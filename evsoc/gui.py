"""Local web GUI: `evsoc gui` starts a small HTTP server and opens the browser.

Standard library only. The page (evsoc/web/index.html) talks to a JSON API:

  GET  /api/info, /api/devices, /api/devices/ble, /api/models?q=, /api/plan?profile=|car=, /api/status,
       /api/job, /api/probe, /api/probe/report, /api/reports
  POST /api/connect {url}, /api/disconnect, /api/read {profile|car, all, battery_kwh},
       /api/monitor/start {...}, /api/monitor/stop, /api/monitor/wake,
       /api/probe/start {car, notes, all, raw, diagnose}, /api/probe/load {report|name, notes},
       /api/raw {commands}, /api/busscan, /api/waketest/start {url, profile, car, minutes}, /api/sniff/start {url, seconds, values}, /api/sniff/analyze {text, values}

Long work (test drive, listening in) runs as one background job; the page polls /api/job.
Reports of test drives are also saved to ~/evsoc-reports (or $EVSOC_REPORTS).

Security: binds to 127.0.0.1 by default. Every API call needs the session
token that is embedded into the served page (custom header -> no cross-site
requests), and the Host header must match, which blocks DNS rebinding.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from collections import Counter, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, broadcast, probe
from .connection import alternatives, buses, capabilities_of, check, recommend
from .elm import AdapterError
from .monitor import Monitor, State, parse_times
from .profiles import Profile, candidates, load_all
from .reader import autodetect, read, run_init
from .safety import SafetyError
from .transports import TransportError

WEB = Path(__file__).parent / "web"


class GuiError(Exception):
    pass


class MemorySink:
    def __init__(self, session: Session):
        self.session = session

    def publish(self, state: State) -> None:
        with self.session.lock:
            self.session.monitor_state = json.loads(state.to_json())
            self.session.monitor_state["labels"] = {k: label_for(k) for k in state.values}
            if state.soc is not None and state.status in ("awake", "woken"):
                self.session.add_history(state.soc)

    def close(self) -> None:
        pass


class Session:
    """Everything the GUI remembers between requests. One adapter at a time."""

    def __init__(self, open_adapter, wired_only: bool = False):
        self.open_adapter = open_adapter
        self.wired_only = wired_only
        self.lock = threading.RLock()
        self.adapter = None
        self.url: str | None = None
        self.profile: Profile | None = None
        self.year: int | None = None
        self.last: dict | None = None
        self.history: deque[tuple[float, float]] = deque(maxlen=720)
        self.log: deque[str] = deque(maxlen=200)
        self.monitor: Monitor | None = None
        self.monitor_state: dict | None = None
        self._monitor_stop: threading.Event | None = None
        self._monitor_thread: threading.Thread | None = None
        self.job: dict = {"kind": None, "running": False, "lines": [], "error": None, "result": None}
        self._job_thread: threading.Thread | None = None
        self.report: dict | None = None   # last test drive (evsoc probe)
        self.last_request = time.monotonic()

    def say(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    def add_history(self, soc: float) -> None:
        self.history.append((time.time(), round(soc, 2)))

    # -- adapter -------------------------------------------------------------------

    def connect(self, url: str) -> dict:
        if self.wired_only:
            from .wired import check_url
            check_url(url)
        with self.lock:
            self._need_idle()
            self.disconnect()
            self.say(f"Connecting to {url} ...")
            self.adapter = self.open_adapter(url, None)
            self.url = url
            self.profile = None
            caps = capabilities_of(self.adapter)
            self.say(f"Connected: {self.adapter.version}")
            return {"version": self.adapter.version, "caps": caps_json(caps)}

    def disconnect(self) -> None:
        with self.lock:
            if self.job["running"] and self.job["kind"] == "Test drive":
                raise GuiError("The test drive is still running. Please wait.")
            if self.adapter is not None:
                try:
                    self.adapter.close()
                except Exception:  # noqa: BLE001
                    pass
                self.say("Disconnected")
            self.adapter, self.url, self.profile = None, None, None

    def read(self, profile_name: str | None, car: str | None, all_values: bool, battery_kwh: float | None = None) -> dict:
        profiles = load_all()
        with self.lock:
            if self.job["running"]:
                raise GuiError(f"Still running: {self.job['kind']}. Please wait.")
            if self.monitor:
                raise GuiError("Continuous operation is running and reads by itself; values are shown there.")
            if self.adapter is None:
                raise GuiError("No adapter connected.")
            detection = None
            if profile_name:
                if profile_name not in profiles:
                    raise GuiError(f"Unknown profile {profile_name}")
                profile = profiles[profile_name]
                problems = check(profile, capabilities_of(self.adapter), self.year)
                if problems:
                    raise GuiError("Adapter does not fit: " + "; ".join(problems))
                if self.profile is not profile:
                    run_init(self.adapter, profile, self.say)
                self.profile = profile
            elif self.profile is None or car:
                det = autodetect(self.adapter, profiles, car=car or None, log=self.say)
                if det is None:
                    raise GuiError("No profile returned a plausible state of charge (ignition on?).")
                self.profile, self.year = det.profile, det.year
                detection = {"tried": det.tried, "seconds": round(det.seconds, 1),
                             "also": det.also_plausible[:6], "vin": det.vin}
                run_init(self.adapter, self.profile, self.say)
            names = None if all_values else [f.name for f in self.profile.soc_fields]
            reading = read(self.adapter, self.profile, names, self.year, battery_kwh)
            result = {
                "profile": profile_json(self.profile),
                "soc": reading.soc,
                "values": [
                    {"name": v.name, "label": label_for(v.name, v.label), "value": v.value,
                     "unit": v.unit, "plausible": v.plausible, "error": v.error}
                    for v in reading.values.values()
                ],
                "raw": reading.raw,
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "detection": detection,
            }
            self.last = result
            if reading.soc is not None:
                self.add_history(reading.soc)
                self.say(f"State of charge {reading.soc:.1f} % ({self.profile.name})")
            return result

    # -- monitor -------------------------------------------------------------------

    def start_monitor(self, opts: dict) -> None:
        profiles = load_all()
        with self.lock:
            if self.monitor:
                raise GuiError("Continuous operation is already running.")
            self._need_idle()
            url = opts.get("url") or self.url
            if not url:
                raise GuiError("Adapter address missing.")
            profile = profiles.get(opts.get("profile") or "") or self.profile
            self.disconnect()  # the monitor opens its own connection and reconnects by itself
            self.monitor = Monitor(
                connect=lambda: self.open_adapter(url, None),
                profiles=profiles,
                sinks=[MemorySink(self)],
                profile=profile,
                car=opts.get("car") or None,
                battery_kwh=float(opts["battery_kwh"]) if opts.get("battery_kwh") else None,
                interval=float(opts.get("interval") or 60),
                sleep_interval=float(opts.get("sleep_interval") or 300),
                awake_voltage=float(opts.get("awake_voltage") or 13.0),
                wake_every=float(opts["wake_every"]) if opts.get("wake_every") else None,
                wake_at=parse_times([opts["wake_at"]]) if opts.get("wake_at") else None,
                log=self.say,
            )
            self.url = url
            stop = threading.Event()
            self._monitor_stop = stop
            self._monitor_thread = threading.Thread(target=self._run_monitor, args=(self.monitor, stop), daemon=True)
            self._monitor_thread.start()
            self.say("Continuous operation started")

    def _run_monitor(self, monitor: Monitor, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                delay = monitor.tick()
                monitor.wait(delay, stop)
        finally:
            monitor._disconnect()

    def stop_monitor(self) -> None:
        with self.lock:
            stop, thread = self._monitor_stop, self._monitor_thread
            self.monitor, self._monitor_stop, self._monitor_thread = None, None, None
        if stop:
            stop.set()
            if thread:
                thread.join(10)
            self.say("Continuous operation stopped")

    # -- background job (one at a time) -----------------------------------------------

    def _need_idle(self) -> None:
        if self.job["running"]:
            raise GuiError(f"Still running: {self.job['kind']}. Please wait.")
        if self.monitor:
            raise GuiError("Stop continuous operation first.")

    def start_job(self, kind: str, work) -> None:
        """`work(say)` runs in a thread; its return value ends up in job['result']."""
        with self.lock:
            self._need_idle()
            job = {"kind": kind, "running": True, "lines": [], "error": None, "result": None}
            self.job = job

        def say(msg: str) -> None:
            job["lines"].append(str(msg))
            del job["lines"][:-400]

        def run() -> None:
            try:
                job["result"] = work(say)
            except (GuiError, AdapterError, TransportError, SafetyError, ValueError, OSError) as e:
                job["error"] = str(e)
                self.say(f"Error ({kind}): {e}")
            except Exception as e:  # noqa: BLE001 - a job must never die silently
                job["error"] = f"{type(e).__name__}: {e}"
                self.say(f"Error ({kind}): {job['error']}")
            finally:
                job["running"] = False

        self._job_thread = threading.Thread(target=run, daemon=True)
        self._job_thread.start()

    def wait_job(self, timeout: float = 60) -> dict:
        if self._job_thread:
            self._job_thread.join(timeout)
        return self.job

    # -- test drive -------------------------------------------------------------------

    def start_probe(self, opts: dict) -> None:
        from .cli import expand_commands
        profiles = load_all()
        notes = probe.parse_notes(split_list(opts.get("notes")))
        raw = expand_commands(str(opts.get("raw") or "").split())
        with self.lock:
            self._need_idle()
            if self.adapter is None:
                raise GuiError("No adapter connected.")
            adapter, url = self.adapter, self.url or ""
        kwh = opts.get("battery_kwh")

        def work(say):
            report = probe.run(adapter, profiles, adapter_url=url, car=(opts.get("car") or "").strip() or None,
                               everything=bool(opts.get("all")), raw_commands=raw, notes=notes,
                               battery_kwh=float(kwh) if kwh else None, diagnose=opts.get("diagnose", True) is not False,
                               log=say)
            self.profile = None  # the adapter was reconfigured many times
            folder = reports_dir()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / probe.default_path(report)
            report["file"] = str(path)
            probe.save(report, str(path))
            self.report = report
            self.say(f"Test drive finished: {path}")
            return {"file": str(path)}

        self.start_job("Test drive", work)

    def load_report(self, body: dict) -> dict:
        profiles = load_all()
        notes = probe.parse_notes(split_list(body.get("notes")))
        if body.get("name"):
            path = reports_dir() / Path(str(body["name"])).name  # no path components from the page
            if not path.is_file():
                raise GuiError(f"Report {path.name} not found")
            report = probe.load(str(path), profiles, notes)
            report["file"] = str(path)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "report.json"
                path.write_text(json.dumps(body.get("report") or {}), encoding="utf-8")
                report = probe.load(str(path), profiles, notes)
            report["file"] = None
        self.report = report
        self.say("Report re-evaluated with the current profiles")
        return probe.view(report, label_for)

    # -- tools --------------------------------------------------------------------------

    def raw(self, text: str, hits_only: bool = False) -> list[dict]:
        from .cli import expand_commands
        commands = expand_commands(text.split())
        with self.lock:
            self._need_idle()
            if self.adapter is None:
                raise GuiError("No adapter connected.")
            self.profile = None
            out = []
            for cmd in commands:
                item = {"cmd": cmd}
                try:
                    if cmd.upper().startswith(("AT", "ST")):
                        self.adapter.at(cmd)
                        item["ok"] = True
                    else:
                        r = self.adapter.request(cmd)
                        item.update(ecu=r.ecu, payload=r.payload.hex(" ").upper())
                except (AdapterError, SafetyError) as e:
                    item["error"] = str(e)
                if not hits_only or "payload" in item:
                    out.append(item)
            self.say(f"{len(commands)} raw commands, {sum('payload' in i for i in out)} answers")
            return out

    def bus_scan(self) -> dict:
        with self.lock:
            self._need_idle()
            if self.adapter is None:
                raise GuiError("No adapter connected.")
            if hasattr(self.adapter, "scan"):
                found = self.adapter.scan()
                self.profile = None
                return {"buses": [{**b, "pins": "/".join(map(str, b["pins"]))} for b in found]}
            if hasattr(self.adapter, "bus_active"):
                return {"active": bool(self.adapter.bus_active(2.0))}
            raise GuiError("Bus scanning needs the evsoc box (box:…). Normal adapters only see pins 6/14.")

    def sniff_file(self, text: str, values: list[str], tolerance: float | None = None) -> dict:
        from . import sniff
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.log"
            path.write_text(text, encoding="utf-8")
            frames, markers = sniff.read_log(str(path))
        if not frames:
            raise GuiError("No CAN frames recognised in the file (candump, ATMA text or CL2000 text).")
        sniffer = sniff.Sniffer(sniff.KnownIndex(load_all()))
        for f in frames:
            sniffer.feed(f)
        sniffer.tick(float("inf"))
        sniffer.markers += markers
        return self._sniff_result(sniffer, values, tolerance, f"{len(frames)} frames read")

    def _sniff_result(self, sniffer, values: list[str], tolerance: float | None, head: str) -> dict:
        from . import sniff
        for text in values:
            sniffer.markers.append(sniff.parse_marker(text, sniffer.first_t))
        formulas = sniff.find_formulas(sniffer.conversations, sniffer.markers, tolerance)
        lines = [head]
        sniff.report(sniffer, formulas, out=lambda m="": lines.append(str(m)))
        return {"text": "\n".join(lines), "data": sniff.report_json(sniffer, formulas)}

    def start_sniff(self, opts: dict) -> None:
        from . import sniff
        from .cli import open_sniff_source
        url = str(opts.get("url") or self.url or "").strip()
        if not url:
            raise GuiError("Adapter address missing.")
        if self.wired_only:
            from .wired import check_url
            check_url(url)
        seconds = min(max(float(opts.get("seconds") or 60), 1), 3600)
        values = split_list(opts.get("values"))
        reference = str(opts.get("reference") or "").strip()
        if reference and self.wired_only:
            from .wired import check_url
            check_url(reference)
        pins = tuple(int(x) for x in str(opts.get("pins") or "6,14").split(","))
        with self.lock:
            self._need_idle()
            self.disconnect()  # listening opens the adapter in its own mode

        def work(say):
            source = open_sniff_source(url, str(opts.get("protocol") or "6"), pins)
            folder = reports_dir()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / time.strftime("capture-%Y%m%d-%H%M%S.log")
            writer = sniff.LogWriter(str(path), source.description)
            sniffer = sniff.Sniffer(sniff.KnownIndex(load_all()))
            say(f"Listening: {source.description}. evsoc sends nothing. Duration {seconds:g} s.")
            typed = self._typed = broadcast.Feed()
            ref = None
            if reference:
                ref = broadcast.Reference(lambda: self.open_adapter(reference, None), load_all(), typed,
                                          car=(opts.get("car") or "").strip() or None, log=say)
                ref.start()
            try:
                sniff.run_live(source, sniffer, writer, duration=seconds, show_all=False, out=say, stdin=typed)
            finally:
                self._typed = None
                if ref is not None:
                    ref.finish()
                typed.close()
            sniffer.tick(float("inf"))
            result = self._sniff_result(sniffer, values, None, f"Capture saved: {path}")
            self.say(f"Listening finished: {path}")
            return result

        self.start_job("Listening", work)

    def sniff_mark(self, text: str) -> None:
        from . import sniff
        sniff.parse_marker(text)  # complain right away about a malformed value
        typed = getattr(self, "_typed", None)
        if typed is None:
            raise GuiError("Not listening right now.")
        typed.queue.put(text)

    def start_waketest(self, opts: dict) -> None:
        from . import waketest
        profiles = load_all()
        url = str(opts.get("url") or self.url or "").strip()
        if not url:
            raise GuiError("Adapter address missing.")
        if self.wired_only:
            from .wired import check_url
            check_url(url)
        profile = profiles.get(opts.get("profile") or "")
        minutes = min(max(float(opts.get("minutes") or 20), 0.01), 240)
        step = min(max(float(opts.get("step") or 30), 0.05), 600)
        with self.lock:
            self._need_idle()
            self.disconnect()  # the test opens the adapter itself, like the continuous operation does

        def work(say):
            report = waketest.run(lambda: self.open_adapter(url, None), profiles, adapter_url=url, profile=profile,
                                  car=(opts.get("car") or "").strip() or None, watch_minutes=minutes, step=step, log=say)
            folder = reports_dir()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / waketest.default_path()
            waketest.save(report, str(path))
            self.say(f"Wake test finished: {path}")
            return {"text": waketest.summary(report) + f"\n\nReport: {path}", "woke": bool(report["wake"].get("woke"))}

        self.start_job("Wake test", work)

    def wake_now(self) -> None:
        with self.lock:
            if self.monitor is None:
                raise GuiError("Continuous operation is not running.")
            self.monitor.request_wake("interface")
            self.say("Reading requested (wakes the car if it is asleep)")

    def status(self) -> dict:
        with self.lock:
            return {
                "connected": self.adapter is not None,
                "url": self.url,
                "version": getattr(self.adapter, "version", None),
                "caps": caps_json(capabilities_of(self.adapter)) if self.adapter else None,
                "profile": profile_json(self.profile) if self.profile else None,
                "last": self.last,
                "history": list(self.history),
                "monitor": {"running": self.monitor is not None, "state": self.monitor_state},
                "job": {"kind": self.job["kind"], "running": self.job["running"]},
                "has_report": self.report is not None,
                "log": list(self.log)[-60:],
            }


def reports_dir() -> Path:
    return Path(os.environ.get("EVSOC_REPORTS") or os.environ.get("EVSOC_BERICHTE") or Path.home() / "evsoc-reports")


def split_list(value) -> list[str]:
    """'soc=54, km=23150' or ['soc=54', ...] -> list of items."""
    if not value:
        return []
    if isinstance(value, str):
        return [v for v in re.split(r"[;\n]|,\s+|\s+", value.strip()) if v]
    return [str(v) for v in value]


def saved_reports() -> list[dict]:
    folder = reports_dir()
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("evsoc-probe-*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)),
             "kb": round(f.stat().st_size / 1024)} for f in files[:50]]


def label_for(name: str, label: str = "") -> str:
    from .cli import LABELS
    if name.startswith("soc_") and name not in LABELS and label:
        return f"State of charge: {label}"
    return LABELS.get(name) or label or name


def caps_json(caps) -> dict:
    return {"name": caps.name, "kinds": sorted(caps.kinds),
            "pins": None if caps.pins is None else ["/".join(map(str, p)) for p in sorted(caps.pins)],
            "listen": caps.listen}


def profile_json(p: Profile) -> dict:
    return {"name": p.name, "description": p.description, "platform": p.platform, "source": p.source,
            "verified": p.verified, "vehicles": [str(v) for v in p.vehicles], "listen": p.needs_listen}


def models(query: str) -> list[dict]:
    q = query.strip()
    out = []
    for p in load_all().values():
        if p.generic or (q and not p.matches_text(q)):
            continue
        for v in p.vehicles:
            out.append({"label": str(v), "make": v.make, "profile": p.name, "platform": p.platform,
                        "listen": p.needs_listen, "source": p.name.split("_", 1)[0]})
    out.sort(key=lambda r: (r["make"].lower(), r["label"].lower(), r["source"] != "evsoc"))
    return out[:400]


def plan(profile_name: str | None, car: str | None, session: Session) -> list[dict]:
    profiles = load_all()
    if profile_name:
        chosen = [profiles[profile_name]] if profile_name in profiles else []
    else:
        chosen = [p for p in candidates(profiles, car=car) if car and p.matches_text(car) and not p.generic][:8]
    caps = capabilities_of(session.adapter) if session.adapter else None
    result = []
    for p in chosen:
        result.append({
            "profile": profile_json(p),
            "buses": [b.describe() for b in buses(p)],
            "alternatives": [b.describe() for b in alternatives(p)],
            "adapters": [{"name": c.name, "ok": not problems, "problems": problems} for c, problems in recommend(p)],
            "adapter_check": None if caps is None else {"name": caps.name, "problems": check(p, caps)},
        })
    return result


def devices(ble: bool = False, wired_only: bool = False) -> dict:
    from .wired import socketcan_interfaces, usb_serial_ports
    out: dict = {"serial": [], "ble": [], "examples": [], "wired_only": wired_only}
    usb = usb_serial_ports()
    out["serial"] = [{"url": p["device"], "label": f"{p['device']}  {p['description']} (USB)"} for p in usb]
    out["serial"] += [{"url": f"can://socketcan/{n}", "label": f"CAN interface {n} (SocketCAN)"} for n in socketcan_interfaces()]
    if not wired_only:
        try:
            from serial.tools import list_ports
            usb_paths = {p["device"] for p in usb}
            out["serial"] += [{"url": p.device, "label": f"{p.device}  (Bluetooth/serial)"} for p in list_ports.comports()
                              if p.device not in usb_paths and "Bluetooth-Incoming" not in p.device and "debug" not in p.device]
        except ImportError:
            pass
    if ble and wired_only:
        out["ble_error"] = "Bluetooth is off in wired-only mode."
    elif ble:
        try:
            import asyncio

            from bleak import BleakScanner
            found = asyncio.run(BleakScanner.discover(timeout=5))
            out["ble"] = [{"url": f"ble://{d.name or d.address}", "label": f"{d.name or '?'}  ({d.address})"}
                          for d in found if d.name]
        except ImportError:
            out["ble_error"] = "bleak missing (pip install bleak)"
    from .mock import BOX_CARS, BROADCAST, VEHICLES
    out["examples"] = (
        ([] if wired_only else [{"url": "tcp://192.168.0.10:35000", "label": "WiFi adapter (default address)"}])
        + [{"url": "enet://auto", "label": "BMW/Mini ENET cable"}]
        + [{"url": f"mock://{v}", "label": f"Test vehicle {v} (no car)"} for v in [*VEHICLES, *BROADCAST]]
        + [{"url": f"box:mock://{v}", "label": f"Simulated evsoc box: {v}"} for v in BOX_CARS]
    )
    return out


def info(wired_only: bool = False) -> dict:
    profiles = load_all()
    makes = {v.make for p in profiles.values() for v in p.vehicles if not p.generic}
    sources = Counter(p.name.split("_", 1)[0] for p in profiles.values())
    return {"version": __version__, "profiles": len(profiles), "makes": len(makes), "sources": dict(sources),
            "wired_only": wired_only}


def make_handler(session: Session, token: str, allowed_hosts: set[str], page_needs_token: bool = False,
                 wired_only: bool = False):
    from .i18n import page as with_i18n
    index_html = with_i18n((WEB / "index.html").read_text(encoding="utf-8"))

    class Handler(BaseHTTPRequestHandler):
        server_version = f"evsoc/{__version__}"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _allowed(self) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._json({"error": "Host not allowed"}, HTTPStatus.FORBIDDEN)
                return False
            return True

        def _authorised(self) -> bool:
            if not self._allowed():
                return False
            if not secrets.compare_digest(self.headers.get("X-Evsoc-Token", ""), token):
                self._json({"error": "Token missing or wrong"}, HTTPStatus.FORBIDDEN)
                return False
            return True

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                if page_needs_token and not secrets.compare_digest(parse_qs(u.query).get("token", [""])[0], token):
                    self._send(HTTPStatus.FORBIDDEN, "Access only with the link from the terminal (…/?token=…)".encode(),
                               "text/plain; charset=utf-8")
                    return
                if self._allowed():
                    page = index_html.replace("__EVSOC_TOKEN__", token)
                    self._send(200, page.encode(), "text/html; charset=utf-8")
                return
            if not u.path.startswith("/api/"):
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            if not self._authorised():
                return
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            session.last_request = time.monotonic()
            try:
                if u.path == "/api/info":
                    self._json(info(wired_only))
                elif u.path == "/api/devices":
                    self._json(devices(wired_only=wired_only))
                elif u.path == "/api/devices/ble":
                    self._json(devices(ble=True, wired_only=wired_only))
                elif u.path == "/api/models":
                    self._json(models(q.get("q", "")))
                elif u.path == "/api/plan":
                    self._json(plan(q.get("profile"), q.get("car"), session))
                elif u.path == "/api/status":
                    self._json(session.status())
                elif u.path == "/api/job":
                    job = session.job
                    self._json({"kind": job["kind"], "running": job["running"], "lines": job["lines"][-200:],
                                "error": job["error"], "result": job["result"]})
                elif u.path == "/api/probe":
                    self._json({"report": probe.view(session.report, label_for) if session.report else None})
                elif u.path == "/api/probe/report":
                    if session.report is None:
                        self._json({"error": "No test drive yet"}, HTTPStatus.NOT_FOUND)
                    else:
                        self._json(session.report)
                elif u.path == "/api/reports":
                    self._json({"folder": str(reports_dir()), "reports": saved_reports()})
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as e:  # noqa: BLE001 - report every failure to the page
                self._json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self):  # noqa: N802
            u = urlparse(self.path)
            if not self._authorised():
                return
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json({"error": "JSON expected"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                big = u.path in ("/api/probe/load", "/api/sniff/analyze")  # uploaded reports and captures
                length = int(self.headers.get("Content-Length", 0))
                if length > (64_000_000 if big else 64_000):
                    self._json({"error": "Request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                session.last_request = time.monotonic()
                if u.path == "/api/connect":
                    self._json(session.connect(str(body.get("url", "")).strip()))
                elif u.path == "/api/disconnect":
                    session.disconnect()
                    self._json({"ok": True})
                elif u.path == "/api/read":
                    kwh = body.get("battery_kwh")
                    self._json(session.read(body.get("profile"), body.get("car"), bool(body.get("all")),
                                            float(kwh) if kwh else None))
                elif u.path == "/api/monitor/start":
                    if session.wired_only and body.get("url"):
                        from .wired import check_url
                        check_url(str(body["url"]))
                    session.start_monitor(body)
                    self._json({"ok": True})
                elif u.path == "/api/monitor/stop":
                    session.stop_monitor()
                    self._json({"ok": True})
                elif u.path == "/api/waketest/start":
                    session.start_waketest(body)
                    self._json({"ok": True})
                elif u.path == "/api/monitor/wake":
                    session.wake_now()
                    self._json({"ok": True})
                elif u.path == "/api/probe/start":
                    session.start_probe(body)
                    self._json({"ok": True})
                elif u.path == "/api/probe/load":
                    self._json({"report": session.load_report(body)})
                elif u.path == "/api/raw":
                    self._json({"results": session.raw(str(body.get("commands", "")), bool(body.get("hits_only")))})
                elif u.path == "/api/busscan":
                    self._json(session.bus_scan())
                elif u.path == "/api/sniff/start":
                    session.start_sniff(body)
                    self._json({"ok": True})
                elif u.path == "/api/sniff/mark":
                    session.sniff_mark(str(body.get("text", "")))
                    self._json({"ok": True})
                elif u.path == "/api/sniff/analyze":
                    tol = body.get("tolerance")
                    self._json(session.sniff_file(str(body.get("text", "")), split_list(body.get("values")),
                                                  float(tol) if tol else None))
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (GuiError, AdapterError, TransportError, SafetyError, ValueError, OSError) as e:
                session.say(f"Error: {e}")
                self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

    return Handler


def serve(open_adapter, host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True,
          token: str | None = None, wired_only: bool = False) -> ThreadingHTTPServer:
    """Create the server (call .serve_forever() on it)."""
    token = token or secrets.token_urlsafe(18)
    session = Session(open_adapter, wired_only)
    server = ThreadingHTTPServer((host, port), None)  # type: ignore[arg-type]
    real_port = server.server_address[1]
    names = {"127.0.0.1", "localhost", "[::1]"} if host in ("127.0.0.1", "localhost", "::1") else {host}
    if host == "0.0.0.0":
        import socket
        names |= {socket.gethostname(), f"{socket.gethostname()}.local", "127.0.0.1", "localhost"}
        try:
            names.add(socket.gethostbyname(socket.gethostname()))
        except OSError:
            pass
    allowed = {f"{n}:{real_port}" for n in names}
    loopback = host in ("127.0.0.1", "localhost", "::1")
    server.RequestHandlerClass = make_handler(session, token, allowed, page_needs_token=not loopback, wired_only=wired_only)
    server.session = session  # type: ignore[attr-defined]
    server.token = token  # type: ignore[attr-defined]
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{real_port}/" + ("" if loopback else f"?token={token}")
    server.url = url  # type: ignore[attr-defined]
    server.extra = []  # type: ignore[attr-defined]
    if loopback and host != "::1":
        # browsers often resolve "localhost" to ::1 first; listen there too (still loopback only)
        try:
            v6 = _V6Server(("::1", real_port), server.RequestHandlerClass)
            threading.Thread(target=v6.serve_forever, daemon=True).start()
            server.extra.append(v6)  # type: ignore[attr-defined]
        except OSError:
            pass
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    return server


APP_BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser",
                "microsoft-edge", "vivaldi")


def open_window(url: str) -> str:
    """Show the page in a window of its own (Chromium-style --app), else in the default browser."""
    for name in APP_BROWSERS:
        binary = shutil.which(name)
        if binary:
            subprocess.Popen([binary, f"--app={url}", "--window-size=1280,860"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return name
    webbrowser.open(url)
    return "default browser"


def idle_seconds(server) -> float:
    """How long the page has not asked for anything (it polls every 2 s while open)."""
    s = server.session
    if s.monitor is not None or s.job["running"]:
        return 0.0
    return time.monotonic() - s.last_request


DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=evsoc
GenericName=EV battery state
GenericName[de]=Ladestand und Batteriewerte von E-Autos
Comment=Read state of charge, battery values and fault memory through the OBD socket (read only)
Comment[de]=Ladestand, Batteriewerte und Fehlerspeicher über die OBD-Buchse lesen (nur lesend)
Exec={exec} gui --fenster
Icon={icon}
Terminal=false
Categories=Utility;Electronics;
Keywords=OBD;EV;SoC;battery;car;Batterie;Auto;
StartupNotify=true
"""

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<rect width="128" height="128" rx="28" fill="#10231c"/>
<rect x="26" y="40" width="68" height="48" rx="10" fill="none" stroke="#4cc596" stroke-width="8"/>
<rect x="98" y="54" width="8" height="20" rx="3" fill="#4cc596"/>
<path d="M64 46 48 68h13l-5 16 18-24H60z" fill="#4cc596"/>
</svg>
"""


def desktop_paths() -> tuple[Path, Path]:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "applications" / "evsoc.desktop", data / "icons" / "hicolor" / "scalable" / "apps" / "evsoc.svg"


def install_desktop(executable: str) -> tuple[Path, Path]:
    """Put evsoc into the application menu of the Linux desktop (no terminal needed afterwards)."""
    entry, icon = desktop_paths()
    entry.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text(ICON_SVG, encoding="utf-8")
    entry.write_text(DESKTOP_ENTRY.format(exec=executable, icon=icon), encoding="utf-8")
    entry.chmod(0o755)
    return entry, icon


def remove_desktop() -> list[Path]:
    removed = []
    for path in desktop_paths():
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


class _V6Server(ThreadingHTTPServer):
    import socket as _socket
    address_family = _socket.AF_INET6
