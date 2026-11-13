"""ELM327 / STN (OBDLink) protocol handling: AT commands, frame parsing, ISO-TP reassembly."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from .safety import check_at, check_request, decode_request
from .transports import Transport


class AdapterError(RuntimeError):
    pass


class NoResponse(AdapterError):
    pass


class NegativeResponse(AdapterError):
    def __init__(self, sid: int, nrc: int):
        self.sid, self.nrc = sid, nrc
        super().__init__(f"Control unit refuses service 0x{sid:02X} (NRC 0x{nrc:02X}: {_NRC.get(nrc, '?')})")


_NRC = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x22: "conditionsNotCorrect (ignition off?)",
    0x31: "requestOutOfRange (DID unknown)",
    0x33: "securityAccessDenied",
    0x7F: "serviceNotSupportedInActiveSession",
}

_ERRORS = (
    "NO DATA", "CAN ERROR", "BUS ERROR", "BUS BUSY", "UNABLE TO CONNECT", "BUFFER FULL",
    "DATA ERROR", "<DATA ERROR", "<RX ERROR", "RX ERROR", "FB ERROR", "ACT ALERT",
    "LV RESET", "STOPPED", "ERR",
)

_HEX = re.compile(r"^[0-9A-F]+$")

# AT command families whose last value is remembered, longest prefix first.
_FAMILIES = sorted(
    ["FCSH", "FCSD", "FCSM", "CRA", "CEA", "CER", "CFC", "CAF", "CSM", "SH", "SP", "TP",
     "CP", "CF", "CM", "ST", "TA", "AT", "PB", "AL", "NL", "IIA", "SR", "WM", "IB"],
    key=len, reverse=True,
)
_FAMILY_ALIAS = {"AL": "LEN", "NL": "LEN", "SR": "CRA", "TP": "SP"}

# Commands that switch something off; old clones answer "?" and that is fine.
_TOLERANT = {"ATCEA", "ATCRA", "ATCSM0", "ATCSM1", "ATFCSM0", "ATAT0", "ATAT1", "ATAT2", "ATCFC1"}


def at_family(cmd: str) -> str | None:
    norm = cmd.replace(" ", "").upper()
    if not norm.startswith("AT"):
        return None
    body = norm[2:]
    for fam in _FAMILIES:
        if body.startswith(fam):
            return _FAMILY_ALIAS.get(fam, fam)
    return None


@dataclass
class UdsResponse:
    ecu: str        # CAN id that answered, e.g. "7EC" or "18DAF1DB"
    payload: bytes  # complete UDS response, starting with the positive-response SID
    raw: bytes = b""  # all raw CAN data bytes of that ECU's frames (WiCAN indexing)


@dataclass
class _Frames:
    data: list[bytes] = field(default_factory=list)
    raw: list[bytes] = field(default_factory=list)


class ElmAdapter:
    """Talks to anything that speaks the ELM327 command set.

    Headers (ATH1), no spaces (ATS0) and no DLC (ATD0) are enforced so every
    response line is `<CAN id><raw CAN data incl. ISO-TP PCI>`. 11-bit ids give
    an odd number of hex digits, 29-bit ids an even number, so lines can be
    split without knowing the protocol.
    """

    _FORCED = ("ATE0", "ATL0", "ATS0", "ATH1", "ATD0")
    _OVERRIDDEN = re.compile(r"^AT(E|L|S|H|D)[01]$")
    _RESETS = ("ATZ", "ATD", "ATWS")
    caf = True

    def __init__(self, transport: Transport, timeout: float = 5.0):
        self.t = transport
        self.timeout = timeout
        self.version = ""
        self._reset_state()

    def _reset_state(self) -> None:
        self.caf = True
        self.ext_addr: int | None = None
        self.tester_addr: int | None = None
        self._state: dict[str, str] = {}

    # -- low level ---------------------------------------------------------

    def _send(self, cmd: str, timeout: float | None = None) -> list[str]:
        self.t.write(cmd.encode("ascii") + b"\r")
        return self._read_prompt(cmd, timeout)

    def _read_prompt(self, cmd: str, timeout: float | None = None) -> list[str]:
        deadline = time.monotonic() + (timeout or self.timeout)
        buf = b""
        while b">" not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NoResponse(f"The adapter does not answer {cmd!r} (timeout)")
            buf += self.t.read(min(remaining, 0.5))
        text = buf.split(b">")[0].decode("ascii", "replace")
        lines = [l.strip() for l in re.split(r"[\r\n]+", text)]
        norm_cmd = cmd.replace(" ", "").upper()
        return [l for l in lines if l and l.replace(" ", "").upper() != norm_cmd]

    def _apply_forced(self) -> None:
        for cmd in self._FORCED:
            self._send(cmd)

    # -- public API --------------------------------------------------------

    def reset(self) -> None:
        """Full restart (ATZ) and forced settings. Use once per connection."""
        try:
            self._send("ATZ", timeout=5)
        except NoResponse:
            self.t.write(b"\r")  # some clones need a wake-up CR first
            time.sleep(0.5)
            self.t.read(0.5)
            self._send("ATZ", timeout=5)
        self._reset_state()
        self._apply_forced()
        info = self._send("ATI")
        self.version = info[0] if info else "?"

    def reset_fast(self) -> None:
        """Back to defaults without rebooting the chip (ATD), for switching profiles."""
        self._send("ATD")
        self._reset_state()
        self._apply_forced()

    def voltage(self) -> float | None:
        """12 V battery voltage at the OBD socket, measured by the adapter itself (no bus traffic)."""
        try:
            lines = self._send("ATRV")
        except NoResponse:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)\s*V", " ".join(lines))
        return float(m.group(1)) if m else None

    def prepare(self, commands: list[str]) -> bool:
        """Reset to defaults only if a setting from earlier would leak into these commands.

        Returns True if a reset happened."""
        wanted = {at_family(c) for c in commands} - {None}
        if set(self._state) - wanted:
            self.reset_fast()
            return True
        return False

    def at(self, cmd: str) -> None:
        """Run a configuration command; unchanged settings are not re-sent."""
        check_at(cmd)
        norm = cmd.replace(" ", "").upper()
        if self._OVERRIDDEN.match(norm) or norm in ("ATI", "ATRV"):
            return
        if norm in self._RESETS:
            self.reset_fast() if norm != "ATZ" else self.reset()
            return
        fam = at_family(norm)
        if fam and self._state.get(fam) == norm:
            return
        lines = self._send(cmd, 5 if norm.startswith("ATSP") else None)
        if any(l.strip() == "?" for l in lines):
            if norm in _TOLERANT or norm.startswith("ATST"):
                return
            raise AdapterError(
                f"The adapter does not know {cmd!r} ({self.version}). Cheap ELM327 clones often lack commands; OBDLink or vLinker are more reliable."
            )
        if fam:
            self._state[fam] = norm
        if fam == "CAF":
            self.caf = norm.endswith("1")
        elif fam == "CEA":
            arg = norm[5:]
            self.ext_addr = int(arg, 16) if arg else None
        elif fam == "SH" and len(norm) == 7:
            self.tester_addr = int(norm[4:], 16) & 0xFF
        elif fam == "TA":
            self.tester_addr = int(norm[4:], 16)

    def request(self, cmd: str) -> UdsResponse:
        """Send a diagnostic request, return the matching positive response."""
        req = decode_request(cmd, self.caf)
        check_request(req)
        wire = cmd.replace(" ", "")
        if len(wire) % 2:  # trailing ELM "number of responses" digit from Car Scanner logs
            wire = wire[:-1]
        lines = self._send(wire)
        return self.parse_response(req, lines)

    def listen(self, can_id: str, timeout: float = 2.0) -> bytes:
        """Passively wait for one broadcast frame with this CAN id (nothing is transmitted)."""
        self.at(f"ATCRA{can_id}")
        self.t.write(b"ATMA\r")
        deadline = time.monotonic() + timeout
        buf = b""
        frame: bytes | None = None
        try:
            while time.monotonic() < deadline and frame is None:
                buf += self.t.read(0.2)
                *lines, buf = re.split(rb"[\r\n]+", buf)
                for line in lines:
                    compact = line.decode("ascii", "replace").replace(" ", "").upper()
                    if compact.startswith(can_id.upper()) and _HEX.match(compact):
                        frame = bytes.fromhex(compact[len(can_id):])
                        break
        finally:
            self.t.write(b"\r")  # any character stops monitoring
            try:
                self._read_prompt("ATMA", 2)
            except NoResponse:
                pass
            self._state.pop("CRA", None)
        if frame is None:
            raise NoResponse(f"No frame 0x{can_id} heard (wrong bus or vehicle asleep?)")
        return frame

    def close(self) -> None:
        self.t.close()

    # -- parsing -----------------------------------------------------------

    def parse_response(self, req: bytes, lines: list[str]) -> UdsResponse:
        frames: OrderedDict[str, _Frames] = OrderedDict()
        errors = []
        for line in lines:
            compact = line.replace(" ", "").upper()
            if compact in ("OK", "SEARCHING...") or compact.startswith("BUSINIT"):
                continue
            if not _HEX.match(compact):
                if any(compact.startswith(e.replace(" ", "")) for e in _ERRORS) or compact == "?":
                    errors.append(line)
                continue
            hdr_len = 3 if len(compact) % 2 else 8
            if len(compact) <= hdr_len:
                continue
            ecu, raw = compact[:hdr_len], bytes.fromhex(compact[hdr_len:])
            data = raw
            if self.ext_addr is not None and data and data[0] == self.tester_addr:
                data = data[1:]  # extended addressing: first byte is the receiver address
            entry = frames.setdefault(ecu, _Frames())
            entry.data.append(data)
            entry.raw.append(raw)

        if not frames:
            if errors:
                raise NoResponse(f"No answer: {'; '.join(errors)}")
            raise NoResponse("No answer from the vehicle")

        negative: NegativeResponse | None = None
        for ecu, entry in frames.items():
            for payload in isotp_reassemble(entry.data):
                if payload[:1] == b"\x7f" and len(payload) >= 3 and payload[1] == req[0]:
                    if payload[2] != 0x78:  # 0x78 = response pending, real answer follows
                        negative = NegativeResponse(payload[1], payload[2])
                    continue
                if payload[0] == req[0] + 0x40 and payload[1 : len(req)] == req[1:]:
                    raw = b"".join(r for r, d in zip(entry.raw, entry.data, strict=True) if not _is_pending(d))
                    return UdsResponse(ecu, payload, raw)
        if negative:
            raise negative
        raise NoResponse(f"No matching answer to {req.hex().upper()}")


def _is_pending(frame: bytes) -> bool:
    return len(frame) >= 4 and frame[0] >> 4 == 0 and frame[1] == 0x7F and frame[3] == 0x78


def isotp_reassemble(frames: list[bytes]) -> list[bytes]:
    """Turn the raw CAN frames of one sender into ISO-TP messages."""
    messages: list[bytes] = []
    current = bytearray()
    expected = 0
    for f in frames:
        if not f:
            continue
        kind = f[0] >> 4
        if kind == 0:  # single frame
            length = f[0] & 0x0F
            if length == 0 and len(f) > 1:  # CAN-FD style escape
                length, body = f[1], f[2:]
            else:
                body = f[1:]
            messages.append(bytes(body[:length]))
        elif kind == 1:  # first frame
            expected = ((f[0] & 0x0F) << 8) | f[1]
            current = bytearray(f[2:])
        elif kind == 2 and expected:  # consecutive frame
            current.extend(f[1:])
            if len(current) >= expected:
                messages.append(bytes(current[:expected]))
                current, expected = bytearray(), 0
        # kind 3 = flow control from another tester; ignore
    if expected and current:
        messages.append(bytes(current))  # truncated, but better than nothing
    return [m for m in messages if m]


def isotp_segment(payload: bytes, ext: int | None = None) -> list[bytes]:
    """Split a message into classic CAN ISO-TP frames (used by ENET and the mock)."""
    prefix = bytes([ext]) if ext is not None else b""
    sf_max = 7 - len(prefix)
    if len(payload) <= sf_max:
        return [prefix + bytes([len(payload)]) + payload]
    frames = [prefix + bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[: sf_max - 1]]
    rest, seq = payload[sf_max - 1 :], 1
    while rest:
        frames.append(prefix + bytes([0x20 | (seq & 0x0F)]) + rest[:sf_max])
        rest, seq = rest[sf_max:], seq + 1
    return frames
