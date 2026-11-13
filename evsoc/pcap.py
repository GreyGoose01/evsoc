"""Read Ethernet recordings (pcap, pcapng) without extra packages, and record them on Linux.

Automotive Ethernet (100BASE-T1/1000BASE-T1) and ENET (100BASE-TX at the OBD
socket) are point-to-point links, so a recording comes from a TAP, a mirror
port of a switch or a media converter, made with tcpdump, Wireshark or
`evsoc analyse -a eth://eth0`. Recordings of a CAN interface made with
tcpdump/Wireshark (link type SocketCAN) are read as well.
"""

from __future__ import annotations

import socket
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

LINK_NULL, LINK_ETHERNET, LINK_RAW, LINK_SLL, LINK_CAN, LINK_IPV4, LINK_IPV6, LINK_SLL2 = 0, 1, 101, 113, 227, 228, 229, 276
VLAN_TYPES = (0x8100, 0x88A8, 0x9100)


class PcapError(ValueError):
    pass


@dataclass
class Packet:
    t: float
    length: int                    # on the wire
    src_mac: bytes | None = None
    dst_mac: bytes | None = None
    vlan: int | None = None
    prio: int | None = None
    ethertype: int | None = None
    l2: bytes = b""                # payload after the Ethernet header, if it is not IP
    src: str | None = None
    dst: str | None = None
    proto: str | None = None       # udp, tcp, icmp, ... or "ip-<n>"
    sport: int | None = None
    dport: int | None = None
    payload: bytes = b""           # UDP/TCP payload
    seq: int = 0
    syn: bool = False
    can: tuple[int, bool, bytes] | None = None  # CAN id, 29 bit, data


def read_records(f: BinaryIO) -> Iterator[tuple[float, int, bytes, int]]:
    """(time, link type, captured bytes, length on the wire) for every packet of a pcap or pcapng file."""
    magic = f.read(4)
    if magic == b"\x0a\x0d\x0d\x0a":
        yield from _pcapng(f)
        return
    for order in "<>":
        m = struct.unpack(order + "I", magic)[0] if len(magic) == 4 else 0
        if m in (0xA1B2C3D4, 0xA1B23C4D):
            frac = 1e-9 if m == 0xA1B23C4D else 1e-6
            link = struct.unpack(order + "HHiIII", f.read(20))[5] & 0xFFFF
            while len(head := f.read(16)) == 16:
                sec, sub, incl, orig = struct.unpack(order + "IIII", head)
                yield sec + sub * frac, link, f.read(incl), orig
            return
    raise PcapError("not a pcap or pcapng file")


def _pcapng(f: BinaryIO) -> Iterator[tuple[float, int, bytes, int]]:
    order, ifaces = "<", []
    btype = 0x0A0D0D0A
    while True:
        raw_len = f.read(4)
        if len(raw_len) < 4:
            return
        if btype == 0x0A0D0D0A:  # section header: byte order comes after the length
            bom = f.read(4)
            order = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            total = struct.unpack(order + "I", raw_len)[0]
            body = bom + f.read(total - 16)
            ifaces = []
        else:
            total = struct.unpack(order + "I", raw_len)[0]
            body = f.read(total - 12)
        f.read(4)
        if total < 12 or len(body) < total - 12:
            return
        if btype == 1:  # interface description
            link = struct.unpack(order + "H", body[:2])[0]
            res, pos = 1e-6, 8
            while pos + 4 <= len(body):
                code, n = struct.unpack(order + "HH", body[pos:pos + 4])
                if code == 9 and n == 1:
                    v = body[pos + 4]
                    res = 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
                if code == 0:
                    break
                pos += 4 + (n + 3) // 4 * 4
            ifaces.append((link, res))
        elif btype == 6 and len(body) >= 20:  # enhanced packet
            idx, hi, lo, cap, orig = struct.unpack(order + "IIIII", body[:20])
            link, res = ifaces[idx] if idx < len(ifaces) else (LINK_ETHERNET, 1e-6)
            yield ((hi << 32) | lo) * res, link, body[20:20 + cap], orig
        elif btype == 3 and ifaces:  # simple packet: no time stamp
            orig = struct.unpack(order + "I", body[:4])[0]
            yield 0.0, ifaces[0][0], body[4:4 + orig], orig
        head = f.read(4)
        if len(head) < 4:
            return
        btype = struct.unpack(order + "I", head)[0]


