"""Listen in on BMW/Mini apps that use ENET (HSFZ over TCP 6801), e.g. BimmerLink with a UCSI-3000.

ENET is point-to-point Ethernet, so a Y cable cannot tap it. Instead evsoc sits
in the middle and looks like an ENET adapter to the app:

    app (phone/laptop) ──WiFi/LAN──► evsoc  :6801 / :6811 ──► ENET adapter or cable ──► car

Every byte is forwarded unchanged in both directions; evsoc only reads along.
Diagnostic messages are turned into the CAN frames a BMW tester would send
(tester 0x6F1 + target ECU byte, answers from 0x600 + ECU with 0xF1), so the
rest of `evsoc sniff` (profiles, formula search, profile export, log replay)
works exactly as on CAN, and exported steps run over ENET and CAN alike.
"""

from __future__ import annotations

import queue
import re
import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator

from . import enet
from .elm import AdapterError
from .sniff import Frame

Log = Callable[[str], None]

TESTER_ID = 0x6F1
MAX_HSFZ = 1 << 20


def hsfz_frames(t: float, src: int, dst: int, uds: bytes, from_tester: bool) -> list[Frame]:
    """One HSFZ diagnostic message as BMW-style CAN frames with extended addressing."""
    can_id, prefix = (TESTER_ID, bytes([dst])) if from_tester else (0x600 + src, b"\xf1")
    if len(uds) <= 6:
        frames = [prefix + bytes([len(uds)]) + uds]
    else:
        if len(uds) <= 0xFFF:
            first = prefix + bytes([0x10 | len(uds) >> 8, len(uds) & 0xFF])
        else:  # ISO-TP escape for long messages
            first = prefix + b"\x10\x00" + len(uds).to_bytes(4, "big")
        room = 8 - len(first)
        frames, rest, seq = [first + uds[:room]], uds[room:], 1
        while rest:
            frames.append(prefix + bytes([0x20 | seq & 0x0F]) + rest[:6])
            rest, seq = rest[6:], seq + 1
    return [Frame(t, can_id, False, f) for f in frames]


