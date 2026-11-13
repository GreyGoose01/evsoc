"""Run profiles against an adapter: initialise, execute steps, decode values, auto-detect."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .connection import bus_for_step, capabilities_of, soc_problems
from .decoders import Response
from .elm import AdapterError, UdsResponse
from .equation import EquationError
from .profiles import Profile, Step, candidates
from .safety import SafetyError, decode_request
from .vehicles import year_from_vin

Log = Callable[[str], None]


class Adapter(Protocol):
    caf: bool
    version: str

    def reset(self) -> None: ...
    def reset_fast(self) -> None: ...
    def prepare(self, commands: list[str]) -> bool: ...
    def at(self, cmd: str) -> None: ...
    def request(self, cmd: str) -> UdsResponse: ...
    def listen(self, can_id: str, timeout: float = 2.0) -> bytes: ...
    def close(self) -> None: ...


@dataclass
class Value:
    name: str
    value: float | None
    plausible: bool = False
    error: str | None = None
    unit: str = ""
    label: str = ""


@dataclass
class Reading:
    profile: str
    values: dict[str, Value] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)  # step id -> "ECU: payload hex"

    SOC_ORDER = ("soc_display", "soc", "soc_bms")

    @property
    def soc(self) -> float | None:
        for name in self.SOC_ORDER:
            v = self.values.get(name)
            if v and v.plausible:
                return v.value
        for name, v in self.values.items():
            if name.startswith("soc") and v.plausible:
                return v.value
        return None


def is_at(cmd: str) -> bool:
    return cmd.replace(" ", "").upper().startswith(("AT", "ST"))


def run_init(adapter: Adapter, profile: Profile, log: Log = lambda _m: None) -> None:
    adapter.reset_fast()
    apply_init(adapter, profile, log)


def apply_init(adapter: Adapter, profile: Profile, log: Log = lambda _m: None) -> None:
    for cmd in profile.init:
        if is_at(cmd):
            adapter.at(cmd)
        else:
            try:
                adapter.request(cmd)
            except (AdapterError, SafetyError) as e:
                log(f"  Init command {cmd} got no answer ({e}), carrying on")


def ensure_state(adapter: Adapter, profile: Profile, step: Step, force_init: bool = False) -> None:
    """Make sure no setting from a previous profile or step leaks into this step,
    and put a universal adapter on the right bus (pins, bus type, listen-only)."""
    if adapter.prepare(profile.init + step.at) or force_init:
        apply_init(adapter, profile)
    if hasattr(adapter, "select_bus"):
        adapter.select_bus(bus_for_step(profile, step))


def execute_step(adapter: Adapter, step: Step) -> tuple[Response, str]:
    for cmd in step.at:
        adapter.at(cmd)
    if step.listen:
        frame = adapter.listen(step.listen)
        return Response(frame, frame), f"{step.listen}: {frame.hex(' ').upper()} (overheard)"
    for cmd in step.pre:
        try:
            adapter.request(cmd)
        except AdapterError:
            pass
    try:
        resp = adapter.request(step.request)
    finally:
        for cmd in step.post:
            try:
                adapter.request(cmd)
            except (AdapterError, SafetyError):
                pass
    req = decode_request(step.request, adapter.caf)
    return Response(resp.payload[len(req):], resp.raw), f"{resp.ecu}: {resp.payload.hex(' ').upper()}"


def missing_battery_kwh(profile: Profile) -> str:
    usual = ", ".join(f"{v:g}" for v in profile.battery_kwh)
    return "Nominal (net) capacity missing: give --battery-kwh" + (f", usual: {usual} kWh" if usual else "")


def decode(profile: Profile, names: list[str], results: dict[str, Response | str],
           battery_kwh: float | None = None) -> dict[str, Value]:
    values: dict[str, Value] = {}
    for name in names:
        f = profile.fields[name]
        res = results.get(f.step, "not requested")
        if isinstance(res, str):
            values[name] = Value(name, None, error=res, unit=f.unit, label=f.label)
            continue
        if f.percent_of == "battery_kwh" and not battery_kwh:
            values[name] = Value(name, None, error=missing_battery_kwh(profile), unit=f.unit, label=f.label)
            continue
        try:
            value = f.decoder(res)
        except EquationError as e:
            values[name] = Value(name, None, error=str(e), unit=f.unit, label=f.label)
            continue
        if value is None:
            values[name] = Value(name, None, error="no valid value", unit=f.unit, label=f.label)
            continue
        if f.percent_of == "battery_kwh":
            value = value * 100 / battery_kwh
        values[name] = Value(name, round(value, 3), f.in_range(value), unit=f.unit, label=f.label)
    return values


def read(adapter: Adapter, profile: Profile, names: list[str] | None = None, year: int | None = None,
         battery_kwh: float | None = None) -> Reading:
    """Run the needed steps of an initialised profile and decode the values.

    `battery_kwh` is the nominal (net) battery capacity for fields relative to it (SoH from energy content)."""
    names = [n for n in (names or profile.fields) if n in profile.fields]
    reading = Reading(profile.name)
    results: dict[str, Response | str] = {}
    for step_id in dict.fromkeys(profile.fields[n].step for n in names):
        step = profile.steps[step_id]
        if not step.applies(year):
            results[step_id] = f"does not apply to model year {year}"
            continue
        try:
            ensure_state(adapter, profile, step)
            results[step_id], reading.raw[step_id] = execute_step(adapter, step)
        except (AdapterError, SafetyError) as e:
            results[step_id] = str(e)
    reading.values = decode(profile, names, results, battery_kwh)
    return reading


def read_vin(adapter: Adapter) -> str | None:
    try:
        adapter.reset_fast()
        for cmd in ("ATSP0", "ATSH7DF"):
            adapter.at(cmd)
        payload = adapter.request("0902").payload
    except (AdapterError, SafetyError):
        try:  # UDS-only cars (OBDonUDS) answer DID F190 instead
            payload = adapter.request("22F190").payload
        except (AdapterError, SafetyError):
            return None
    vin = "".join(chr(b) for b in payload if 0x30 <= b <= 0x5A)
    return vin[-17:] if len(vin) >= 17 else None


def confirm_problem(profile: Profile, results: dict[str, Response | str]) -> str | None:
    """Why a look-alike control unit answered instead of this profile's (see `confirm` in profiles.py)."""
    for step_id, want in profile.confirm:
        res = results.get(step_id)
        if isinstance(res, Response) and len(res.data) != want:
            return f"{profile.steps[step_id].request}: {len(res.data)} instead of {want} data bytes"
    return None


