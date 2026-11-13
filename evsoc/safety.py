"""Read-only guard: only diagnostic requests that cannot change the car get sent."""

from __future__ import annotations


class SafetyError(RuntimeError):
    pass


# Service ID -> allowed sub-functions (None = any).
_ALLOWED: dict[int, set[int] | None] = {
    0x01: None,          # OBD: current data
    0x09: None,          # OBD: vehicle information (VIN)
    0x22: None,          # UDS: ReadDataByIdentifier
    0x1A: None,          # KWP2000: ReadEcuIdentification
    0x21: None,          # KWP2000: ReadDataByLocalIdentifier (older Hyundai/Kia)
    0x10: {0x01, 0x03},  # UDS: default / extended session (some cars need it to read)
    0x3E: None,          # UDS: TesterPresent
    0x03: None,          # OBD: stored fault codes (reading only; mode 04 would clear them and stays blocked)
    0x07: None,          # OBD: pending fault codes
    0x0A: None,          # OBD: permanent fault codes
    0x19: {0x01, 0x02},  # UDS: ReadDTCInformation, number of codes / codes by status mask (0x14 would clear)
}

# AT commands that would flood or hang the link.
_BLOCKED_AT = ("ATMA", "ATMR", "ATMT", "STM")


def decode_request(cmd: str, caf: bool = True) -> bytes:
    """Hex command as sent to the adapter -> UDS request bytes.

    With CAN auto formatting off (ATCAF0) the command carries its own ISO-TP
    PCI byte and padding, e.g. '0322028C55555555' -> 22 02 8C.
    """
    hexstr = cmd.replace(" ", "")
    if len(hexstr) % 2:
        hexstr = hexstr[:-1]  # trailing ELM "number of responses" digit, e.g. 22D4101
    try:
        raw = bytes.fromhex(hexstr)
    except ValueError as e:
        raise SafetyError(f"Invalid command {cmd!r}") from e
    if not raw:
        raise SafetyError("Empty command")
    if not caf:
        length = raw[0] & 0x0F
        if raw[0] >> 4 != 0 or length == 0 or length > len(raw) - 1:
            raise SafetyError(f"Cannot decode raw command {cmd!r}")
        raw = raw[1 : 1 + length]
    return raw


def check_request(req: bytes) -> None:
    sid = req[0]
    if sid not in _ALLOWED:
        raise SafetyError(
            f"Service 0x{sid:02X} is not allowed. evsoc only sends read commands (allowed: {', '.join(f'0x{s:02X}' for s in sorted(_ALLOWED))})."
        )
    subs = _ALLOWED[sid]
    if subs is not None and (len(req) < 2 or (req[1] & 0x7F) not in subs):
        raise SafetyError(f"Service 0x{sid:02X} with this parameter is not allowed.")


def check_at(cmd: str) -> None:
    norm = cmd.replace(" ", "").upper()
    if norm.startswith(_BLOCKED_AT):
        raise SafetyError(f"Adapter command {cmd!r} is blocked (bus monitoring).")
