"""Control units and their fault memory, read-only.

For every control unit that answered during a test drive (`evsoc probe`): identification
(part number, software, serial number ...) and the stored fault codes. Nothing is cleared:
the read-only guard in safety.py does not let service 0x14 (clear) or OBD mode 04 through.

UDS: 19 02 FF (reportDTCByStatusMask), answer 59 02 <mask> then 3 code bytes + 1 status byte each.
OBD: modes 03 (stored), 07 (pending) and 0A (permanent), answer 4x <count> then 2 bytes per code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .elm import AdapterError, NegativeResponse
from .profiles import Profile, Step
from .reader import ensure_state, execute_step
from .safety import SafetyError

Log = Callable[[str], None]

# UDS identification records (ISO 14229), plus the ones PSA uses instead.
IDENT = {
    "F190": "Vehicle identification number",
    "F187": "Part number",
    "F18C": "Serial number",
    "F191": "Hardware number",
    "F195": "Software version",
    "F197": "System name",
    "F080": "Part number (PSA)",
}
OBD_MODES = {"03": "stored", "07": "pending", "0A": "permanent"}
FUNCTIONAL = {"7DF", "DB33F1", "18DB33F1"}

# BMW diagnostic addresses asked over ENET. Names from the bmwGxx/G-Diag ECU catalogue (MIT);
# 0x07 is the high-voltage battery unit in the OBDb captures.
BMW_UNITS = {
    0x01: "ACSM (Airbag)", 0x07: "SME (high-voltage battery)", 0x0D: "KAFAS (camera)", 0x0E: "SME (per G-Diag)",
    0x10: "ZGW (Gateway)", 0x12: "DME/EDME (drive)", 0x13: "DME2", 0x18: "EGS (gearbox)", 0x19: "VTG",
    0x1A: "0x1A", 0x1C: "ICM (chassis)", 0x29: "DSC (brakes)", 0x2A: "EMF (parking brake)", 0x30: "EPS (steering)",
    0x40: "BDC (body)", 0x56: "FZD (roof)", 0x5D: "KAFAS (camera)", 0x60: "KOMBI (instrument cluster)",
    0x63: "HU (Headunit)", 0x64: "PDC (park distance control)", 0x67: "ZBE (iDrive controller)", 0x6D: "Passenger seat",
    0x6E: "Driver seat", 0x71: "AHM (trailer)", 0x72: "FLE (headlights)", 0x78: "IHKA (climate)",
}

_STATUS = ((0x01, "active"), (0x08, "confirmed"), (0x04, "pending"), (0x20, "occurred since clearing"), (0x80, "warning lamp"))


@dataclass
class Unit:
    label: str                      # e.g. "6B4" or "6F1/07"
    ask: Callable[[str], tuple[bytes, str]]   # request -> (data after the echo, shown answer)
    functional: bool = False
    known: bool = False             # it answered a profile's request, so it exists even if it is silent here


def unit_label(profile: Profile, step: Step) -> str | None:
    """'6B4' or '6F1/07' from the adapter commands of a step (None: no request header)."""
    header = ext = None
    for cmd in [*profile.init, *step.at]:
        norm = cmd.replace(" ", "").upper()
        if norm.startswith("ATSH"):
            header = norm[4:]
        elif norm.startswith("ATCEA") and len(norm) > 5:
            ext = norm[5:]
    if header is None:
        return None
    return f"{header}/{ext}" if ext else header


def unit_for(adapter, profile: Profile, step: Step) -> Unit | None:
    label = unit_label(profile, step)
    if label is None or step.listen:
        return None

    def ask(cmd: str) -> tuple[bytes, str]:
        probe_step = Step("diag", step.at, cmd, None, None, list(step.pre), list(step.post), step.bus)
        ensure_state(adapter, profile, probe_step, force_init=True)
        resp, shown = execute_step(adapter, probe_step)
        return resp.data, shown

    return Unit(label, ask, label.split("/")[0] in FUNCTIONAL, known=True)


def enet_unit(adapter, address: int) -> Unit:
    def ask(cmd: str) -> tuple[bytes, str]:
        adapter.at(f"ATCEA{address:02X}")
        resp = adapter.request(cmd)
        return resp.payload[len(bytes.fromhex(cmd)):], f"{resp.ecu}: {resp.payload.hex(' ').upper()}"

    return Unit(f"6F1/{address:02X}", ask)


def text_or_hex(data: bytes) -> str:
    stripped = data.strip(b"\x00 \xff")
    if stripped and all(0x20 <= b < 0x7F for b in stripped):
        return stripped.decode("ascii")
    return data.hex(" ").upper()


def dtc_name(high: int, low: int) -> str:
    """Two code bytes -> P0A80 style (SAE J2012): letter from the top two bits."""
    return f"{'PCBU'[high >> 6]}{(high >> 4) & 3}{high & 0x0F:X}{low:02X}"


def status_text(status: int) -> str:
    return ", ".join(text for bit, text in _STATUS if status & bit) or "not active"


def parse_uds_dtcs(data: bytes) -> list[dict]:
    """Records after '59 02 <mask>': 3 code bytes + status byte."""
    out = []
    for i in range(0, len(data) - 3, 4):
        a, b, c, status = data[i : i + 4]
        if not (a or b or c):
            continue
        out.append({"code": f"{dtc_name(a, b)}-{c:02X}", "hex": f"{a:02X}{b:02X}{c:02X}", "status": status,
                    "text": status_text(status)})
    return out


def parse_obd_dtcs(data: bytes, kind: str) -> list[dict]:
    """After '4x': number of codes, then 2 bytes per code (CAN)."""
    out = []
    body = data[1:] if len(data) % 2 else data
    for i in range(0, len(body) - 1, 2):
        a, b = body[i], body[i + 1]
        if a or b:
            out.append({"code": dtc_name(a, b), "hex": f"{a:02X}{b:02X}", "status": None, "text": kind})
    return out


def read_unit(unit: Unit) -> dict | None:
    """Identification and fault codes of one control unit; None if it does not answer at all."""
    result: dict = {"unit": unit.label, "ident": {}, "dtcs": [], "requests": {}}
    alive = unit.known

    def ask(cmd: str) -> bytes | None:
        nonlocal alive
        try:
            data, shown = unit.ask(cmd)
        except NegativeResponse as e:
            alive = True
            result["requests"][cmd] = str(e)
            return None
        except (AdapterError, SafetyError) as e:
            result["requests"][cmd] = str(e)
            return None
        alive = True
        result["requests"][cmd] = shown
        return data

    if unit.functional:
        errors = []
        for mode, kind in OBD_MODES.items():
            data = ask(mode)
            if data is None:
                errors.append(mode)
            else:
                result["dtcs"] += parse_obd_dtcs(data, kind)
        if len(errors) == len(OBD_MODES):
            result["dtc_error"] = "no answer to the OBD fault query (03, 07, 0A)"
        return result if alive else None

    for did, name in IDENT.items():
        data = ask("22" + did)
        if data:
            result["ident"][name] = text_or_hex(data)
        if not alive and did == "F187":
            return None  # silent to the first two questions: not there
    data = ask("1902FF")
    if data is None:
        result["dtc_error"] = result["requests"]["1902FF"]
    else:
        result["dtcs"] = parse_uds_dtcs(data)
    return result


def scan(units: list[Unit], log: Log = print) -> list[dict]:
    out = []
    for unit in units:
        found = read_unit(unit)
        if found is None:
            continue
        name = BMW_UNITS.get(int(unit.label.split("/")[1], 16)) if unit.label.startswith("6F1/") else None
        if name:
            found["name"] = name
        out.append(found)
        faults = found.get("dtc_error") or f"{len(found['dtcs'])} fault entries"
        log(f"  Control unit {unit.label}{' ' + name if name else ''}: {faults}")
    return out
