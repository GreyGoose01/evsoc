"""BMW / Mini ENET (HSFZ over TCP 6801) for F-, G- and I-series cars.

Accepts the same calls as ElmAdapter so BMW profiles (written for ELM with
ATSH6F1 / ATCEA<ecu>) run unchanged: ATCEA picks the target ECU, every other
AT command is ignored.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import struct
import subprocess
import time
from pathlib import Path

from .elm import AdapterError, NegativeResponse, NoResponse, UdsResponse, isotp_segment
from .safety import check_at, check_request, decode_request

HSFZ_PORT = 6801
DISCOVERY_PORT = 6811
TESTER = 0xF4
OBD_FUNCTIONAL = 0xDF

CTRL_DIAG = 0x0001
CTRL_ACK = 0x0002
CTRL_IDENT = 0x0011
CTRL_ALIVE = 0x0012
CTRL_ALIVE_REPLY = 0x0013


def discover(timeout: float = 2.0, targets: list[str] | None = None) -> list[tuple[str, str]]:
    """Broadcast a vehicle identification request; returns [(ip, vin)]."""
    found: dict[str, str] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        for target in targets or ["255.255.255.255"]:
            try:
                s.sendto(struct.pack(">IH", 0, CTRL_IDENT), (target, DISCOVERY_PORT))
            except OSError:
                continue  # e.g. no route to that subnet
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (ip, _port) = s.recvfrom(1024)
            except TimeoutError:
                break
            m = re.search(rb"BMWVIN([A-Z0-9]{17})", data)
            found.setdefault(ip, m.group(1).decode() if m else "?")
    return list(found.items())


def parse_linux_routes(text: str) -> list[str]:
    """Default gateways from /proc/net/route (hex, little endian), one per interface."""
    out = []
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) > 2 and cols[1] == "00000000" and cols[2] != "00000000":
            gw = socket.inet_ntoa(bytes.fromhex(cols[2])[::-1])
            if gw not in out:
                out.append(gw)
    return out


def parse_bsd_routes(text: str) -> list[str]:
    """Default gateways from `netstat -rn -f inet` (macOS/BSD)."""
    out = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) > 1 and cols[0] == "default" and re.fullmatch(r"[0-9.]+", cols[1]) and cols[1] not in out:
            out.append(cols[1])
    return out


def parse_broadcasts(text: str) -> list[str]:
    """Broadcast addresses of all IPv4 interfaces from `ip -4 -o addr` or `ifconfig`.

    Needed because 255.255.255.255 only leaves through the interface with the default route:
    an ENET adapter on a second interface (Pi: home network on WLAN, adapter on eth0) would
    never see the search otherwise."""
    out = []
    for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)(?:/(\d+))?(?:.*?netmask (0x[0-9a-f]+))?"
                         r"(?:.*?(?:brd|broadcast) (\d+\.\d+\.\d+\.\d+))?", text):
        addr, prefix, mask, brd = m.groups()
        if addr.startswith("127."):
            continue
        if not brd:
            bits = int(prefix) if prefix else (bin(int(mask, 16)).count("1") if mask else 24)
            brd = str(ipaddress.ip_network(f"{addr}/{bits}", strict=False).broadcast_address)
        if brd not in out:
            out.append(brd)
    return out


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def default_gateways() -> list[str]:
    route = Path("/proc/net/route")
    if route.exists():
        return parse_linux_routes(route.read_text())
    return parse_bsd_routes(_run(["netstat", "-rn", "-f", "inet"]))


def interface_broadcasts() -> list[str]:
    return parse_broadcasts(_run(["ip", "-4", "-o", "addr"]) or _run(["ifconfig"]))


def port_open(host: str, port: int = HSFZ_PORT, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_vehicle(timeout: float = 2.0) -> tuple[str, str, str] | None:
    """(ip, vin, how) of the car: by broadcast on every interface, else via an ENET adapter.

    ENET adapters with WLAN or LAN (e.g. UniCarScan UCSI-3000) form their own small network.
    Some answer the broadcast for the car, others only forward TCP 6801 at their own address,
    which is then a default gateway of that network."""
    targets = ["255.255.255.255"] + interface_broadcasts()
    cars = discover(timeout, targets)
    if cars:
        return cars[0][0], cars[0][1], "Broadcast"
    for gw in default_gateways():
        if port_open(gw, HSFZ_PORT, timeout):
            return gw, "?", "gateway of the WiFi/LAN adapter"
    return None


class EnetAdapter:
    caf = True

    def __init__(self, host: str, timeout: float = 5.0, log_path: str | None = None):
        self.host = host
        self.timeout = timeout
        self.version = f"ENET {host}"
        self.target: int | None = None
        try:
            self._s = socket.create_connection((host, HSFZ_PORT), timeout=timeout)
        except OSError as e:
            raise AdapterError(
                f"No ENET connection to {host}:{HSFZ_PORT}: {e}. Ignition on, cable plugged in?"
            ) from e
        # --log: one HSFZ frame per line (the ELM transports log their text traffic instead)
        self._log_file = open(log_path, "a", encoding="utf-8") if log_path else None
        if self._log_file:
            self._log_file.write(f"{time.strftime('%H:%M:%S')} # ENET {host}:{HSFZ_PORT}\n")

    def reset(self) -> None:
        self.target = None

    def reset_fast(self) -> None:
        self.target = None

    def voltage(self) -> float | None:
        return None  # no voltage measurement on this hardware

    def prepare(self, commands: list[str]) -> bool:
        self.target = None  # every BMW step names its ECU again via ATCEA
        return False

    def listen(self, can_id: str, timeout: float = 2.0) -> bytes:
        raise AdapterError("Passive listening needs a CAN adapter, not ENET")

    def at(self, cmd: str) -> None:
        check_at(cmd)
        norm = cmd.replace(" ", "").upper()
        if norm.startswith("ATCEA") and len(norm) == 7:
            self.target = int(norm[5:], 16)
        elif norm.startswith("ATCRA6") and len(norm) == 9 and self.target is None:
            self.target = int(norm[7:], 16)  # 0x6xx answers come from ECU xx

    def request(self, cmd: str) -> UdsResponse:
        req = decode_request(cmd)
        check_request(req)
        target = self.target if self.target is not None else OBD_FUNCTIONAL
        self._log(">", CTRL_DIAG, bytes([TESTER, target]) + req)
        self._s.sendall(struct.pack(">IH", len(req) + 2, CTRL_DIAG) + bytes([TESTER, target]) + req)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            ctrl, body = self._recv(deadline)
            if ctrl == CTRL_ALIVE:
                # the gateway asks whether this tester is still there (e.g. when a second one
                # connects); without an answer it may drop the connection
                reply = bytes([0x00, TESTER])
                self._log(">", CTRL_ALIVE_REPLY, reply)
                self._s.sendall(struct.pack(">IH", len(reply), CTRL_ALIVE_REPLY) + reply)
                continue
            if ctrl == CTRL_ACK or len(body) < 3:
                continue
            if ctrl >= 0x0040:
                raise AdapterError(f"Gateway reports error 0x{ctrl:04X}")
            src, payload = body[0], body[2:]
            if payload[0] == 0x7F and len(payload) >= 3 and payload[1] == req[0]:
                if payload[2] == 0x78:
                    deadline = time.monotonic() + self.timeout
                    continue
                raise NegativeResponse(payload[1], payload[2])
            if payload[0] == req[0] + 0x40 and payload[1 : len(req)] == req[1:]:
                raw = b"".join(isotp_segment(payload))  # lets WiCAN-style byte positions work too
                return UdsResponse(f"{src:02X}", payload, raw)
        raise NoResponse(f"No answer to {req.hex().upper()} from control unit 0x{target:02X}")

    def _recv(self, deadline: float) -> tuple[int, bytes]:
        header = self._read_exact(6, deadline)
        length, ctrl = struct.unpack(">IH", header)
        body = self._read_exact(length, deadline)
        self._log("<", ctrl, body)
        return ctrl, body

    def _log(self, direction: str, ctrl: int, body: bytes) -> None:
        """Control word, then source, target and UDS bytes in hex, e.g. '> 0001 F4 07 22 DD BC'."""
        if self._log_file:
            self._log_file.write(f"{time.strftime('%H:%M:%S')} {direction} {ctrl:04X} {body.hex(' ').upper()}\n")
            self._log_file.flush()

    def _read_exact(self, n: int, deadline: float) -> bytes:
        buf = b""
        while len(buf) < n:
            self._s.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self._s.recv(n - len(buf))
            except TimeoutError as e:
                raise NoResponse("ENET: timeout") from e
            if not chunk:
                raise AdapterError("ENET: connection closed")
            buf += chunk
        return buf

    def close(self) -> None:
        self._s.close()
        if self._log_file:
            self._log_file.close()
            self._log_file = None