def hit_rank(profile: Profile, plausible: int, index: int) -> tuple:
    """Order of profiles with a plausible SoC: model-specific beats make-wide, then more agreeing
    SoC values, then known EV platform, then candidate order."""
    specific = not any(v.model in ("all models", "alle Modelle", "") or v.make in ("all", "alle") for v in profile.vehicles)
    return (not specific, -plausible, profile.platform is None, index)


@dataclass
class Detection:
    profile: Profile
    reading: Reading
    vin: str | None
    year: int | None
    also_plausible: list[str]
    tried: int
    seconds: float


def autodetect(
    adapter: Adapter,
    profiles: dict[str, Profile],
    vin: str | None = None,
    car: str | None = None,
    year: int | None = None,
    log: Log = print,
    read_vin_first: bool = True,
) -> Detection | None:
    """Try candidate profiles; identical requests are only sent once.

    Returns the first profile (in candidate order) whose SoC decodes to a
    plausible value, plus the names of other profiles that agree.
    """
    start = time.monotonic()
    if vin is None and car is None and read_vin_first:
        log("Reading the vehicle identification number (VIN) ...")
        vin = read_vin(adapter)
        log(f"  VIN: {vin}" if vin else "  no VIN (normal for many EVs)")
    year = year or year_from_vin(vin)
    caps = capabilities_of(adapter)
    cands, skipped = [], []
    for p in candidates(profiles, vin, car):
        (skipped if soc_problems(p, caps, year) and not (p.generic and caps.bmw_enet) else cands).append(p)
    if skipped and car:
        log(f"  {len(skipped)} profiles do not fit the adapter ({caps.name}), e.g. {skipped[0].name}: {soc_problems(skipped[0], caps, year)[0]}")
    log(f"Trying {len(cands)} profiles" + (f" (model year {year})" if year else "") + " ...")

    cache: dict[tuple, Response | str] = {}
    hits: list[tuple[tuple, Profile, dict[str, Value]]] = []
    for index, profile in enumerate(cands):
        socs = [f for f in profile.soc_fields if profile.steps[f.step].applies(year)]
        if not socs:
            continue
        results: dict[str, Response | str] = {}
        for f in socs:
            step = profile.steps[f.step]
            key = (tuple(profile.init), step.signature, bus_for_step(profile, step))
            if key not in cache:
                if hits:
                    continue  # after a hit, only compare against answers we already have
                try:
                    ensure_state(adapter, profile, step, force_init=True)
                    cache[key], _raw = execute_step(adapter, step)
                except (AdapterError, SafetyError) as e:
                    cache[key] = str(e)
            results[f.step] = cache[key]
        values = decode(profile, [f.name for f in socs], results)
        plausible = sum(v.plausible for v in values.values())
        if not plausible:
            continue
        confirm: dict[str, Response | str] = {}
        for step_id, _n in profile.confirm:  # rare: only look-alike control units, only after a plausible SoC
            step = profile.steps[step_id]
            key = (tuple(profile.init), step.signature, bus_for_step(profile, step))
            if key not in cache:
                try:
                    ensure_state(adapter, profile, step, force_init=True)
                    cache[key], _raw = execute_step(adapter, step)
                except (AdapterError, SafetyError) as e:
                    cache[key] = str(e)
            confirm[step_id] = cache[key]
        why = confirm_problem(profile, confirm)
        if why:
            log(f"  {profile.name}: state of charge plausible, but a different control unit ({why})")
            continue
        if not hits:
            ok = ", ".join(f"{v.name}={v.value}" for v in values.values() if v.plausible)
            log(f"  Match: {profile.name}  ({ok})")
        hits.append((hit_rank(profile, plausible, index), profile, values))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])
    _score, found, values = hits[0]
    agree = [p.name for _s, p, _v in hits[1:]]
    return Detection(found, Reading(found.name, values), vin, year, agree, len(cands), time.monotonic() - start)