def decode(t: float, link: int, raw: bytes, length: int) -> Packet | None:
    p = Packet(t, length)
    if link == LINK_CAN:
        if len(raw) < 8:
            return None
        can_id = int.from_bytes(raw[:4], "big")
        if can_id & 0x60000000:  # remote or error frame
            return None
        ext = bool(can_id & 0x80000000)
        p.can = (can_id & (0x1FFFFFFF if ext else 0x7FF), ext, bytes(raw[8:8 + raw[4]]))
        return p
    if link == LINK_ETHERNET:
        if len(raw) < 14:
            return None
        p.dst_mac, p.src_mac = bytes(raw[:6]), bytes(raw[6:12])
        etype, pos = int.from_bytes(raw[12:14], "big"), 14
        while etype in VLAN_TYPES and len(raw) >= pos + 4:
            tci = int.from_bytes(raw[pos:pos + 2], "big")
            p.vlan, p.prio = tci & 0xFFF, tci >> 13
            etype, pos = int.from_bytes(raw[pos + 2:pos + 4], "big"), pos + 4
        body = raw[pos:]
    elif link == LINK_SLL and len(raw) >= 16:
        p.src_mac = bytes(raw[6:12]) if raw[4:6] == b"\x00\x06" else None
        etype, body = int.from_bytes(raw[14:16], "big"), raw[16:]
    elif link == LINK_SLL2 and len(raw) >= 20:
        p.src_mac = bytes(raw[12:18]) if raw[11] == 6 else None
        etype, body = int.from_bytes(raw[:2], "big"), raw[20:]
    elif link in (LINK_RAW, LINK_IPV4, LINK_IPV6, LINK_NULL):
        body = raw[4:] if link == LINK_NULL else raw
        etype = 0x86DD if body[:1] and body[0] >> 4 == 6 else 0x0800
    else:
        raise PcapError(f"Recording type (link type {link}) is not supported")
    p.ethertype = etype
    if etype == 0x0800 and len(body) >= 20:
        ihl, total = (body[0] & 0x0F) * 4, int.from_bytes(body[2:4], "big")
        proto, frag = body[9], int.from_bytes(body[6:8], "big") & 0x1FFF
        p.src, p.dst = socket.inet_ntoa(bytes(body[12:16])), socket.inet_ntoa(bytes(body[16:20]))
        l4 = body[ihl:total] if total >= ihl else body[ihl:]
    elif etype == 0x86DD and len(body) >= 40:
        proto, frag, pos = body[6], 0, 40
        p.src = socket.inet_ntop(socket.AF_INET6, bytes(body[8:24]))
        p.dst = socket.inet_ntop(socket.AF_INET6, bytes(body[24:40]))
        while proto in (0, 43, 44, 60) and len(body) >= pos + 8:  # extension headers
            if proto == 44:
                frag = int.from_bytes(body[pos + 2:pos + 4], "big") >> 3
            proto, pos = body[pos], pos + (8 if proto == 44 else (body[pos + 1] + 1) * 8)
        l4 = body[pos:]
    else:
        p.l2 = bytes(body)
        return p
    p.proto = {1: "icmp", 2: "igmp", 6: "tcp", 17: "udp", 58: "icmpv6"}.get(proto, f"ip-{proto}")
    if frag:
        p.proto += "-fragment"
    elif proto == 17 and len(l4) >= 8:
        p.sport, p.dport = struct.unpack(">HH", l4[:4])
        p.payload = bytes(l4[8:])
    elif proto == 6 and len(l4) >= 20:
        p.sport, p.dport, p.seq = struct.unpack(">HHI", l4[:8])
        p.syn = bool(l4[13] & 0x02)
        p.payload = bytes(l4[(l4[12] >> 4) * 4:])
    return p


