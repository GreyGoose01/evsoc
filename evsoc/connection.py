"""Which physical connection ("OBD type") a profile needs, and which adapter can provide it.

Pick the car, and evsoc derives the bus for every step: CAN (11/29 bit,
bitrate), CAN-FD, K-Line, Single-Wire-CAN or Automotive Ethernet (DoIP), on
which OBD pins, passive or not. A universal adapter is switched accordingly;
for every other adapter evsoc checks up front whether it can do the job.

Sources of truth, in order: step "bus" in the profile JSON, profile
"connection", and finally the ELM protocol commands of the step (ATSP/ATPB).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from .elm import at_family

# J1962 pins of the common buses.
PINS = {
    "can": (6, 14),          # ISO 15765-4 high-speed CAN, every car since ~2008
    "kline": (7, 15),        # ISO 9141 / KWP2000 K- and L-line
    "j1850": (2, 10),
    "swcan": (1,),           # GM single-wire CAN
    "mscan": (3, 11),        # Ford medium-speed CAN
    "doip1": (3, 11, 12, 13),  # ISO 13400-4 option 1, activation pin 8
    "doip2": (1, 9, 12, 13),   # ISO 13400-4 option 2, activation pin 8
}

_SP = {  # ELM protocol number -> (kind, id bits, bitrate)
    "1": ("j1850", None, 41_600), "2": ("j1850", None, 10_400),
    "3": ("kline", None, 10_400), "4": ("kline", None, 10_400), "5": ("kline", None, 10_400),
    "6": ("can", 11, 500_000), "7": ("can", 29, 500_000),
    "8": ("can", 11, 250_000), "9": ("can", 29, 250_000), "A": ("can", 29, 250_000),
}
_PB_RATES = {0x01: 500_000, 0x02: 250_000, 0x04: 125_000}


@dataclass(frozen=True)
class Bus:
    kind: str                        # can | canfd | kline | j1850 | swcan | doip
    pins: tuple[int, ...]
    bitrate: int | None = None
    id_bits: int | None = None       # 11 / 29, None = automatic
    data_bitrate: int | None = None  # CAN-FD data phase
    listen_only: bool = False
    cable: str | None = None         # special cable needed, e.g. Tesla

    def describe(self) -> str:
        name = {"can": "CAN", "canfd": "CAN-FD", "kline": "K-Line", "j1850": "J1850",
                "swcan": "Single-Wire-CAN", "doip": "Ethernet (DoIP)"}[self.kind]
        parts = [name]
        if self.bitrate:
            rate = f"{self.bitrate // 1_000_000} Mbit/s" if self.bitrate >= 1_000_000 else f"{self.bitrate // 1000} kbit/s"
            parts.append(rate + (f" / {self.data_bitrate // 1_000_000} Mbit/s" if self.data_bitrate else ""))
        elif self.kind == "can":
            parts.append("automatic")
        if self.id_bits:
            parts.append(f"{self.id_bits} bit")
        parts.append("pins " + "/".join(map(str, self.pins)) + (" + 8" if self.kind == "doip" else ""))
        if self.listen_only:
            parts.append("listen only")
        if self.cable:
            parts.append(f"cable: {self.cable}")
        return ", ".join(parts)


def _from_commands(commands: Iterable[str]) -> Bus:
    kind, bits, rate = "can", None, None
    pb: tuple[int, int] | None = None
    for cmd in commands:
        norm = cmd.replace(" ", "").upper()
        fam = at_family(norm)
        if fam == "PB" and len(norm) >= 8:
            flags, div = int(norm[4:6], 16), int(norm[6:8], 16)
            pb = (11 if flags & 0x80 else 29, _PB_RATES.get(div, 500_000 // max(div, 1)))
        elif fam == "SP":
            arg = norm[4:].lstrip("A") or "0"
            if arg in _SP:
                kind, bits, rate = _SP[arg]
            elif arg in ("B", "C") and pb:
                kind, (bits, rate) = "can", pb
            elif arg == "0":
                kind, bits, rate = "can", None, None
    return Bus(kind, PINS.get(kind, PINS["can"]), rate, bits)


def _apply(bus: Bus, spec: dict | None) -> Bus:
    if not spec:
        return bus
    kind = spec.get("kind", bus.kind)
    if spec.get("fd"):
        kind = "canfd"
    pins = tuple(spec["pins"]) if "pins" in spec else (PINS.get(kind, bus.pins) if kind != bus.kind else bus.pins)
    return replace(
        bus, kind=kind, pins=pins,
        bitrate=spec.get("bitrate", bus.bitrate), id_bits=spec.get("id_bits", bus.id_bits),
        data_bitrate=spec.get("data_bitrate", bus.data_bitrate if kind == "canfd" else None),
        cable=spec.get("cable", bus.cable),
    )


def bus_for_step(profile, step) -> Bus:
    bus = _from_commands(list(profile.init) + list(step.at))
    bus = _apply(bus, profile.connection)
    bus = _apply(bus, step.bus)
    if step.listen:
        bus = replace(bus, listen_only=True)
    return bus


def buses(profile) -> list[Bus]:
    return list(dict.fromkeys(bus_for_step(profile, s) for s in profile.steps.values()))


def alternatives(profile) -> list[Bus]:
    """Other ways to reach the same control units (BMW/Mini: ENET instead of CAN)."""
    if profile.reachable_via_enet:
        return [Bus("doip", PINS["doip1"], 100_000_000)]
    return []


# -- adapter capabilities -------------------------------------------------------------

@dataclass
class Capabilities:
    name: str
    kinds: set[str]
    pins: set[tuple[int, ...]] | None   # None = switchable to any pins
    listen: bool = True
    ext_addr: bool = True                # ATCEA (BMW addressing)
    bmw_enet: bool = False
    notes: list[str] = field(default_factory=list)

    def supports(self, bus: Bus) -> str | None:
        """None if the adapter can do it, else the reason why not."""
        if bus.kind not in self.kinds:
            return f"{self.name} cannot do {bus.describe().split(',')[0]}"
        if self.pins is not None and bus.pins not in self.pins:
            return f"{self.name} does not reach pins {'/'.join(map(str, bus.pins))} (only {', '.join('/'.join(map(str, p)) for p in sorted(self.pins))})"
        if bus.listen_only and not self.listen:
            return f"{self.name} cannot listen passively"
        return None


CATALOG: list[Capabilities] = [
    Capabilities("ELM327 clone", {"can", "kline"}, {PINS["can"], PINS["kline"]}, ext_addr=False,
                 notes=["often incomplete AT commands, no ATCEA"]),
    Capabilities("OBDLink MX+/SX/EX", {"can", "kline", "j1850"}, {PINS["can"], PINS["kline"], PINS["j1850"]},
                 notes=["per the maker also Ford MS-CAN and GM SW-CAN; evsoc does not switch to them yet"]),
    Capabilities("OBDLink CX (BLE)", {"can"}, {PINS["can"]}),
    Capabilities("BMW ENET cable", {"doip"}, {PINS["doip1"]}, listen=False, bmw_enet=True,
                 notes=["BMW/Mini only (HSFZ)"]),
    Capabilities("CAN interface (python-can) + OBD cable", {"can"}, {PINS["can"]},
                 notes=["other pins with a suitably wired cable (?pins=12,13)"]),
    Capabilities("CAN FD interface (python-can) + OBD cable", {"can", "canfd"}, {PINS["can"]}),
    Capabilities("evsoc box (universal adapter)", {"can", "canfd", "kline", "swcan", "doip"}, None,
                 notes=["switches pins and protocol per vehicle by itself"]),
]


def capabilities_of(adapter) -> Capabilities:
    caps = getattr(adapter, "capabilities", None)
    if caps is not None:
        return caps
    version = getattr(adapter, "version", "")
    if version.startswith("ENET"):
        return CATALOG[3]
    if "STN" in version.upper() or "OBDLINK" in version.upper():
        return CATALOG[1]
    return Capabilities("ELM327 adapter", {"can", "kline"}, {PINS["can"], PINS["kline"]})


def check(profile, caps: Capabilities, year: int | None = None) -> list[str]:
    """Problems that keep this adapter from running the profile ([] = fine)."""
    if caps.bmw_enet:
        return [] if profile.reachable_via_enet else [f"{caps.name} only reaches BMW/Mini control units"]
    problems = []
    for step in profile.steps.values():
        if not step.applies(year):
            continue
        why = caps.supports(bus_for_step(profile, step))
        if why and why not in problems:
            problems.append(why)
    if profile.is_bmw_addressing and not caps.ext_addr:
        problems.append(f"{caps.name} usually cannot do extended CAN addressing (ATCEA)")
    return problems


def soc_problems(profile, caps: Capabilities, year: int | None = None) -> list[str]:
    """Like check(), but only for the steps that deliver a state of charge."""
    steps = {f.step for f in profile.soc_fields}
    sub = replace(profile, steps={k: v for k, v in profile.steps.items() if k in steps})
    return check(sub, caps, year)


def recommend(profile) -> list[tuple[Capabilities, list[str]]]:
    return [(caps, check(profile, caps)) for caps in CATALOG]
