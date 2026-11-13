"""Vehicle profiles (evsoc format v2) and the index that finds the right one.

A profile is a JSON file:

    {
      "name": "...", "description": "...", "source": "...", "license": "...",
      "platform": "...", "verified": "...",
      "vehicles": [{"make": "Peugeot", "model": "e-208", "years": [2019, null]}],
      "init": ["ATSP6"],
      "steps": [{"id": "bmu_soc", "at": ["ATSH6B4", "ATCRA694"], "request": "22D410",
                 "years": [2020, null], "pre": [], "post": []}],
      "fields": {"soc": {"step": "bmu_soc", "decode": {"type": "equation", "expr": "INT16(A,B)/512"},
                         "min": 0, "max": 100, "unit": "%"}}
    }

Every step carries the complete adapter state it needs (on top of `init`), so
steps can run in any order and profiles from different sources can be mixed.
A step may `listen` for a broadcast CAN id instead of sending a `request`.
Optional `connection` (profile) and `bus` (step) describe the physical bus
when it is not plain CAN on pins 6/14, e.g. {"pins": [12, 13]} or
{"fd": true, "data_bitrate": 2000000} or {"cable": "Tesla-Diagnosekabel"}.

A field with `"percent_of": "battery_kwh"` decodes to kWh and is shown in
percent of the battery's nominal capacity, which the user supplies (it is not
readable from the car), e.g. SoH = max. energy content / nominal capacity.
The profile's `battery_kwh` list names the usual nominal capacities.

Optional `"confirm": [{"step": "soh", "bytes": 3}]` tells look-alike control units apart during
auto-detection: the answer to that step must carry exactly that many data bytes. A profile is
only rejected by a positive answer of another length, never by a missing answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .decoders import Decoder, make_decoder
from .equation import EquationError
from .vehicles import canonical_make, make_from_vin, norm, platform_for, related_makes

PKG = Path(__file__).parent
PROFILE_DIRS = [PKG / "profiles"]


# Vehicle settings a field may be relative to (see `percent_of`).
SETTINGS = {"battery_kwh"}


class ProfileError(ValueError):
    pass


@dataclass
class Step:
    id: str
    at: list[str]
    request: str | None = None
    listen: str | None = None
    years: tuple[int | None, int | None] | None = None
    pre: list[str] = field(default_factory=list)   # e.g. a session change before the request
    post: list[str] = field(default_factory=list)
    bus: dict | None = None                         # physical bus override, see connection.py

    def applies(self, year: int | None) -> bool:
        if year is None or self.years is None:
            return True
        lo, hi = self.years
        return (lo is None or year >= lo) and (hi is None or year <= hi)

    @property
    def signature(self) -> tuple:
        return (tuple(self.at), tuple(self.pre), self.request, self.listen, repr(self.bus))


@dataclass
class Field:
    name: str
    step: str
    decoder: Decoder
    min: float | None = None
    max: float | None = None
    unit: str = ""
    label: str = ""
    percent_of: str | None = None   # vehicle setting the decoded value is divided by, see SETTINGS

    def in_range(self, value: float) -> bool:
        return (self.min is None or value >= self.min) and (self.max is None or value <= self.max)


@dataclass
class Vehicle:
    make: str
    model: str
    years: tuple[int | None, int | None] | None = None

    def __str__(self) -> str:
        if not self.years:
            return f"{self.make} {self.model}".strip()
        lo, hi = self.years
        return f"{self.make} {self.model} ({lo or '?'}-{hi or ''})".strip()


@dataclass
class Profile:
    name: str
    description: str
    init: list[str]
    steps: dict[str, Step]
    fields: dict[str, Field]
    vehicles: list[Vehicle] = field(default_factory=list)
    platform: str | None = None
    source: str = ""
    license: str = ""
    verified: str = ""
    generic: bool = False
    connection: dict | None = None   # profile-wide bus override, see connection.py
    battery_kwh: list[float] = field(default_factory=list)  # usual nominal capacities, for help texts
    confirm: list[tuple[str, int]] = field(default_factory=list)  # (step id, data bytes), see module docstring
    path: Path | None = None

    @property
    def makes(self) -> set[str]:
        return {v.make for v in self.vehicles}

    @property
    def soc_fields(self) -> list[Field]:
        return [f for n, f in self.fields.items() if n == "soc" or n.startswith("soc_")]

    @property
    def is_bmw_addressing(self) -> bool:
        """Uses CAN extended addressing (ATCEA with a target, e.g. ATCEA07); a bare ATCEA only switches it off."""
        cmds = list(self.init) + [a for s in self.steps.values() for a in s.at]
        return any(len(c.replace(" ", "")) > 5 and c.replace(" ", "").upper().startswith("ATCEA") for c in cmds)

    @property
    def reachable_via_enet(self) -> bool:
        """BMW-group control units can also be reached over the ENET cable (HSFZ)."""
        return self.is_bmw_addressing and bool(self.makes & {"BMW", "Mini", "Rolls-Royce"})

    @property
    def needs_listen(self) -> bool:
        return any(s.listen for s in self.steps.values())

    def matches_text(self, query: str) -> bool:
        q = norm(query)
        hay = [norm(str(v)) for v in self.vehicles] + [norm(self.name), norm(self.platform or "")]
        return any(q in h for h in hay)


def _years(v) -> tuple[int | None, int | None] | None:
    if not v:
        return None
    lo, hi = (list(v) + [None, None])[:2]
    return (int(lo) if lo else None, int(hi) if hi else None)


def parse_profile(d: dict, path: Path | None = None) -> Profile:
    name = d["name"]
    steps: dict[str, Step] = {}
    for s in d.get("steps", []):
        if not (s.get("request") or s.get("listen")):
            raise ProfileError(f"{name}: step {s.get('id')} has neither request nor listen")
        steps[s["id"]] = Step(
            s["id"], [str(a) for a in s.get("at", [])], s.get("request"), s.get("listen"),
            _years(s.get("years")), list(s.get("pre", [])), list(s.get("post", [])), s.get("bus"),
        )
    fields: dict[str, Field] = {}
    for fname, f in d.get("fields", {}).items():
        if f["step"] not in steps:
            raise ProfileError(f"{name}.{fname}: unknown step {f['step']}")
        try:
            dec = make_decoder(f["decode"])
        except (EquationError, KeyError, ValueError) as e:
            raise ProfileError(f"{name}.{fname}: {e}") from e
        percent_of = f.get("percent_of")
        if percent_of is not None and percent_of not in SETTINGS:
            raise ProfileError(f"{name}.{fname}: percent_of {percent_of!r} unknown")
        fields[fname] = Field(fname, f["step"], dec, f.get("min"), f.get("max"), f.get("unit", ""), f.get("label", ""),
                              percent_of)
    confirm = [(c["step"], int(c["bytes"])) for c in d.get("confirm", [])]
    for step_id, _n in confirm:
        if step_id not in steps:
            raise ProfileError(f"{name}: confirm names unknown step {step_id}")
    if not any(n == "soc" or n.startswith("soc_") for n in fields):
        raise ProfileError(f"{name}: no state of charge field")
    vehicles = [Vehicle(canonical_make(v.get("make", "")), v.get("model", ""), _years(v.get("years"))) for v in d.get("vehicles", [])]
    platform = d.get("platform") or next((p for p in (platform_for(f"{v.make} {v.model}") for v in vehicles) if p), None)
    return Profile(
        name=name,
        description=d.get("description", ""),
        init=[str(c) for c in d.get("init", [])],
        steps=steps,
        fields=fields,
        vehicles=vehicles,
        platform=platform,
        source=d.get("source", ""),
        license=d.get("license", ""),
        verified=d.get("verified", ""),
        generic=bool(d.get("generic", False)),
        connection=d.get("connection"),
        battery_kwh=[float(v) for v in d.get("battery_kwh", [])],
        confirm=confirm,
        path=path,
    )


@lru_cache(maxsize=1)
def load_all() -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}
    for base in PROFILE_DIRS:
        for path in sorted(base.rglob("*.json")):
            d = json.loads(path.read_text(encoding="utf-8"))
            p = parse_profile(d, path)
            if p.name in profiles:
                raise ProfileError(f"Duplicate profile name: {p.name} ({path})")
            profiles[p.name] = p
    return profiles


# Sources ranked by how trustworthy their SoC formulas are in practice.
_SOURCE_RANK = {"evsoc": 0, "obdb": 1, "abrp": 2, "wican": 3}


def _rank(p: Profile) -> int:
    return _SOURCE_RANK.get(p.name.split("_", 1)[0], 4)


def candidates(
    profiles: dict[str, Profile],
    vin: str | None = None,
    car: str | None = None,
) -> list[Profile]:
    """Profiles worth trying, most likely first.

    Generic profiles come last; listen-only profiles (slow, need a special
    cable) are only tried when they match the car/make or nothing is known."""
    specific = [p for p in profiles.values() if not p.generic and not p.needs_listen]
    generic = [p for p in profiles.values() if p.generic]
    listen = [p for p in profiles.values() if p.needs_listen]
    if car:
        hits = [p for p in specific if p.matches_text(car)]
        platforms = {p.platform for p in hits if p.platform}
        siblings = [p for p in specific if p.platform in platforms and p not in hits]
        return sorted(hits, key=_rank) + sorted(siblings, key=_rank) + generic + [p for p in listen if p.matches_text(car)]
    make = make_from_vin(vin)
    if make:
        own = [p for p in specific if make in p.makes]
        related = related_makes(make)
        platforms = {p.platform for p in own if p.platform}
        group = [p for p in specific if p not in own and (p.makes & related or p.platform in platforms)]
        own_listen = [p for p in listen if make in p.makes]
        if own or group:
            return sorted(own, key=_rank) + sorted(group, key=_rank) + generic + own_listen
        return own_listen + generic + sorted(specific, key=_rank)  # known make without EV profile: likely a hybrid
    return sorted(specific, key=_rank) + generic + listen
