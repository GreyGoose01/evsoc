"""Raw CAN backend via python-can: any SocketCAN, PCAN, Kvaser, slcan (CANable),
gs_usb (candleLight), Vector, comma panda ... interface, CAN-FD included.

evsoc does the ISO-TP segmentation, flow control and addressing itself and
understands the same AT commands the profiles use, so ELM profiles run
unchanged:

    ATSP6/7/8/9, ATPB, ATSH, ATCP, ATCRA, ATCEA, ATCAF0/1, ATFCSH, ATFCSD, ATST
"""

from __future__ import annotations

import time

from .elm import AdapterError, NegativeResponse, NoResponse, UdsResponse, at_family
from .safety import check_at, check_request, decode_request

# ELM protocol number -> (29-bit ids, bitrate)
_PROTOCOLS = {"6": (False, 500_000), "7": (True, 500_000), "8": (False, 250_000), "9": (True, 250_000),
              "0": (False, 500_000)}
_PB_RATES = {0x01: 500_000, 0x02: 250_000, 0x04: 125_000}


class CanAdapter:
    caf = True

    def __init__(self, interface: str, channel: str, bitrate: int = 500_000, fd: bool = False,
                 pad: int = 0x00, timeout: float = 1.0, bus=None, listen_only: bool = False,
                 pins: tuple[int, ...] = (6, 14)):
        try:
            import can  # noqa: F401
        except ImportError as e:
            raise AdapterError("python-can missing: pip install python-can") from e
        self.interface, self.channel, self.fd, self.pad = interface, channel, fd, pad
        self.listen_only = listen_only
        from .connection import Capabilities
        self.capabilities = Capabilities(  # what the interface + its OBD cable can reach
            f"CAN-Interface {interface}", {"can", "canfd"} if fd else {"can"}, {tuple(pins)},
            notes=[f"cable on pins {'/'.join(map(str, pins))}"])
        self.default_bitrate = bitrate
        self.timeout = timeout
        self.version = f"python-can {interface}:{channel}"
        self._bus = bus
        self._bus_bitrate = bitrate if bus is not None else None
        self.reset()

    # -- adapter interface -----------------------------------------------------

    def reset(self) -> None:
        self.caf = True
        self.extended = False
        self.bitrate = self.default_bitrate
        self.header: str | None = None
        self.priority = 0x18
        self.rx_filter: str | None = None
        self.ext_addr: int | None = None
        self.fc_header: str | None = None
        self.fc_data: bytes | None = None
        self.user_pb: tuple[bool, int] | None = None
        self._state: dict[str, str] = {}

    reset_fast = reset

    def voltage(self) -> float | None:
        return None  # no voltage measurement on this hardware

    def prepare(self, commands: list[str]) -> bool:
        wanted = {at_family(c) for c in commands} - {None}
        if set(self._state) - wanted:
            self.reset()
            return True
        return False

    def at(self, cmd: str) -> None:
        check_at(cmd)
        norm = cmd.replace(" ", "").upper()
        if norm in ("ATZ", "ATD", "ATWS"):
            self.reset()
            return
        fam = at_family(norm)
        if fam:
            self._state[fam] = norm
        arg = norm[2 + len(fam or ""):] if fam else ""
        if fam == "SP":
            arg = arg.lstrip("A")
            if arg in _PROTOCOLS:
                self.extended, self.bitrate = _PROTOCOLS[arg]
            elif arg in ("B", "C") and self.user_pb:
                self.extended, self.bitrate = self.user_pb
        elif fam == "PB" and len(arg) >= 4:  # ATPB xx yy: bit 7 of xx = 11-bit, yy = 500k/x
            flags, div = int(arg[:2], 16), int(arg[2:4], 16)
            self.user_pb = (not flags & 0x80, _PB_RATES.get(div, 500_000 // max(div, 1)))
        elif fam == "SH":
            self.header = arg
            if len(arg) == 8:
                self.extended = True
        elif fam == "CP" and arg:
            self.priority = int(arg, 16)
        elif fam == "CRA":
            self.rx_filter = arg or None
        elif fam == "CEA":
            self.ext_addr = int(arg, 16) if arg else None
        elif fam == "CAF":
            self.caf = arg.endswith("1")
        elif fam == "FCSH":
            self.fc_header = arg
        elif fam == "FCSD":
            self.fc_data = bytes.fromhex(arg) if arg else None
        elif fam == "ST" and arg:
            self.timeout = max(0.2, int(arg, 16) * 0.004 * 2)

    def request(self, cmd: str) -> UdsResponse:
        if self.listen_only:
            raise AdapterError("Listen-only mode: requests are switched off")
        req = decode_request(cmd, self.caf)
        check_request(req)
        bus = self._open()
        tx = self._tx_id()
        if not self.caf:  # raw frame given by the profile, PCI included
            raw = bytes.fromhex(cmd.replace(" ", "")[: len(cmd.replace(" ", "")) // 2 * 2])
            self._send(bus, tx, raw)
        else:
            self._send_isotp(bus, tx, req)
        return self._receive(bus, req, tx)

    def bus_active(self, timeout: float = 1.0) -> bool:
        """True if any frame shows up, i.e. the car is awake. Sends nothing."""
        bus = self._open()
        return bus.recv(timeout) is not None

    def listen(self, can_id: str, timeout: float = 2.0) -> bytes:
        bus = self._open()
        want = int(can_id, 16)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = bus.recv(max(0.0, deadline - time.monotonic()))
            if msg is not None and msg.arbitration_id == want:
                return bytes(msg.data)
        raise NoResponse(f"No frame 0x{can_id} heard")

    def close(self) -> None:
        if self._bus is not None:
            self._bus.shutdown()
            self._bus = None

    # -- internals ----------------------------------------------------------------

    def _open(self):
        if self._bus is not None and self._bus_bitrate in (None, self.bitrate):
            return self._bus
        import can
        if self._bus is not None:
            self._bus.shutdown()
        try:
            self._bus = can.Bus(interface=self.interface, channel=self.channel, bitrate=self.bitrate, fd=self.fd)
        except (can.CanError, OSError, ValueError) as e:
            raise AdapterError(f"CAN interface {self.interface}:{self.channel} cannot be opened: {e}") from e
        self._bus_bitrate = self.bitrate
        if self.listen_only:
            try:
                self._bus.state = can.BusState.PASSIVE  # no ACKs, no error frames
            except (NotImplementedError, can.CanError) as e:
                raise AdapterError(f"{self.interface} has no listen-only mode: {e}") from e
        return self._bus

    def _tx_id(self) -> int:
        if self.extended:
            h = self.header or "DB33F1"
            return int(h, 16) if len(h) == 8 else (self.priority << 24) | int(h, 16)
        return int(self.header or "7DF", 16)

    def _rx_ok(self, arb_id: int, tx: int) -> bool:
        if arb_id == tx:
            return False
        if self.rx_filter:
            f = self.rx_filter
            if self.extended and len(f) <= 6:
                return arb_id & 0xFFFFFF == int(f, 16)
            return arb_id == int(f, 16)
        if not self.extended:
            if tx == 0x7DF:
                return 0x7E8 <= arb_id <= 0x7EF
            return arb_id == tx + 8 or 0x7E8 <= arb_id <= 0x7EF
        return (arb_id >> 8) & 0xFFFF == 0xDAF1 or arb_id & 0xFF == (tx >> 8) & 0xFF

    def _send(self, bus, arb_id: int, data: bytes) -> None:
        import can
        if self.pad is not None and not self.fd and len(data) < 8:
            data = data + bytes([self.pad]) * (8 - len(data))
        bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=self.extended,
                             is_fd=self.fd, bitrate_switch=self.fd))

    def _prefix(self) -> bytes:
        return bytes([self.ext_addr]) if self.ext_addr is not None else b""

    def _send_isotp(self, bus, tx: int, payload: bytes) -> None:
        prefix = self._prefix()
        room = 7 - len(prefix)
        if len(payload) <= room:
            self._send(bus, tx, prefix + bytes([len(payload)]) + payload)
            return
        self._send(bus, tx, prefix + bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[: room - 1])
        rest, seq = payload[room - 1 :], 1
        fc = self._wait_flow_control(bus, tx)
        stmin = fc[2] / 1000 if fc and fc[2] <= 0x7F else 0
        while rest:
            self._send(bus, tx, prefix + bytes([0x20 | (seq & 0x0F)]) + rest[:room])
            rest, seq = rest[room:], seq + 1
            time.sleep(stmin)

    def _wait_flow_control(self, bus, tx: int) -> bytes | None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = bus.recv(max(0.0, deadline - time.monotonic()))
            if msg is None or not self._rx_ok(msg.arbitration_id, tx):
                continue
            data = self._strip(bytes(msg.data))
            if data and data[0] >> 4 == 3:
                return data
        raise NoResponse("No flow control answer")

    def _strip(self, data: bytes) -> bytes:
        if self.ext_addr is not None and data:
            return data[1:]  # receiver address byte (BMW: F1)
        return data

    def _send_fc(self, bus, tx: int) -> None:
        arb = int(self.fc_header, 16) if self.fc_header else tx
        data = self.fc_data or (self._prefix() + bytes([0x30, 0x00, 0x00]))
        self._send(bus, arb, data)

    def _receive(self, bus, req: bytes, tx: int) -> UdsResponse:
        deadline = time.monotonic() + self.timeout
        partial: dict[int, tuple[int, bytearray, list[bytes]]] = {}  # id -> (expected, data, raw frames)
        negative: NegativeResponse | None = None
        while time.monotonic() < deadline:
            msg = bus.recv(max(0.0, deadline - time.monotonic()))
            if msg is None or not self._rx_ok(msg.arbitration_id, tx):
                continue
            original = bytes(msg.data)
            data = self._strip(original)
            if not data:
                continue
            kind, arb = data[0] >> 4, msg.arbitration_id
            if kind == 0:
                payload, frames = data[1 : 1 + (data[0] & 0x0F)], [original]
            elif kind == 1:
                expected = ((data[0] & 0x0F) << 8) | data[1]
                partial[arb] = (expected, bytearray(data[2:]), [original])
                self._send_fc(bus, tx)
                continue
            elif kind == 2 and arb in partial:
                expected, buf, frames = partial[arb]
                buf.extend(data[1:])
                frames.append(original)
                if len(buf) < expected:
                    continue
                payload = bytes(buf[:expected])
                del partial[arb]
            else:
                continue
            if payload[:1] == b"\x7f" and len(payload) >= 3 and payload[1] == req[0]:
                if payload[2] == 0x78:
                    deadline = time.monotonic() + 5.0  # ECU asks for more time
                else:
                    negative = NegativeResponse(payload[1], payload[2])
                continue
            if payload and payload[0] == req[0] + 0x40 and payload[1 : len(req)] == req[1:]:
                ecu = f"{arb:08X}" if self.extended else f"{arb:03X}"
                return UdsResponse(ecu, bytes(payload), b"".join(frames))
        if negative:
            raise negative
        raise NoResponse(f"No answer to {req.hex().upper()}")