def _local_addresses() -> list[str]:
    text = enet._run(["ip", "-4", "-o", "addr"]) or enet._run(["ifconfig"])
    return [a for a in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", text) if not a.startswith("127.")]


class EnetProxySource:
    """TCP 6801 proxy plus answers to the vehicle search (UDP 6811)."""

    def __init__(self, upstream: str = "auto", listen: str = "0.0.0.0", port: int | None = None,
                 discovery: bool = True, vin: str | None = None, log: Log = print):
        self.log = log
        self.port = port if port is not None else enet.HSFZ_PORT
        if upstream in ("", "auto"):
            car = enet.find_vehicle()
            if not car:
                raise AdapterError("No BMW found over ENET. ENET adapter/cable plugged in, ignition on, Pi on the adapter's network? Otherwise give the address: enet-proxy://192.168.16.254")
            upstream, found_vin, how = car
            vin = vin or (found_vin if found_vin != "?" else None)
            log(f"ENET: vehicle at {upstream} ({how})")
        self.upstream = upstream
        self.bitrate = 500_000
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._socks: list[socket.socket] = []
        self.connections = 0
        self.ident = self._upstream_ident() if discovery else None
        if discovery and self.ident is None:
            vin = vin or self._read_vin()
            self.ident = b"DIAGADR10BMWMAC000000000000BMWVIN" + (vin or "0" * 17).encode()[:17]
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._srv.bind((listen, self.port))
        except OSError as e:
            raise AdapterError(f"Port {self.port} is in use ({e}). Is 'evsoc run' or a second session running?") from e
        self.port = self._srv.getsockname()[1]
        self._srv.listen(4)
        self._srv.settimeout(0.5)
        threading.Thread(target=self._accept, daemon=True).start()
        if discovery:
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                self._udp.bind((listen, enet.DISCOVERY_PORT))
                self._udp.settimeout(0.5)
                threading.Thread(target=self._answer_search, daemon=True).start()
            except OSError as e:
                log(f"Note: vehicle discovery (UDP {enet.DISCOVERY_PORT}) not possible ({e}). Then enter evsoc's address in the app.")
        where = listen if listen != "0.0.0.0" else ", ".join(_local_addresses()) or "this computer"
        self.description = f"ENET listener: app connects to {where} port {self.port}, passed on to {upstream}"

    # -- vehicle search ------------------------------------------------------------------

    def _upstream_ident(self) -> bytes | None:
        """The car's own answer to the vehicle search, to hand it on unchanged."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            try:
                s.sendto(struct.pack(">IH", 0, enet.CTRL_IDENT), (self.upstream, enet.DISCOVERY_PORT))
                data, _ = s.recvfrom(1024)
            except OSError:
                return None
        if len(data) > 6 and b"BMWVIN" in data:
            return data[6:]
        return None

    def _read_vin(self) -> str | None:
        try:
            a = enet.EnetAdapter(self.upstream, timeout=2.0)
        except AdapterError:
            return None
        try:
            a.at("ATCEA10")  # central gateway
            vin = a.request("22F190").payload[3:20].decode("ascii", "replace")
            return vin if re.fullmatch(r"[A-Z0-9]{17}", vin) else None
        except Exception:  # noqa: BLE001 - VIN is only cosmetic for the search answer
            return None
        finally:
            a.close()

    def _answer_search(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._udp.recvfrom(1024)
            except TimeoutError:
                continue
            except OSError:
                return
            if len(data) >= 6 and struct.unpack(">IH", data[:6]) == (0, enet.CTRL_IDENT) and addr[0] != self.upstream:
                self._udp.sendto(struct.pack(">IH", len(self.ident), enet.CTRL_IDENT) + self.ident, addr)
                self.log(f"Vehicle discovery from {addr[0]} answered")

    # -- TCP 6801 ------------------------------------------------------------------------

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                client, addr = self._srv.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                up = socket.create_connection((self.upstream, enet.HSFZ_PORT), timeout=5)
            except OSError as e:
                self.log(f"App {addr[0]} connected, but {self.upstream} not reachable: {e}")
                client.close()
                continue
            self.connections += 1
            self.log(f"App connected from {addr[0]}, passed on to {self.upstream}")
            for s in (client, up):
                s.settimeout(None)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._socks.append(s)
            threading.Thread(target=self._pump, args=(client, up, True, addr[0]), daemon=True).start()
            threading.Thread(target=self._pump, args=(up, client, False, addr[0]), daemon=True).start()

    def _pump(self, src: socket.socket, dst: socket.socket, from_app: bool, who: str) -> None:
        """Forward everything; parse HSFZ on the way. Unknown bytes are forwarded raw."""
        buf = b""
        parse = True
        try:
            while not self._stop.is_set():
                chunk = src.recv(65536)
                if not chunk:
                    break
                dst.sendall(chunk)
                if not parse:
                    continue
                buf += chunk
                while len(buf) >= 6:
                    length, ctrl = struct.unpack(">IH", buf[:6])
                    if length > MAX_HSFZ:
                        parse = False
                        self.log("Note: traffic is not HSFZ, only passed through")
                        break
                    if len(buf) < 6 + length:
                        break
                    body, buf = buf[6 : 6 + length], buf[6 + length :]
                    if ctrl == enet.CTRL_DIAG and len(body) >= 3:
                        self._q.put((time.time(), body[0], body[1], body[2:], from_app))
                    elif ctrl >= 0x0040:
                        self.log(f"Gateway reports error 0x{ctrl:04X}")
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()
            if from_app:
                self.log(f"App {who} disconnected")

    # -- source interface -------------------------------------------------------------------

    def frames(self) -> Iterator[Frame | None]:
        while not self._stop.is_set():
            try:
                t, src, dst, uds, from_app = self._q.get(timeout=0.2)
            except queue.Empty:
                yield None
                continue
            yield from hsfz_frames(t, src, dst, uds, from_app)

    def close(self) -> None:
        self._stop.set()
        for s in [self._srv, getattr(self, "_udp", None), *self._socks]:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
