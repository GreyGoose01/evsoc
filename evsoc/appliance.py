"""`evsoc run`: the installed device. One process does everything:

  - finds the adapter by itself (evsoc box first) and keeps the car monitored
  - passes the values on (MQTT with Home Assistant discovery, webhook, JSON endpoint)
  - shows a display page without any controls for the end user ("/")
  - offers a PIN-protected setup page that is used once ("/setup")

Security: the display and GET /api/state are read-only and open on the
interface the server is bound to (e.g. eth0 only). Everything that changes
something needs a login with the setup PIN (or the one-time setup code that is
printed to the log on first start), a SameSite=Strict session cookie, a custom
request header and a matching Host header.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, config
from .connection import capabilities_of, check
from .detect import find_adapter
from .elm import AdapterError
from .gui import caps_json, label_for, models, profile_json
from .monitor import Monitor, MqttSink, State, ThrottledFileSink, WebhookSink, load_state, parse_times
from .profiles import load_all
from .reader import autodetect, read, run_init
from .safety import SafetyError
from .transports import TransportError

WEB = Path(__file__).parent / "web"
Log = Callable[[str], None]


class SetupError(Exception):
    pass


def _kwh(value) -> float | None:
    """Nominal battery capacity from the setup page: empty means not set."""
    if value in (None, ""):
        return None
    kwh = float(value)
    if not 5 <= kwh <= 250:
        raise SetupError(f"Nominal capacity {kwh:g} kWh is implausible (5 to 250)")
    return kwh


class Appliance:
    def __init__(self, config_path, open_adapter, log: Log = print, adapter_urls: list[str] | None = None):
        self.config_path = Path(config_path)
        self.open_adapter = open_adapter
        self.adapter_urls = adapter_urls          # tests: fixed candidate list instead of scanning USB
        self.cfg = config.load(self.config_path)
        self.lock = threading.RLock()
        self.logbuf: deque[str] = deque(maxlen=300)
        self._log = log
        self.history: deque[tuple[float, float]] = deque(maxlen=2880)
        self.state: State = load_state(self.cfg.get("state_file"))
        self.adapter_info: dict = {"url": None, "version": None, "caps": None, "error": None}
        self.monitor: Monitor | None = None
        self.outputs: dict[str, object] = {}
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._found_url: str | None = None
        self.sessions: dict[str, float] = {}
        self._fails: deque[float] = deque(maxlen=20)
        self.setup_code = None if self.cfg.get("pin_hash") else secrets.token_hex(3).upper()
        if self.state.soc is not None and self.state.soc_updated:
            self.history.append((time.time(), self.state.soc))

    def log(self, msg: str) -> None:
        self.logbuf.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        self._log(msg)

    # -- adapter -----------------------------------------------------------------------

    def connect(self):
        """Used by the monitor for every (re)connect: the configured or auto-detected adapter."""
        if self.cfg["adapter"] != "auto":
            url = self.cfg["adapter"]
            adapter = self.open_adapter(url, None)
        else:
            urls = [self._found_url] if self._found_url else self.adapter_urls
            try:
                url, adapter = find_adapter(self.open_adapter, self.cfg.get("wired_only", True), self.log, urls)
            except AdapterError:
                if not self._found_url:
                    raise
                self._found_url = None  # the adapter moved to another port: search again
                url, adapter = find_adapter(self.open_adapter, self.cfg.get("wired_only", True), self.log, self.adapter_urls)
            self._found_url = url
        self.adapter_info = {"url": url, "version": adapter.version, "caps": caps_json(capabilities_of(adapter)), "error": None}
        return adapter

    # -- monitor ------------------------------------------------------------------------

    def _sinks(self) -> list:
        self.outputs = {}
        sinks: list = [_MemorySink(self)]
        if self.cfg.get("state_file"):
            sinks.append(ThrottledFileSink(self.cfg["state_file"]))
        out = self.cfg["outputs"]
        if out["mqtt"].get("enabled") and out["mqtt"].get("url"):
            try:
                self.outputs["mqtt"] = MqttSink(out["mqtt"]["url"], self.log)
                sinks.append(self.outputs["mqtt"])
            except AdapterError as e:
                self.log(f"MQTT: {e}")
        if out["webhook"].get("enabled") and out["webhook"].get("url"):
            self.outputs["webhook"] = WebhookSink(out["webhook"]["url"], self.log)
            sinks.append(self.outputs["webhook"])
        return sinks

    def start(self) -> None:
        with self.lock:
            if self._thread:
                return
            profiles = load_all()
            v, m = self.cfg["vehicle"], self.cfg["monitor"]
            self.monitor = Monitor(
                connect=self.connect, profiles=profiles, sinks=self._sinks(),
                profile=profiles.get(v.get("profile") or ""), car=v.get("car"), year=v.get("year"),
                battery_kwh=float(v["battery_kwh"]) if v.get("battery_kwh") else None,
                interval=float(m["interval"]), sleep_interval=float(m["sleep_interval"]),
                awake_voltage=float(m["awake_voltage"]), wake_every=m.get("wake_every"),
                wake_at=parse_times([m["wake_at"]]) if m.get("wake_at") else None,
                min_voltage=float(m.get("min_voltage") or 12.2), state=self.state, log=self.log,
            )
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self.monitor, self._stop), daemon=True)
            self._thread.start()

    def _run(self, monitor: Monitor, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                delay = monitor.tick()
                if monitor.state.status == "no connection" and monitor.adapter is None:
                    self.adapter_info = {**self.adapter_info, "error": "Adapter not reachable"}
                monitor.wait(delay, stop)
        finally:
            monitor._disconnect()
            for sink in monitor.sinks:
                try:
                    sink.close()
                except Exception:  # noqa: BLE001
                    pass

    def stop(self) -> None:
        with self.lock:
            stop, thread = self._stop, self._thread
            self._stop, self._thread, self.monitor = None, None, None
        if stop:
            stop.set()
            if thread:
                thread.join(15)

    @contextmanager
    def paused(self):
        """Stop monitoring while the setup page talks to the adapter directly."""
        self.stop()
        try:
            yield
        finally:
            self.start()

    # -- setup actions --------------------------------------------------------------------

    def detect_adapter(self) -> dict:
        with self.paused():
            self._found_url = None
            try:
                self.connect().close()
            except (AdapterError, TransportError, OSError, ValueError) as e:
                self.adapter_info = {"url": None, "version": None, "caps": None, "error": str(e)}
        return self.adapter_info

    def test_vehicle(self, profile_name: str | None, car: str | None, battery_kwh: float | None = None) -> dict:
        profiles = load_all()
        with self.paused():
            adapter = self.connect()
            try:
                detection = None
                if profile_name:
                    if profile_name not in profiles:
                        raise SetupError(f"Unknown profile {profile_name}")
                    profile = profiles[profile_name]
                    problems = check(profile, capabilities_of(adapter))
                    if problems:
                        raise SetupError("Adapter does not fit this vehicle: " + "; ".join(problems))
                else:
                    det = autodetect(adapter, profiles, car=car or None, log=self.log)
                    if det is None:
                        raise SetupError("No profile returned a plausible state of charge. Ignition or \"Ready\" on?")
                    profile = det.profile
                    detection = {"seconds": round(det.seconds, 1), "also": det.also_plausible[:5], "vin": det.vin, "year": det.year}
                run_init(adapter, profile, self.log)
                reading = read(adapter, profile, None, battery_kwh=battery_kwh)
            finally:
                adapter.close()
        return {
            "profile": profile_json(profile),
            "soc": reading.soc,
            "values": [{"name": v.name, "label": label_for(v.name, v.label), "value": v.value, "unit": v.unit,
                        "plausible": v.plausible, "error": v.error} for v in reading.values.values()],
            "detection": detection,
        }

    def test_output(self, kind: str, url: str) -> dict:
        url = url.strip()
        if ":***@" in url:  # masked password from the setup page: use the stored one
            url = config.apply_public(self.cfg, {"outputs": {"mqtt": {"url": url}}})["outputs"]["mqtt"]["url"]
        test_state = State(status="Test", soc=self.state.soc, checked=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if kind == "webhook":
            sink = WebhookSink(url, self.log)
            sink.publish(test_state)
            return {"ok": bool(sink.ok), "error": sink.error}
        if kind == "mqtt":
            try:
                sink = MqttSink(url, self.log, discovery_prefix="homeassistant")
            except AdapterError as e:
                return {"ok": False, "error": str(e)}
            try:
                ok = sink.connected.wait(6)
                return {"ok": ok, "error": None if ok else (sink.error or "no connection to the broker (address, port, credentials?)")}
            finally:
                sink.close()
        raise SetupError(f"Unknown output {kind}")

    def save(self, update: dict) -> None:
        new = config.apply_public(self.cfg, update)
        v = new["vehicle"]
        v["battery_kwh"] = _kwh(v.get("battery_kwh"))
        if v.get("profile"):
            p = load_all().get(v["profile"])
            if p is None:
                raise SetupError(f"Unknown profile {v['profile']}")
            if not v.get("label"):
                v["label"] = f"{p.vehicles[0].make} {p.vehicles[0].model}" if p.vehicles else p.name
        with self.paused():
            config.save(new, self.config_path)
            self.cfg = new
            if self.state.profile != v.get("profile"):
                self.state.profile = v.get("profile")
        self.log("Settings saved")

    def set_pin(self, pin: str) -> None:
        if len(pin) < 4 or not pin.isdigit():
            raise SetupError("The PIN must have at least 4 digits.")
        self.cfg["pin_hash"] = config.hash_pin(pin)
        config.save(self.cfg, self.config_path)
        self.setup_code = None
        self.log("PIN set")

    # -- auth ------------------------------------------------------------------------------

    def login(self, code: str) -> str:
        now = time.monotonic()
        recent = [t for t in self._fails if now - t < 600]
        if len(recent) >= 10:
            raise SetupError("Too many failed attempts, please wait 10 minutes.")
        ok = (self.setup_code is not None and secrets.compare_digest(code.strip().upper(), self.setup_code)) \
            or config.check_pin(code.strip(), self.cfg.get("pin_hash"))
        if not ok:
            self._fails.append(now)
            time.sleep(1)
            raise SetupError("PIN or setup code wrong.")
        token = secrets.token_urlsafe(24)
        self.sessions[token] = now + 3600
        return token

    def authorised(self, token: str | None) -> bool:
        exp = self.sessions.get(token or "")
        if not exp or exp < time.monotonic():
            self.sessions.pop(token or "", None)
            return False
        self.sessions[token] = time.monotonic() + 3600
        return True

    # -- views -------------------------------------------------------------------------------

    def vehicle_label(self) -> str | None:
        v = self.cfg["vehicle"]
        if v.get("label"):
            return v["label"]
        p = load_all().get(self.state.profile or v.get("profile") or "")
        return f"{p.vehicles[0].make} {p.vehicles[0].model}" if p and p.vehicles else None

    def outputs_status(self) -> list[dict]:
        out = []
        cfg = self.cfg["outputs"]
        if cfg["mqtt"].get("enabled"):
            sink = self.outputs.get("mqtt")
            connected = bool(sink and sink.connected.is_set())
            out.append({"name": "MQTT", "ok": connected,
                        "detail": "connected" if connected else (getattr(sink, "error", None) or "not connected")})
        if cfg["webhook"].get("enabled"):
            sink = self.outputs.get("webhook")
            ok = getattr(sink, "ok", None)
            out.append({"name": "Webhook", "ok": ok,
                        "detail": "nothing sent yet" if ok is None else ("last ok" if ok else sink.error)})
        return out

    def public_state(self) -> dict:
        s = json.loads(self.state.to_json())
        return {
            "vehicle": self.vehicle_label(),
            "configured": bool(self.cfg["vehicle"].get("profile") or self.cfg["vehicle"].get("car") or self.state.profile),
            "status": s["status"],
            "soc": s["soc"],
            "soc_updated": s["soc_updated"],
            "checked": s["checked"],
            "voltage_12v": s["voltage_12v"],
            "note": s["note"],
            "values": [{"name": k, "label": label_for(k), "value": v} for k, v in s["values"].items()
                       if not k.startswith("soc")],
            "adapter": {"ok": bool(self.adapter_info.get("url")) and not self.adapter_info.get("error"),
                        "detail": self.adapter_info.get("error") or (self.adapter_info.get("caps") or {}).get("name") or "searching"},
            "outputs": self.outputs_status(),
            "history": list(self.history),
            "version": __version__,
        }

    def setup_view(self) -> dict:
        return {"config": config.public(self.cfg), "adapter": self.adapter_info, "needs_pin": not self.cfg.get("pin_hash"),
                "log": list(self.logbuf)[-80:], "state": json.loads(self.state.to_json())}


class _MemorySink:
    def __init__(self, app: Appliance):
        self.app = app

    def publish(self, state: State) -> None:
        if state.soc is not None and state.status in ("awake", "woken"):
            self.app.history.append((time.time(), round(state.soc, 2)))

    def close(self) -> None:
        pass


# -- HTTP -----------------------------------------------------------------------------------

def make_handler(app: Appliance, allowed_hosts: set[str]):
    pages = {"/": "app.html", "/setup": "setup.html", "/einrichtung": "setup.html"}

    class Handler(BaseHTTPRequestHandler):
        server_version = f"evsoc/{__version__}"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status=200, extra=None):
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

        def _host_ok(self) -> bool:
            if self.headers.get("Host", "") in allowed_hosts:
                return True
            self._json({"error": "Host not allowed"}, HTTPStatus.FORBIDDEN)
            return False

        def _session(self) -> str | None:
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "evsoc_session":
                    return v
            return None

        def _authorised(self) -> bool:
            if app.authorised(self._session()):
                return True
            self._json({"error": "Please log in"}, HTTPStatus.UNAUTHORIZED)
            return False

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path in pages:
                from .i18n import page as with_i18n
                html = with_i18n((WEB / pages[u.path]).read_text(encoding="utf-8"))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path in ("/api/state", "/api/v1/state"):
                self._json(app.public_state())
            elif u.path == "/api/setup":
                if self._authorised():
                    self._json(app.setup_view())
            elif u.path == "/api/setup/models":
                if self._authorised():
                    self._json(models(q.get("q", "")))
            elif u.path == "/api/auth":
                self._json({"authorised": app.authorised(self._session()), "needs_pin": not app.cfg.get("pin_hash")})
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return
            if self.headers.get("X-Evsoc") != "1" or not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json({"error": "invalid request"}, HTTPStatus.FORBIDDEN)
                return
            u = urlparse(self.path)
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 64_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                if u.path == "/api/login":
                    token = app.login(str(body.get("code", "")))
                    self._json({"ok": True}, extra={"Set-Cookie": f"evsoc_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600"})
                    return
                if u.path == "/api/logout":
                    app.sessions.pop(self._session() or "", None)
                    self._json({"ok": True}, extra={"Set-Cookie": "evsoc_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
                    return
                if not self._authorised():
                    return
                if u.path == "/api/setup/pin":
                    app.set_pin(str(body.get("pin", "")))
                    self._json({"ok": True})
                elif u.path == "/api/setup/detect-adapter":
                    self._json(app.detect_adapter())
                elif u.path == "/api/setup/test-vehicle":
                    self._json(app.test_vehicle(body.get("profile"), body.get("car"), _kwh(body.get("battery_kwh"))))
                elif u.path == "/api/setup/test-output":
                    self._json(app.test_output(str(body.get("kind")), str(body.get("url", ""))))
                elif u.path == "/api/wake":
                    if app.monitor is None:
                        raise SetupError("Monitoring is not running.")
                    app.monitor.request_wake("setup page")
                    app.log("Reading requested (wakes the car if it is asleep)")
                    self._json({"ok": True})
                elif u.path == "/api/setup/save":
                    app.save(body)
                    self._json({"ok": True})
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (SetupError, AdapterError, TransportError, SafetyError, ValueError, OSError) as e:
                app.log(f"Setup: {e}")
                self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

    return Handler


class _V6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def serve(app: Appliance, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), None)  # type: ignore[arg-type]
    real_port = server.server_address[1]
    loopback = host in ("127.0.0.1", "localhost", "::1")
    names = {"127.0.0.1", "localhost", "[::1]"} if loopback else {host}
    if not loopback:
        hn = socket.gethostname()
        names |= {hn, f"{hn}.local", hn.split(".")[0], f"{hn.split('.')[0]}.local"}
    server.RequestHandlerClass = make_handler(app, {f"{n}:{real_port}" for n in names} | ({f"{n}" for n in names} if real_port == 80 else set()))
    server.extra = []  # type: ignore[attr-defined]
    if loopback:
        try:
            v6 = _V6(("::1", real_port), server.RequestHandlerClass)
            threading.Thread(target=v6.serve_forever, daemon=True).start()
            server.extra.append(v6)  # type: ignore[attr-defined]
        except OSError:
            pass
    return server