def read_packets(path: str) -> Iterator[Packet]:
    with open(path, "rb") as f:
        for t, link, raw, length in read_records(f):
            p = decode(t, link, raw, length)
            if p is not None:
                yield p


def _distance(seq: int, nxt: int) -> int:
    d = (seq - nxt) & 0xFFFFFFFF
    return d - (1 << 32) if d >= 1 << 31 else d


class TcpStreams:
    """Puts TCP payload back in order, one byte stream per direction."""

    def __init__(self):
        self._next: dict[tuple, int] = {}
        self._waiting: dict[tuple, dict[int, bytes]] = {}

    def add(self, p: Packet) -> bytes:
        """The bytes that continue the stream of this packet's direction (may be empty)."""
        key = (p.src, p.sport, p.dst, p.dport)
        if p.syn:
            self._next[key] = (p.seq + 1) & 0xFFFFFFFF
            self._waiting.pop(key, None)
            return b""
        if not p.payload:
            return b""
        nxt = self._next.setdefault(key, p.seq)
        waiting = self._waiting.setdefault(key, {})
        waiting[p.seq] = p.payload
        out = b""
        while waiting:
            seq = min(waiting, key=lambda s: _distance(s, nxt))
            ahead = _distance(seq, nxt)
            if ahead > 0:
                if len(waiting) <= 64:
                    break
                nxt = seq  # a segment is missing in the recording: go on behind the gap
                continue
            data = waiting.pop(seq)
            if -ahead < len(data):  # retransmissions overlap what is already there
                out += data[-ahead:]
                nxt = (seq + len(data)) & 0xFFFFFFFF
        self._next[key] = nxt
        return out


# -- recording (Linux) ---------------------------------------------------------------------------

class EthSource:
    """Records everything an Ethernet interface sees into a pcap file (Linux, needs root). Sends nothing."""

    bitrate = 0

    def __init__(self, iface: str, path: str):
        if not hasattr(socket, "AF_PACKET"):
            raise OSError("Ethernet can only be recorded like this on Linux. On a Mac: sudo tcpdump -i en0 -w file.pcap, then evsoc analyse -d file.pcap")
        self.packets = 0
        try:
            self._s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
            self._s.bind((iface, 0))
            index = socket.if_nametoindex(iface)
        except PermissionError as e:
            raise OSError(f"Recording on {iface} needs root: sudo evsoc analyse -a eth://{iface}") from e
        except OSError as e:
            raise OSError(f"Ethernet interface {iface!r} cannot be opened ({e}). Available: "
                          + ", ".join(name for _, name in socket.if_nameindex())) from e
        self._s.setsockopt(263, 1, struct.pack("iHH8s", index, 1, 0, b""))  # promiscuous while the socket is open
        self._s.setsockopt(263, 8, 1)  # PACKET_AUXDATA: the kernel hands the VLAN tag over separately
        self._s.settimeout(0.2)
        self._f = open(path, "wb")
        self._f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, LINK_ETHERNET))
        self.description = f"Ethernet {iface}, everything arriving there (listen only)"
        self._stop = False

    def frames(self) -> Iterator[None]:
        while not self._stop:
            try:
                for _ in range(500):
                    data, anc, _flags, _addr = self._s.recvmsg(65535, 64)
                    for level, kind, aux in anc:
                        if level == 263 and kind == 8 and len(aux) >= 20:
                            status, _, _, _, _, tci, tpid = struct.unpack("IIIHHHH", aux[:20])
                            if status & 0x10:  # TP_STATUS_VLAN_VALID: put the tag back
                                data = data[:12] + struct.pack(">HH", tpid or 0x8100, tci) + data[12:]
                    t = time.time()
                    self._f.write(struct.pack("<IIII", int(t), int(t % 1 * 1e6), len(data), len(data)) + data)
                    self.packets += 1
            except TimeoutError:
                pass
            except OSError:
                return
            yield None

    def close(self) -> None:
        self._stop = True
        self._s.close()
        self._f.close()
