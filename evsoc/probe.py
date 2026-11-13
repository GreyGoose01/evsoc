"""Test drive at the car: try every candidate profile completely and keep all raw answers.

`read` stops at the first profile with a plausible state of charge. `probe` does not judge: it
asks everything the candidate profiles know (identical requests only once), stores each raw answer
and what every profile makes of it, and writes one JSON report. What is right or wrong is decided
afterwards, with the values noted from the instrument cluster (`--notiz soc=54`) as reference.

The report holds the raw answers, so `probe -d report.json` decodes it again with the current
profiles. A corrected formula can be checked without going back to the car.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__, diag
from .connection import bus_for_step, capabilities_of, check
from .decoders import Response
from .elm import AdapterError
from .i18n import tr
from .profiles import Profile, Step, candidates
from .reader import (
    Value,
    confirm_problem,
    decode,
    ensure_state,
    execute_step,
    hit_rank,
    read_vin,
)
from .safety import SafetyError
from .vehicles import year_from_vin

Log = Callable[[str], None]
FORMAT = 1
NOTE_TOLERANCE = {"soc": 3.0, "soh": 3.0}  # how far a value may be from the noted one to count as a match
DEFAULT_TOLERANCE = 0.05                   # relative, for everything else (voltage, km ...)


def request_key(profile: Profile, step: Step) -> str:
    """Identifies one question to the car: same bus, same adapter settings, same request."""
    return json.dumps([profile.init, step.at, step.pre, step.request, step.listen, repr(bus_for_step(profile, step))])


def _response(entry: dict) -> Response | str:
    if entry.get("error"):
        return entry["error"]
    return Response(bytes.fromhex(entry["data"]), bytes.fromhex(entry["raw"]))


def parse_notes(items: list[str] | None) -> dict[str, float]:
    """['soc=54', 'soh=93,5'] -> {'soc': 54.0, 'soh': 93.5}"""
    notes = {}
    for item in items or []:
        name, sep, value = item.partition("=")
        try:
            notes[name.strip().lower()] = float(value.replace(",", "."))
        except ValueError:
            sep = ""
        if not sep or not name.strip():
            raise ValueError(f"Note {item!r}: form name=number, e.g. soc=54")
    return notes


def run(adapter, profiles: dict[str, Profile], *, adapter_url: str = "", vin: str | None = None, car: str | None = None,
        year: int | None = None, everything: bool = False, raw_commands: list[str] | None = None,
        notes: dict[str, float] | None = None, battery_kwh: float | None = None, diagnose: bool = True,
        log: Log = print) -> dict:
    """Ask the car everything the candidate profiles know; returns the report."""
    start = time.monotonic()
    if vin is None:
        log("Reading the vehicle identification number (VIN) ...")
        vin = read_vin(adapter)
        log(f"  VIN: {vin}" if vin else "  no VIN (normal for many EVs)")
    year = year or year_from_vin(vin)
    caps = capabilities_of(adapter)
    voltage = None
    try:
        voltage = adapter.voltage() if hasattr(adapter, "voltage") else None
    except AdapterError:
        pass
    cands = list(profiles.values()) if everything else candidates(profiles, vin, car)
    log(f"Testing {len(cands)} profiles completely" + (f" (model year {year})" if year else "") + " ...")

    requests: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    units: dict[str, diag.Unit] = {}  # control units that answered, for the fault memory
    for n, profile in enumerate(cands, 1):
        problems = check(profile, caps, year)
        if problems and not (profile.generic and caps.bmw_enet):
            skipped[profile.name] = problems[0]
            continue
        new = answered = 0
        for step in profile.steps.values():
            if not step.applies(year):
                continue
            key = request_key(profile, step)
            if key in requests:
                continue
            entry = {"init": profile.init, "at": step.at, "pre": step.pre, "request": step.request, "listen": step.listen,
                     "first_profile": profile.name}
            t0 = time.monotonic()
            try:
                ensure_state(adapter, profile, step, force_init=True)
                resp, shown = execute_step(adapter, step)
                entry.update(data=resp.data.hex().upper(), raw=resp.raw.hex().upper(), answer=shown)
                answered += 1
                unit = diag.unit_for(adapter, profile, step)
                if unit and unit.label not in units and step.request[:2] in ("22", "01"):
                    units[unit.label] = unit
            except (AdapterError, SafetyError) as e:
                entry["error"] = str(e)
            entry["ms"] = round((time.monotonic() - t0) * 1000)
            requests[key] = entry
            new += 1
        if new:
            log(f"  [{n}/{len(cands)}] {profile.name}: {new} new requests, {answered} answers")

    found_units: list[dict] = []
    if diagnose:
        if caps.bmw_enet:  # over ENET every control unit is reachable by its address
            for address in range(0x100) if everything else diag.BMW_UNITS:
                units.setdefault(f"6F1/{address:02X}", diag.enet_unit(adapter, address))
        if units:
            log(f"Reading identification and fault memory of {len(units)} control units (read only) ...")
            found_units = diag.scan(list(units.values()), log)

    raw = []
    for cmd in raw_commands or []:
        item = {"cmd": cmd}
        try:
            if cmd.upper().startswith(("AT", "ST")):
                adapter.at(cmd)
            else:
                r = adapter.request(cmd)
                item.update(ecu=r.ecu, payload=r.payload.hex().upper())
        except (AdapterError, SafetyError) as e:
            item["error"] = str(e)
        raw.append(item)
    if raw:
        log(f"  {sum('payload' in r for r in raw)} answers to {sum(not r['cmd'].upper().startswith(('AT', 'ST')) for r in raw)} additional read commands")

    report = {
        "format": FORMAT,
        "evsoc": __version__,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.monotonic() - start, 1),
        "adapter": {"url": adapter_url, "name": caps.name, "version": getattr(adapter, "version", ""), "voltage": voltage},
        "vin": vin, "year": year, "car": car, "battery_kwh": battery_kwh,
        "notes": notes or {},
        "candidates": [p.name for p in cands],
        "skipped": skipped,
        "requests": requests,
        "units": found_units,
        "raw": raw,
    }
    report["profiles"] = evaluate(report, profiles)
    report["autodetect"] = pick(report, profiles)
    return report


def evaluate(report: dict, profiles: dict[str, Profile]) -> dict[str, dict]:
    """What every profile makes of the stored answers (also used to re-decode an old report)."""
    requests, year = report["requests"], report.get("year")
    names = [n for n in report.get("candidates") or profiles if n in profiles]
    names += [n for n in profiles if n not in names]  # profiles added since the report was written
    out: dict[str, dict] = {}
    for index, name in enumerate(names):
        profile = profiles[name]
        results: dict[str, Response | str] = {}
        for step in profile.steps.values():
            entry = requests.get(request_key(profile, step))
            if entry is not None and step.applies(year):
                results[step.id] = _response(entry)
        if not any(isinstance(r, Response) for r in results.values()):
            continue  # the car answered nothing this profile asks
        fields = [n for n, f in profile.fields.items() if f.step in results]
        values = decode(profile, fields, results, report.get("battery_kwh"))
        out[name] = {
            "index": index,
            "values": {n: _value_dict(v) for n, v in values.items()},
            "soc_plausible": sum(v.plausible for n, v in values.items() if n == "soc" or n.startswith("soc_")),
            "other_unit": confirm_problem(profile, results),
            "verified": profile.verified,
        }
    return out


def _value_dict(v: Value) -> dict:
    d = {"value": v.value, "plausible": v.plausible, "unit": v.unit}
    if v.error:
        d["error"] = v.error
    return d


def pick(report: dict, profiles: dict[str, Profile]) -> str | None:
    """The profile `evsoc read` would choose from these answers."""
    hits = [(hit_rank(profiles[name], p["soc_plausible"], p["index"]), name)
            for name, p in report["profiles"].items() if p["soc_plausible"] and not p["other_unit"]]
    return min(hits)[1] if hits else None


def note_for(field: str, notes: dict[str, float]) -> tuple[str, float] | None:
    """The noted value a field is compared with: exact name first, else its family (soc_bms -> soc)."""
    if field in notes:
        return field, notes[field]
    family = field.split("_", 1)[0]
    return (family, notes[family]) if family in notes and family in NOTE_TOLERANCE else None


def matches_note(field: str, value: float, notes: dict[str, float]) -> bool | None:
    ref = note_for(field, notes)
    if ref is None:
        return None
    name, wanted = ref
    tol = NOTE_TOLERANCE.get(name.split("_", 1)[0], abs(wanted) * DEFAULT_TOLERANCE)
    return abs(value - wanted) <= tol


def summary(report: dict) -> str:
    notes = report.get("notes") or {}
    reqs = report["requests"].values()
    answered = sum("error" not in r for r in reqs)
    car = report.get("vin") or report.get("car") or "unknown"
    out = [f"Vehicle: {car}" + (f", model year {report['year']}" if report.get("year") else "")
           + f"   Adapter: {report['adapter']['name']}"
           + (f", {report['adapter']['voltage']:.1f} V" if report['adapter'].get('voltage') else ""),
           f"{len(report['requests'])} requests, {answered} answers, {report.get('seconds', 0):g} s"]
    if notes:
        out.append("Noted: " + ", ".join(f"{k}={v:g}" for k, v in notes.items()))
    profiles = report["profiles"]
    if not profiles:
        out.append("\nNo profile got an answer. Ignition on? Right adapter? Test all profiles with --all-profiles.")
    quiet: list[str] = []
    order = sorted(profiles, key=lambda n: (not profiles[n]["soc_plausible"], bool(profiles[n]["other_unit"]), profiles[n]["index"]))
    for name in order:
        p = profiles[name]
        values = p["values"]
        good = [n for n, v in values.items() if v["plausible"]]
        flags = []
        if name == report.get("autodetect"):
            flags.append("<- 'evsoc read' would choose this")
        if p["other_unit"]:
            flags.append(f"different control unit ({p['other_unit']})")
        if not good:
            quiet.append(name)
            continue
        out.append(f"\n{name}   {len(good)}/{len(values)} values plausible   {'   '.join(flags)}")
        for n, v in values.items():
            if v["value"] is None:
                out.append(f"    {n:<22} -            ({v.get('error', 'no value')})")
                continue
            mark = "" if v["plausible"] else "   " + tr("implausible")
            hit = matches_note(n, v["value"], notes)
            if hit is not None:
                ref = note_for(n, notes)
                mark += "   " + tr(f"{'matches' if hit else 'DIFFERS from'} {ref[0]}={ref[1]:g}")
            out.append(f"    {n:<22} {v['value']:>10g} {v['unit']}{mark}")
    if quiet:
        out.append(f"\nAnswer, but no plausible value ({len(quiet)}): {', '.join(quiet)}")
    units = report.get("units") or []
    if units:
        out.append(f"\nControl units ({len(units)}):")
        for u in units:
            ident = ", ".join(f"{tr(k)} {v}" for k, v in u["ident"].items() if k != "Vehicle identification number")
            out.append(f"  {u['unit']:<8} {u.get('name', '')}  {ident}".rstrip())
            if u.get("dtc_error"):
                out.append(f"      Fault memory not readable: {u['dtc_error']}")
            elif not u["dtcs"]:
                out.append("      no fault entries")
            for d in u["dtcs"]:
                out.append(f"      {d['code']:<10} ({d['hex']})  {tr(d['text'])}")
    if report.get("skipped"):
        first = next(iter(report["skipped"].items()))
        out.append(f"\n{len(report['skipped'])} profiles do not fit the adapter and were skipped, e.g. {first[0]}: {first[1]}")
    hits = [r for r in report.get("raw", []) if "payload" in r]
    if hits:
        out.append(f"\nAdditional read commands: {len(hits)} answers (in the report)")
    return "\n".join(out)


def view(report: dict, label_for: Callable[[str], str] = lambda n: n) -> dict:
    """The report without the raw answers, with labels and the comparison to the noted values (for the GUI)."""
    notes = report.get("notes") or {}
    profiles = report["profiles"]
    order = sorted(profiles, key=lambda n: (not profiles[n]["soc_plausible"], bool(profiles[n]["other_unit"]), profiles[n]["index"]))
    shown, quiet = [], []
    for name in order:
        p = profiles[name]
        rows = []
        for n, v in p["values"].items():
            ref = note_for(n, notes) if v["value"] is not None else None
            rows.append({"name": n, "label": label_for(n), "value": v["value"], "unit": v["unit"], "plausible": v["plausible"],
                         "error": v.get("error"), "note": None if ref is None else {"name": ref[0], "value": ref[1],
                                                                                    "match": matches_note(n, v["value"], notes)}})
        good = sum(r["plausible"] for r in rows)
        if not good:
            quiet.append(name)
            continue
        shown.append({"name": name, "chosen": name == report.get("autodetect"), "other_unit": p["other_unit"],
                      "verified": p.get("verified", ""), "plausible": good, "total": len(rows), "values": rows})
    reqs = report["requests"].values()
    return {
        "vin": report.get("vin"), "year": report.get("year"), "car": report.get("car"), "time": report.get("time"),
        "seconds": report.get("seconds"), "adapter": report.get("adapter"), "notes": notes,
        "requests": len(report["requests"]), "answers": sum("error" not in r for r in reqs),
        "autodetect": report.get("autodetect"), "profiles": shown, "quiet": quiet,
        "skipped": report.get("skipped") or {}, "units": report.get("units") or [],
        "raw": [r for r in report.get("raw", []) if "payload" in r], "file": report.get("file"),
    }


def default_path(report: dict) -> str:
    tag = (report.get("vin") or report.get("car") or "auto").replace(" ", "_").replace("/", "_")
    return f"evsoc-probe-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.json"


def save(report: dict, path: str) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load(path: str, profiles: dict[str, Profile], notes: dict[str, float] | None = None,
         battery_kwh: float | None = None) -> dict:
    """Read a report and decode its raw answers with the profiles of this evsoc version."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("format") != FORMAT or "requests" not in report:
        raise ValueError(f"{path} is not a report of 'evsoc probe' (format {FORMAT})")
    report["notes"] = {**(report.get("notes") or {}), **(notes or {})}
    if battery_kwh:
        report["battery_kwh"] = battery_kwh
    report["profiles"] = evaluate(report, profiles)
    report["autodetect"] = pick(report, profiles)
    return report
