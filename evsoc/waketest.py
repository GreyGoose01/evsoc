"""Wake test: can this car be woken through the OBD socket, and does it go back to sleep?

Whether a parked car answers after a diagnostic request depends on the car, the adapter and the
bus. This test measures it instead of guessing:

  1. state before: reachable? 12 V voltage? awake?
  2. wake: read the state of charge, a few tries; time until the first answer
  3. watch without bus traffic where the adapter allows it, until the car sleeps again

The result is a small JSON report with a timeline, for deciding how (and whether) to wake this car
in continuous operation. Guard: never wakes below `min_voltage`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .elm import AdapterError
from .monitor import car_awake
from .profiles import Profile
from .reader import autodetect, read, run_init
from .safety import SafetyError
from .transports import TransportError

Log = Callable[[str], None]
FORMAT = 1


def _connect(connect, tries: int, pause, log: Log):
    """Open the adapter; over ENET a sleeping car is simply not there, so a few tries count as waking."""
    error = ""
    for attempt in range(1, tries + 1):
        try:
            return connect(), attempt, error
        except (AdapterError, TransportError, OSError) as e:
            error = str(e)
            log(f"  Connection, attempt {attempt}/{tries}: {error}")
            if attempt < tries:
                pause(3.0)
    return None, tries, error


def run(connect, profiles: dict[str, Profile], *, adapter_url: str = "", profile: Profile | None = None, car: str | None = None,
        awake_voltage: float = 13.0, min_voltage: float = 12.2, watch_minutes: float = 20, step: float = 30,
        wake_tries: int = 5, log: Log = print, now: Callable[[], float] = time.monotonic,
        pause: Callable[[float], None] = time.sleep) -> dict:
    report: dict = {"format": FORMAT, "kind": "waketest", "evsoc": __version__, "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "adapter": {"url": adapter_url}, "settings": {"awake_voltage": awake_voltage, "min_voltage": min_voltage,
                                                                  "watch_minutes": watch_minutes, "step": step},
                    "before": {}, "wake": {"attempts": []}, "timeline": [], "verdict": []}
    start = now()
    log("1. State before ...")
    adapter, tries, error = _connect(connect, 1, pause, log)
    if adapter is None:
        report["before"] = {"reachable": False, "error": error}
        log("  Adapter or car not reachable. With ENET that usually means the car is asleep. Trying further ...")
        adapter, tries, error = _connect(connect, wake_tries, pause, log)
        if adapter is None:
            report["wake"].update(woke=False, error=error)
            report["verdict"] = ["No connection. The car cannot be reached or woken this way through this adapter.",
                                 "Check: is the adapter plugged in and powered? Over ENET a sleeping car does not answer."]
            return _finish(report, start, now)
        report["wake"]["connected_after_tries"] = tries + 1
    try:
        awake, volt, how = car_awake(adapter, awake_voltage)
        report["adapter"].update(version=getattr(adapter, "version", ""), awake_by=how)
        report["before"].update(reachable=report["before"].get("reachable", True), awake=awake, voltage=volt)
        log(f"  {'awake' if awake else 'asleep'} ({how}" + (f", {volt:.2f} V" if volt is not None else "") + ")")
        if awake:
            report["verdict"].append("The car was already awake at the start. The test then says nothing about waking, only about when it falls asleep again. For the wake test: lock the car and wait 15–30 minutes.")
        if not awake and volt is not None and volt < min_voltage:
            report["wake"].update(woke=False, error="12 V battery too weak")
            report["verdict"].append(f"Not woken: 12 V battery only {volt:.2f} V (limit {min_voltage:g} V).")
            return _finish(report, start, now)

        log("2. Waking: reading the state of charge ...")
        t_wake = now()
        soc = None
        for attempt in range(1, wake_tries + 1):
            entry = {"attempt": attempt, "t": round(now() - t_wake, 1)}
            try:
                if profile is None:
                    det = autodetect(adapter, profiles, car=car, log=lambda _m: None)
                    if det is not None:
                        profile, soc = det.profile, det.reading.soc
                else:
                    run_init(adapter, profile)
                    soc = read(adapter, profile, [f.name for f in profile.soc_fields]).soc
            except (AdapterError, SafetyError) as e:
                entry["error"] = str(e)
            entry["soc"] = soc
            entry["seconds"] = round(now() - t_wake, 1)
            report["wake"]["attempts"].append(entry)
            log(f"  Attempt {attempt}: " + (f"state of charge {soc:.1f} % after {entry['seconds']:g} s" if soc is not None
                                              else entry.get("error", "no answer")))
            if soc is not None:
                break
            if attempt < wake_tries:
                pause(3.0)  # gateways and battery controllers need a moment to boot
        report["wake"].update(woke=soc is not None, soc=soc, profile=profile.name if profile else None,
                              seconds=report["wake"]["attempts"][-1]["seconds"])
        if soc is None:
            report["verdict"].append(f"No answer after {wake_tries} attempts: this car cannot be woken through the OBD socket with this adapter (or the profile does not fit).")
        elif not awake:
            report["verdict"].append(f"Waking works: answer after {report['wake']['seconds']:g} s (attempt {len(report['wake']['attempts'])}), state of charge {soc:.1f} %.")

        log(f"3. Watching for up to {watch_minutes:g} min whether the car falls asleep again (no requests) ...")
        asleep_since = None
        t_watch = now()
        while now() - t_watch < watch_minutes * 60:
            pause(step)
            try:
                is_awake, volt, how = car_awake(adapter, awake_voltage)
            except (AdapterError, TransportError, OSError) as e:
                is_awake, volt, how = False, None, f"no longer reachable ({e})"
            minutes = round((now() - t_watch) / 60, 1)
            report["timeline"].append({"min": minutes, "awake": is_awake, "voltage": volt})
            log(f"  {minutes:>5g} min: {'awake' if is_awake else 'asleep'}" + (f", {volt:.2f} V" if volt is not None else ""))
            if is_awake:
                asleep_since = None
            elif asleep_since is None:
                asleep_since = minutes
            else:
                break  # asleep on two checks in a row
        report["asleep_after_min"] = asleep_since
        if how == "gateway reachable":
            report["verdict"].append("Over ENET falling asleep cannot be measured passively: while the connection stands, the car counts as awake, and a permanently plugged ENET cable can keep it awake. Check the 12 V voltage overnight another way (multimeter, app).")
        elif asleep_since is not None:
            report["verdict"].append(f"The car was asleep again after about {asleep_since:g} min.")
        else:
            report["verdict"].append(f"After {watch_minutes:g} min the car was still awake. Is it charging, climatising or is the ignition on? Otherwise the adapter keeps it awake: then do not wake it regularly.")
    finally:
        try:
            adapter.close()
        except Exception:  # noqa: BLE001 - closing a dead link may fail any way
            pass
    return _finish(report, start, now)


def _finish(report: dict, start: float, now) -> dict:
    report["seconds"] = round(now() - start, 1)
    return report


def summary(report: dict) -> str:
    b, w = report["before"], report["wake"]
    out = ["Wake test " + report.get("time", "")]
    if b:
        volt = f", {b['voltage']:.2f} V" if b.get("voltage") is not None else ""
        out.append("Before: " + ("not reachable" if not b.get("reachable", True) else ("awake" if b.get("awake") else "asleep") + volt))
    for a in w.get("attempts", []):
        out.append(f"  Attempt {a['attempt']}: " + (f"state of charge {a['soc']:.1f} % after {a['seconds']:g} s" if a.get("soc") is not None
                                                    else a.get("error", "no answer")))
    if report["timeline"]:
        volts = [t["voltage"] for t in report["timeline"] if t["voltage"] is not None]
        out.append(f"Watched: {report['timeline'][-1]['min']:g} min"
                   + (f", 12 V between {min(volts):.2f} and {max(volts):.2f} V" if volts else ""))
    out += ["", *report["verdict"]]
    return "\n".join(out)


def default_path() -> str:
    return time.strftime("evsoc-waketest-%Y%m%d-%H%M%S.json")


def save(report: dict, path: str) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
