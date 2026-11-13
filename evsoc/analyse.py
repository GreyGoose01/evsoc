"""Boil a complete recording down to a report an assistant (or a person) can reason about.

A raw log of a few minutes has hundreds of thousands of lines. `evsoc analyse`
turns it into some hundred lines of Markdown: every CAN id with cycle time and
what each byte does (constant, counter, checksum, state, signal, 16-bit pairs),
how the payload develops over time, when it changed, all diagnostic
conversations, and the notes typed while recording ("door open"). Ethernet
recordings (pcap/pcapng) get the same treatment for DoIP, HSFZ (BMW ENET),
SOME/IP incl. service discovery and whatever else is on the wire.
"""

from __future__ import annotations

import bisect
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import pcap, sniff
from .elm import _NRC
from .sniff import Frame, Sniffer, clock, fmt_id, letters

MAX_BYTES = 64
ETHERTYPES = {0x0800: "IPv4", 0x0806: "ARP", 0x86DD: "IPv6", 0x88F7: "gPTP/PTP (time synchronisation)",
              0x22F0: "AVTP (IEEE 1722, audio/video)", 0x22EA: "SRP (stream reservation)", 0x88F5: "MVRP",
              0x88F6: "MMRP", 0x88CC: "LLDP", 0x88E5: "MACsec (encrypted)", 0x888E: "802.1X"}
PORTS = {53: "DNS", 67: "DHCP", 68: "DHCP", 80: "HTTP", 123: "NTP", 137: "NetBIOS", 319: "PTP", 320: "PTP",
         443: "TLS/HTTPS", 1900: "SSDP", 3490: "DLT (diagnostic log)", 5353: "mDNS", 5355: "LLMNR", 5555: "XCP?",
         6801: "HSFZ (BMW diagnostics)", 6811: "HSFZ vehicle discovery", 13400: "DoIP", 30490: "SOME/IP-SD"}
SOMEIP_TYPES = {0x00: "request", 0x01: "request without response", 0x02: "event", 0x80: "response", 0x81: "error"}
DOIP_TYPES = {0x0001: "vehicle discovery", 0x0002: "vehicle discovery (EID)", 0x0003: "vehicle discovery (VIN)"}


# -- one series of payloads ------------------------------------------------------------------------

@dataclass
class Stream:
    label: str
    note: str = ""
    times: list[float] = field(default_factory=list)
    payloads: list[bytes] = field(default_factory=list)
    sizes: Counter = field(default_factory=Counter)

    def add(self, t: float, data: bytes) -> None:
        self.times.append(t)
        self.payloads.append(bytes(data[:MAX_BYTES]))
        self.sizes[len(data)] += 1


@dataclass
class ByteInfo:
    kind: str                 # const, counter, nibble_lo, nibble_hi, check, flags, signal
    values: set[int]
    mask: int                 # bits that ever changed
    changes: int
    text: str = ""            # how a checksum is built, if that is known


@dataclass
class Field:
    start: int
    size: int
    order: str                # BE, LE
    lo: int = 0
    hi: int = 0
    distinct: int = 0

    def value(self, payload: bytes) -> int | None:
        part = payload[self.start:self.start + self.size]
        return int.from_bytes(part, "big" if self.order == "BE" else "little") if len(part) == self.size else None


@dataclass
class Info:
    stream: Stream
    period: float | None = None      # median, seconds
    spread: tuple[float, float] = (0.0, 0.0)
    cyclic: bool = False
    max_gap: float = 0.0
    bytes: list[ByteInfo] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    changes: list[tuple[float, list[tuple[int, int | None, int | None]]]] = field(default_factory=list)
    n_changes: int = 0

    @property
    def n(self) -> int:
        return len(self.stream.times)

    @property
    def pattern(self) -> str:
        return "".join({"const": ".", "counter": "Z", "nibble_lo": "z", "nibble_hi": "z", "check": "P",
                        "flags": "F", "signal": "S"}[b.kind] for b in self.bytes)

    @property
    def interesting(self) -> bool:
        return any(b.kind in ("flags", "signal") for b in self.bytes)


def _counts_up(values: list[int], modulo: int) -> bool:
    if len(values) < 8 or len(set(values)) < min(8, modulo // 2):
        return False
    steps = Counter((b - a) % modulo for a, b in zip(values, values[1:], strict=False))
    step, hits = steps.most_common(1)[0]
    return step != 0 and hits >= 0.9 * (len(values) - 1)


def _carries(hi: list[int], lo: list[int]) -> bool:
    """Does `hi` step by one exactly when `lo` wraps around? Then they are one 16-bit number."""
    events = hits = 0
    for k in range(len(hi) - 1):
        dh, dl = hi[k + 1] - hi[k], lo[k + 1] - lo[k]
        if dh in (1, -1):
            events += 1
            hits += (dh == 1 and dl < -64) or (dh == -1 and dl > 64)
    return events >= 2 and hits >= 0.75 * events


def _xor(p: bytes) -> int:
    x = 0
    for v in p:
        x ^= v
    return x


def analyse_stream(s: Stream, keep_changes: int = 400) -> Info:
    info = Info(s)
    if len(s.times) >= 3:
        gaps = sorted(b - a for a, b in zip(s.times, s.times[1:], strict=False))
        info.period = gaps[len(gaps) // 2]
        info.spread = (gaps[len(gaps) // 10], gaps[len(gaps) * 9 // 10])
        info.cyclic = info.period > 0 and info.spread[0] >= 0.5 * info.period and info.spread[1] <= 1.5 * info.period
        info.max_gap = gaps[-1]
    width = max((len(p) for p in s.payloads), default=0)
    cols = [[p[i] for p in s.payloads if len(p) > i] for i in range(width)]
    for col in cols:
        values = set(col)
        mask = changes = 0
        for a, b in zip(col, col[1:], strict=False):
            if a != b:
                mask |= a ^ b
                changes += 1
        if len(values) == 1:
            kind = "const"
        elif _counts_up(col, 256):
            kind = "counter"
        elif _counts_up([v & 0x0F for v in col], 16):
            kind = "nibble_lo"
        elif _counts_up([v >> 4 for v in col], 16):
            kind = "nibble_hi"
        else:
            kind = "flags" if len(values) <= 4 else "signal"
        info.bytes.append(ByteInfo(kind, values, mask, changes))
    # neighbours that carry into each other form 16/24/32-bit numbers
    full = [p for p in s.payloads if len(p) == width]
    joined: dict[int, str] = {}
    for i in range(width - 1):
        if info.bytes[i].kind in ("flags", "signal") and info.bytes[i + 1].kind == "signal" or \
                info.bytes[i].kind == "signal" and info.bytes[i + 1].kind in ("flags", "signal"):
            a, b = [p[i] for p in full], [p[i + 1] for p in full]
            if _carries(a, b):
                joined[i] = "BE"
            elif _carries(b, a):
                joined[i] = "LE"
    i = 0
    while i < width:
        order = joined.get(i)
        if order:
            size = 2
            while joined.get(i + size - 1) == order and size < 4:
                size += 1
            f = Field(i, size, order)
            vals = [f.value(p) for p in full]
            f.lo, f.hi, f.distinct = min(vals), max(vals), len(set(vals))
            info.fields.append(f)
            for k in range(i, i + size):
                info.bytes[k].kind = "signal"
            i += size
        else:
            i += 1
    in_field = {k for f in info.fields for k in range(f.start, f.start + f.size)}
    # first or last byte that follows from the others: checksum
    for i in {0, width - 1} if width > 2 and len(full) >= 16 else ():
        b = info.bytes[i]
        if b.kind in ("flags", "signal") and i not in in_field:
            for name, fold in (("sum", lambda p, i=i: (p[i] - sum(p) + p[i]) & 0xFF),
                               ("XOR", lambda p: _xor(p))):
                if len({fold(p) for p in full}) == 1:
                    b.kind, b.text = "check", f"checksum ({name} of the other bytes, remainder {fold(full[0]):02X})"
                    break
    # a byte that jumps wildly with almost every message, at the edge or next to a counter: checksum
    for i, b in enumerate(info.bytes):
        col = cols[i]
        if b.kind != "signal" or i in in_field or len(col) < 16 or len(b.values) < min(48, len(col) // 3):
            continue
        near = i in (0, width - 1) or any(info.bytes[k].kind in ("counter", "nibble_lo", "nibble_hi")
                                          for k in (i - 1, i + 1) if 0 <= k < width)
        jumps = [min((y - x) % 256, (x - y) % 256) for x, y in zip(col, col[1:], strict=False) if x != y]
        if near and b.changes >= 0.8 * (len(col) - 1) and sum(jumps) / len(jumps) > 48:
            b.kind = "check"
    # when did the content change, apart from counters and checksums
    masks = [{"counter": 0, "check": 0, "nibble_lo": 0xF0, "nibble_hi": 0x0F}.get(b.kind, 0xFF) for b in info.bytes]
    prev = None
    for t, p in zip(s.times, s.payloads, strict=True):
        cur = [v & m for v, m in zip(p, masks, strict=False)]
        if prev is not None and cur != prev:
            info.n_changes += 1
            if len(info.changes) < keep_changes:
                n = max(len(cur), len(prev))
                info.changes.append((t, [(k, prev[k] if k < len(prev) else None, cur[k] if k < len(cur) else None)
                                         for k in range(n) if k >= len(prev) or k >= len(cur) or prev[k] != cur[k]]))
        prev = cur
    return info


# -- everything in a recording --------------------------------------------------------------------

def mask_vin(vin: str) -> str:
    """Keep maker, model and year, drop the serial number: enough to analyse, safer to pass on."""
    return vin[:11] + "…" if len(vin) == 17 else vin


def _mac(m: bytes | None) -> str:
    return m.hex(":") if m else "?"


@dataclass
class Flow:
    name: str = ""
    packets: list[int] = field(default_factory=lambda: [0, 0])   # to the server, from the server
    size: list[int] = field(default_factory=lambda: [0, 0])


class Analysis:
    def __init__(self, known: sniff.KnownIndex | None = None, bitrate: int = 500_000):
        self.sniffer = Sniffer(known)
        self.bitrate = bitrate
        self.source = ""
        self.notes: list[tuple[float, str]] = []
        self.first_t: float | None = None
        self.last_t = 0.0
        # CAN
        self.can: dict[tuple[int, bool], Stream] = {}
        self.can_frames = 0
        self.can_bits = 0
        self.can_fd = False
        # Ethernet
        self.streams: dict[str, Stream] = {}
        self.packets = 0
        self.size = 0
        self.ethertypes: Counter = Counter()
        self.vlans: dict[int, Counter] = {}
        self.nodes: dict[str, dict] = {}
        self.flows: dict[tuple, Flow] = {}
        self.facts: Counter = Counter()
        self.offers: dict[tuple, dict] = {}
        self.subscriptions: Counter = Counter()
        self._tcp = pcap.TcpStreams()
        self._buf: dict[tuple, bytes] = {}
        self._proto: dict[tuple, str] = {}

    def _time(self, t: float) -> None:
        self.first_t = t if self.first_t is None else min(self.first_t, t)
        self.last_t = max(self.last_t, t)

    @property
    def seconds(self) -> float:
        return self.last_t - self.first_t if self.first_t is not None else 0.0

    # -- CAN -------------------------------------------------------------------------------

    def can_frame(self, f: Frame) -> None:
        self._time(f.t)
        self.can_frames += 1
        self.can_bits += (67 if f.ext else 47) + 8 * len(f.data)
        self.can_fd = self.can_fd or len(f.data) > 8
        key = (f.id, f.ext)
        s = self.can.get(key)
        if s is None:
            s = self.can[key] = Stream(fmt_id(f.id, f.ext))
        s.add(f.t, f.data)
        self.sniffer.feed(f)

    # -- Ethernet --------------------------------------------------------------------------

    def packet(self, p: pcap.Packet) -> None:
        if p.can:
            self.can_frame(Frame(p.t, *p.can))
            return
        self._time(p.t)
        self.packets += 1
        self.size += p.length
        self.ethertypes[p.ethertype] += 1
        if p.vlan is not None:
            self.vlans.setdefault(p.vlan, Counter())[p.prio] += 1
        who = p.src or _mac(p.src_mac)
        node = self.nodes.setdefault(who, {"mac": set(), "packets": 0, "vlans": set()})
        node["packets"] += 1
        if p.src_mac:
            node["mac"].add(_mac(p.src_mac))
        if p.vlan is not None:
            node["vlans"].add(p.vlan)
        if p.src is None:
            if p.ethertype not in (0x0806, 0x0800, 0x86DD):
                name = ETHERTYPES.get(p.ethertype, f"EtherType {p.ethertype:04X}").split(" (")[0]
                self._stream(f"{name} {_mac(p.src_mac)} → {_mac(p.dst_mac)}").add(p.t, p.l2)
            return
        if p.sport is None:
            self._flow(p, (p.proto, p.src, 0, p.dst, 0), 0)
            return
        # the side with the well-known (or lower) port is the server
        to_server = (p.dport in PORTS, -p.dport) >= (p.sport in PORTS, -p.sport)
        key = (p.proto, p.src, p.sport, p.dst, p.dport) if to_server else (p.proto, p.dst, p.dport, p.src, p.sport)
        flow = self._flow(p, key, 0 if to_server else 1)
        port = p.dport if to_server else p.sport
        direction = (p.src, p.sport, p.dst, p.dport)
        if p.proto == "udp":
            self._udp(p, flow, port)
        elif p.proto == "tcp":
            data = self._tcp.add(p)
            if data:
                self._tcp_data(p, flow, port, direction, data)

    def _flow(self, p: pcap.Packet, key: tuple, way: int) -> Flow:
        flow = self.flows.get(key)
        if flow is None:
            flow = self.flows[key] = Flow(PORTS.get(key[4], ""))
        flow.packets[way] += 1
        flow.size[way] += p.length
        return flow

    def _stream(self, label: str, note: str = "") -> Stream:
        s = self.streams.get(label)
        if s is None:
            s = self.streams[label] = Stream(label, note)
        return s

    def _udp(self, p: pcap.Packet, flow: Flow, port: int) -> None:
        d = p.payload
        if port == 13400 and self._doip(p, d) is not None:
            return
        if port == 6811:
            at = d.find(b"BMWVIN")
            if at >= 0:
                self.facts[f"HSFZ: vehicle {p.src} announces itself, VIN {mask_vin(d[at + 6:at + 23].decode('ascii', 'replace'))}"] += 1
            else:
                self.facts[f"HSFZ: vehicle discovery from {p.src}"] += 1
            return
        if self._someip(p, d) == len(d) and d:
            flow.name = flow.name or "SOME/IP"
            return
        if port not in PORTS:
            self._stream(f"UDP {p.src}:{p.sport} → {p.dst}:{p.dport}").add(p.t, d)

    def _tcp_data(self, p: pcap.Packet, flow: Flow, port: int, direction: tuple, data: bytes) -> None:
        buf = self._buf.get(direction, b"") + data
        proto = self._proto.get(direction)
        if proto is None:  # decide on the first bytes of each direction
            if port == 6801:
                proto = "hsfz"
            elif port == 13400:
                proto = "doip"
            elif buf[:1] == b"\x16" and buf[1:2] == b"\x03":
                proto, flow.name = "other", "TLS (encrypted)"
            elif len(buf) >= 16 and _someip_header(buf) is not None:
                proto, flow.name = "someip", flow.name or "SOME/IP"
            else:
                proto = "other"
            self._proto[direction] = proto
        if proto == "other":
            return
        while True:
            used = None
            if proto == "hsfz" and len(buf) >= 6:
                length, ctrl = struct.unpack(">IH", buf[:6])
                if length > 1 << 20:
                    proto = self._proto[direction] = "other"
                    break
                if len(buf) >= 6 + length:
                    used, body = 6 + length, buf[6:6 + length]
                    if ctrl == 0x0001 and len(body) >= 3:
                        from .enet_sniff import hsfz_frames
                        for f in hsfz_frames(p.t, body[0], body[1], body[2:], p.dport == 6801):
                            self.sniffer.feed(f)
            elif proto == "doip" and len(buf) >= 8:
                length = int.from_bytes(buf[4:8], "big")
                if buf[0] ^ buf[1] != 0xFF or length > 1 << 20:
                    proto = self._proto[direction] = "other"
                    break
                if len(buf) >= 8 + length:
                    used = self._doip(p, buf[:8 + length])
            elif proto == "someip" and len(buf) >= 16:
                used = self._someip(p, buf, partial=True) or None
            if not used:
                break
            buf = buf[used:]
        self._buf[direction] = buf if proto != "other" else b""

    def _doip(self, p: pcap.Packet, d: bytes) -> int | None:
        """One DoIP message at the start of `d`; returns its length."""
        if len(d) < 8 or d[0] ^ d[1] != 0xFF:
            return None
        kind, length = struct.unpack(">HI", d[2:8])
        body = d[8:8 + length]
        if kind == 0x8001 and len(body) > 4:
            src, dst = struct.unpack(">HH", body[:4])
            self.sniffer.feed_message(p.t, src, dst, body[4:], functional=0xE000 <= dst <= 0xEFFF)
        elif kind == 0x0004 and len(body) >= 19:
            self.facts[f"DoIP: vehicle {p.src} announces itself, VIN {mask_vin(body[:17].decode('ascii', 'replace'))}, address {body[17:19].hex().upper()}"] += 1
        elif kind in DOIP_TYPES:
            self.facts[f"DoIP: {DOIP_TYPES[kind]} from {p.src}"] += 1
        elif kind == 0x0005 and len(body) >= 3:
            self.facts[f"DoIP: tester {body[:2].hex().upper()} ({p.src}) activates routing, type {body[2]:02X}"] += 1
        elif kind == 0x0006 and len(body) >= 5:
            ok = "accepted" if body[4] == 0x10 else f"refused/other (code {body[4]:02X})"
            self.facts[f"DoIP: gateway {body[2:4].hex().upper()} ({p.src}): routing {ok}"] += 1
        elif kind == 0x8003 and len(body) >= 5:
            self.facts[f"DoIP: diagnostic message refused by {p.src} (code {body[4]:02X})"] += 1
        return 8 + length

    def _someip(self, p: pcap.Packet, d: bytes, partial: bool = False) -> int:
        """Bytes of `d` that are complete SOME/IP messages (0 if it is something else)."""
        pos = 0
        while len(d) - pos >= 16:
            h = _someip_header(d[pos:])
            if h is None:
                return 0
            service, method, length, mtype = h
            if pos + 8 + length > len(d):
                if partial:
                    break
                return 0
            body = d[pos + 16:pos + 8 + length]
            if (service, method) == (0xFFFF, 0x8100):
                self._someip_sd(p, body)
            else:
                kind = SOMEIP_TYPES.get(mtype & 0xDF, f"Typ {mtype:02X}") + (" (TP-Segment)" if mtype & 0x20 else "")
                s = self._stream(f"SOME/IP {service:04X}.{method:04X} {kind}")
                way = f"{p.src}:{p.sport} → {p.dst}:{p.dport} ({p.proto.upper()})"
                if way not in s.note and s.note.count(";") < 2:
                    s.note = f"{s.note}; {way}" if s.note else way
                s.add(p.t, body)
            pos += 8 + length
        return pos if partial or pos == len(d) else 0

    def _someip_sd(self, p: pcap.Packet, d: bytes) -> None:
        if len(d) < 12:
            return
        n = int.from_bytes(d[4:8], "big")
        entries, rest = d[8:8 + n], d[8 + n:]
        options = []
        pos, end = 4, 4 + int.from_bytes(rest[:4], "big") if len(rest) >= 4 else 0
        while pos + 3 <= min(end, len(rest)):
            size, kind = int.from_bytes(rest[pos:pos + 2], "big"), rest[pos + 2]
            o = rest[pos + 4:pos + 3 + size]
            text = None
            if kind in (0x04, 0x14) and len(o) >= 8:  # IPv4 endpoint / multicast
                text = f"{'.'.join(str(b) for b in o[:4])}:{int.from_bytes(o[6:8], 'big')}/{'tcp' if o[5] == 6 else 'udp'}"
            options.append(text)
            pos += 3 + size
        for k in range(0, len(entries) - 15, 16):
            e = entries[k:k + 16]
            kind, i1, i2, counts = e[0], e[1], e[2], e[3]
            service, instance = struct.unpack(">HH", e[4:8])
            major, ttl = e[8], int.from_bytes(e[9:12], "big")
            refs = options[i1:i1 + (counts >> 4)] + options[i2:i2 + (counts & 0x0F)]
            ends = {o for o in refs if o}
            if kind == 0x01:
                offer = self.offers.setdefault((p.src, service, instance), {"version": "", "ends": set(), "n": 0,
                                                                            "stopped": False})
                offer["version"] = f"{major}.{int.from_bytes(e[12:16], 'big')}"
                offer["ends"] |= ends
                offer["n"] += 1
                offer["stopped"] = ttl == 0
            elif kind == 0x00:
                self.facts[f"SOME/IP-SD: {p.src} looks for service {service:04X}"] += 1
            elif kind in (0x06, 0x07):
                what = "subscribes" if kind == 0x06 else ("confirms subscription" if ttl else "refuses subscription")
                if kind == 0x06 and ttl == 0:
                    what = "ends subscription"
                group = int.from_bytes(e[14:16], "big")
                self.subscriptions[(p.src, p.dst, what, service, instance, group)] += 1

    # -- results ---------------------------------------------------------------------------

    def finish(self) -> None:
        self.sniffer.tick(float("inf"))

    def broadcast(self) -> list[tuple[tuple[int, bool], Stream]]:
        others = self.sniffer.broadcast_ids()
        return [(k, s) for k, s in sorted(self.can.items(), key=lambda kv: (kv[0][1], kv[0][0])) if k in others]


def _someip_header(d: bytes) -> tuple[int, int, int, int] | None:
    service, method, length = struct.unpack(">HHI", d[:8])
    if d[12] != 0x01 or length < 8 or length > 1 << 20 or d[14] & 0xDF not in SOMEIP_TYPES:
        return None
    return service, method, length, d[14]


def load(path: str, known: sniff.KnownIndex | None = None, bitrate: int = 500_000) -> Analysis:
    """CAN logs (everything `evsoc sniff -d` reads) and Ethernet/CAN recordings as pcap or pcapng."""
    a = Analysis(known, bitrate)
    a.source = Path(path).name
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic in (b"\x0a\x0d\x0d\x0a", b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        for p in pcap.read_packets(path):
            a.packet(p)
        a.notes = sniff.read_notes(path + ".notes") or sniff.read_notes(path + ".notizen")
    else:
        frames, markers = sniff.read_log(path)
        for f in frames:
            a.can_frame(f)
        a.sniffer.markers += markers
        a.notes = sniff.read_notes(path)
    a.finish()
    return a


# -- report ----------------------------------------------------------------------------------------

def _ms(seconds: float) -> str:
    ms = seconds * 1000
    return f"{ms:.0f}" if ms >= 10 else f"{ms:.1f}"


def _timing(info: Info) -> str:
    if info.period is None:
        return "-"
    if info.cyclic:
        return f"{_ms(info.period)} ms"
    return f"irregular, mostly {_ms(info.period)} ms ({_ms(info.spread[0])}–{_ms(info.spread[1])})"


def _sizes(s: Stream) -> str:
    sizes = sorted(s.sizes)
    return str(sizes[0]) if len(sizes) == 1 else f"{sizes[0]}–{sizes[-1]}"


def _hex(p: bytes, limit: int = 24) -> str:
    return p[:limit].hex(" ").upper() + (" …" if len(p) > limit else "")


def _describe_bytes(info: Info) -> list[str]:
    out, i, width = [], 0, len(info.bytes)
    starts = {f.start: f for f in info.fields}
    while i < width:
        b, name = info.bytes[i], letters(i)
        if i in starts:
            f = starts[i]
            out.append(f"{name}–{letters(i + f.size - 1)} number {f.size * 8} bit {f.order} {f.lo}–{f.hi} ({f.distinct} values)")
            i += f.size
            continue
        if b.kind == "const":
            j = i
            while j + 1 < width and info.bytes[j + 1].kind == "const" and j + 1 not in starts:
                j += 1
            vals = " ".join(f"{next(iter(info.bytes[k].values)):02X}" for k in range(i, min(j, i + 7) + 1))
            out.append(f"{name}{'–' + letters(j) if j > i else ''} constant {vals}{' …' if j > i + 7 else ''}")
            i = j + 1
            continue
        if b.kind == "counter":
            out.append(f"{name} counter")
        elif b.kind in ("nibble_lo", "nibble_hi"):
            low = b.kind == "nibble_lo"
            other = sorted({v >> 4 if low else v & 0x0F for v in b.values})
            rest = f"constant {other[0]:X}" if len(other) == 1 else "Values " + ",".join(f"{v:X}" for v in other)
            out.append(f"{name} counter in the {'unteren' if low else 'oberen'} nibble ({'oberes' if low else 'unteres'}: {rest})")
        elif b.kind == "check":
            out.append(f"{name} {b.text or 'checksum?'}")
        elif b.kind == "flags":
            out.append(f"{name} state {{{','.join(f'{v:02X}' for v in sorted(b.values))}}} ({b.changes} changes)")
        else:
            out.append(f"{name} signal {min(b.values)}–{max(b.values)} ({len(b.values)} values, bits {b.mask:02X})")
        i += 1
    return out


def _samples(info: Info, points: int) -> list[int]:
    n = info.n
    if n <= points:
        return list(range(n))
    t0, t1 = info.stream.times[0], info.stream.times[-1]
    picked = [max(0, bisect.bisect_right(info.stream.times, t0 + (t1 - t0) * k / (points - 1)) - 1) for k in range(points)]
    return sorted(set(picked))


def detail(info: Info, t0: float, heading: str, points: int = 12, max_changes: int = 12) -> list[str]:
    s = info.stream
    out = [f"### {heading}", "",
           f"{info.n}×, interval {_timing(info)}, {_sizes(s)} bytes"
           + (f", +{s.times[0] - t0:.1f} to +{s.times[-1] - t0:.1f} s" if s.times else "")
           + (f", longest gap {info.max_gap:.1f} s" if info.period and info.max_gap > max(1.0, 10 * info.period) else "")]
    if s.note:
        out.append(s.note)
    if max(s.sizes, default=0) > MAX_BYTES:
        out.append(f"Only the first {MAX_BYTES} bytes evaluated.")
    out += ["", "Bytes: " + "; ".join(_describe_bytes(info)), ""]
    width = len(info.bytes)
    shown = [i for i in range(width) if info.bytes[i].kind != "const"] if width > 16 else list(range(width))
    if shown and info.n > 1:
        head = " ".join(f"{letters(i):>2}" for i in shown)
        fields = "".join(f"  {letters(f.start) + '–' + letters(f.start + f.size - 1):>8}" for f in info.fields)
        out += ["```", f"{'t [s]':>8}  {head}{fields}" + ("   (constant bytes left out)" if len(shown) < width else "")]
        for k in _samples(info, points):
            p = s.payloads[k]
            row = " ".join(f"{p[i]:02X}" if i < len(p) else "  " for i in shown)
            vals = "".join(f"  {v if (v := f.value(p)) is not None else '':>8}" for f in info.fields)
            out.append(f"{s.times[k] - t0:8.2f}  {row}{vals}")
        out.append("```")
    if 0 < info.n_changes <= max_changes:
        out.append(f"All {info.n_changes} changes (without counter/checksum):")
        for t, diff in info.changes:
            out.append(f"- +{t - t0:.2f} s  " + ", ".join(
                f"{letters(i)} {'--' if a is None else f'{a:02X}'}→{'--' if b is None else f'{b:02X}'}" for i, a, b in diff[:12])
                + (" …" if len(diff) > 12 else ""))
    elif info.n_changes:
        out.append(f"{info.n_changes} changes (without counter/checksum), first +{info.changes[0][0] - t0:.2f} s. Individually with --id.")
    out.append("")
    return out


def _matches(wanted: list[str], *names: str) -> bool:
    """'3d2' finds CAN id 3D2, '22D410' the request, longer text any stream that contains it."""
    flat = [n.replace(" ", "").upper() for n in names]
    for w in wanted:
        w = w.replace(" ", "").upper()
        if any(w == n or w.lstrip("0") == n.lstrip("0") or (len(w) >= 4 and w in n) for n in flat):
            return True
    return False


def report(a: Analysis, ids: list[str] | None = None, points: int = 12, max_streams: int = 60) -> str:
    """Markdown. With `ids` only these CAN ids/requests/streams, but in full length."""
    t0 = a.first_t or 0.0
    focus = bool(ids)
    if focus:
        points, max_changes, max_streams = max(points, 40), 400, 10_000
    else:
        max_changes = 12
    out = [f"# evsoc analysis: {a.source}", "",
           "Summary of a complete capture, to hand to an assistant. "
           "Times in seconds since the start. Bytes are called A, B, C … (A = first data byte), contents hex, "
           "value ranges decimal. Pattern per byte: `.` constant, `Z` counter, `z` counter in a nibble, "
           "`P` checksum?, `F` state (at most 4 values), `S` signal.", ""]
    if a.first_t is None:
        return "\n".join(out + ["The capture contains no frames."]) + "\n"
    out += [f"- Start {clock(t0)}, duration {a.seconds:.1f} s"]
    if a.can_frames:
        n29 = sum(1 for _, ext in a.can if ext)
        load_ = f", bus load about {min(100.0, a.can_bits * 1.1 / (a.seconds * a.bitrate) * 100):.0f} % at {a.bitrate // 1000} kbit/s" if a.seconds > 0 and not a.can_fd else ""
        out.append(f"- CAN: {a.can_frames} frames ({a.can_frames / max(a.seconds, 1e-9):.0f}/s), {len(a.can)} IDs ({len(a.can) - n29}× 11 bit, {n29}× 29 bit){', CAN FD' if a.can_fd else ''}{load_}")
    if a.packets:
        out.append(f"- Ethernet: {a.packets} packets, {a.size / 1e6:.2f} MB, {len(a.nodes)} senders, {len(a.flows)} connections")
    out.append("")

    if a.notes or a.sniffer.markers:
        out += ["## Notes during the recording", ""]
        events = [(t, text) for t, text in a.notes] + \
                 [(m.t, f"value read off {m.name} = {m.value:g}") for m in a.sniffer.markers if m.t is not None]
        out += [f"- +{t - t0:.1f} s ({clock(t)})  {text}" for t, text in sorted(events)]
        out += [f"- (no time)  value read off {m.name} = {m.value:g}" for m in a.sniffer.markers if m.t is None]
        out.append("")

    if a.packets and not focus:
        out += _ethernet(a)

    body = len(out)
    # diagnostics (CAN ISO-TP, HSFZ, DoIP)
    convs = a.sniffer.conversations
    details: list[list[str]] = []
    if convs:
        rows = []
        for c in convs:
            if focus and not _matches(ids, c.label, c.request.hex()):
                continue
            vin = c.request.hex() in ("22f190", "0902")  # the report is meant to be passed on
            if c.answers:
                status = f"known: {c.known_summary()}" if c.known else "new to evsoc"
                last = "(vehicle identification number, hidden)" if vin else _hex(c.answers[-1].data, 32)
            elif c.nrc:
                status = "refused: " + ", ".join(f"NRC {k:02X} {_NRC.get(k, '')}".strip() for k in c.nrc)
                last = ""
            else:
                status, last = "no answer", ""
            warn = " **not a read command**" if c.writes else ""
            rows.append(f"| {c.label} | {c.service}{warn} | {c.count} | {len(c.answers)} | {status} | {last} |")
            if c.answers and not vin and (focus or (len(c.answers) > 1 and c.varying and c.request[0] in sniff.READ_SIDS)):
                s = Stream(c.label)
                for ans in c.answers:
                    s.add(ans.t, ans.data)
                details.append(detail(analyse_stream(s), t0, f"response to {c.label}", points, max_changes))
        if rows:
            out += ["## Diagnostics (requests of a tester and responses)", "",
                    "Byte A is the first byte after the repeated request header, as in the evsoc formulas.", "",
                    "| Request | Service | Requests | Responses | Status | last response (data) |", "|---|---|---|---|---|---|"]
            out += rows + [""]
            for d in details[:max_streams]:
                out += d
            if len(details) > max_streams:
                out += [f"{len(details) - max_streams} more responses with changing bytes not shown individually.", ""]
    elif a.can_frames and not focus:
        out += ["## Diagnostics", "", "No diagnostic requests in the capture (no tester active).", ""]

    # CAN broadcast
    infos = [(k, analyse_stream(s)) for k, s in a.broadcast()]
    if focus:
        infos = [(k, i) for k, i in infos if _matches(ids, i.stream.label)]
    if infos:
        if not focus:
            shown_keys = {k for k, _ in infos}
            diag = sorted(fmt_id(*k) for k in a.can if k not in shown_keys)
            out += ["## CAN frames (broadcast)", ""]
            if diag:
                out += [f"Diagnostic IDs (evaluated above, not here): {', '.join(diag)}", ""]
            out += ["| ID | Count | Interval | Bytes | Pattern | last |", "|---|---|---|---|---|---|"]
            out += [f"| {i.stream.label} | {i.n} | {_timing(i)} | {_sizes(i.stream)} | `{i.pattern}` | {_hex(i.stream.payloads[-1], 16)} |"
                    for _, i in infos]
            out.append("")
        shown = [i for _, i in infos if focus or i.interesting]
        for i in shown[:max_streams]:
            out += detail(i, t0, f"CAN {i.stream.label}", points, max_changes)
        if len(shown) > max_streams:
            out += [f"{len(shown) - max_streams} more IDs with signals not shown individually: "
                    + ", ".join(i.stream.label for i in shown[max_streams:]) + ". Individually with --id.", ""]

    # other Ethernet streams
    streams = sorted(a.streams.values(), key=lambda s: -len(s.times))
    if focus:
        streams = [s for s in streams if _matches(ids, s.label)]
    if streams:
        infos2 = [analyse_stream(s) for s in streams]
        if not focus:
            out += ["## Ethernet streams (SOME/IP, other UDP, layer 2)", "",
                    "| Stream | Count | Interval | Bytes | Pattern | last |", "|---|---|---|---|---|---|"]
            out += [f"| {i.stream.label} | {i.n} | {_timing(i)} | {_sizes(i.stream)} | `{i.pattern[:32]}` | {_hex(i.stream.payloads[-1], 12)} |"
                    for i in infos2[:200]]
            out.append("")
        shown = [i for i in infos2 if focus or i.interesting]
        for i in shown[:max_streams]:
            out += detail(i, t0, i.stream.label, points, max_changes)
        if len(shown) > max_streams:
            out += [f"{len(shown) - max_streams} more streams not shown individually. Individually with --id \"name\".", ""]
    if focus and len(out) == body:
        out.append("Nothing found for: " + ", ".join(ids))
    return "\n".join(out).rstrip() + "\n"


def _ethernet(a: Analysis) -> list[str]:
    out = ["## Ethernet: participants and connections", "", "| Sender | MAC | VLAN | Packets |", "|---|---|---|---|"]
    for who, n in sorted(a.nodes.items(), key=lambda kv: -kv[1]["packets"])[:40]:
        macs = ", ".join(sorted(n["mac"] - {who})) or "-"
        out.append(f"| {who} | {macs} | {', '.join(str(v) for v in sorted(n['vlans'])) or '-'} | {n['packets']} |")
    out.append("")
    if a.vlans:
        out += ["VLANs: " + "; ".join(f"{v} ({sum(c.values())} packets, priority {', '.join(str(p) for p in sorted(c))})"
                                      for v, c in sorted(a.vlans.items())), ""]
    out += ["Protocols (EtherType): " + ", ".join(
        f"{ETHERTYPES.get(e, f'{e:04X}' if e is not None else '?')} {n}" for e, n in a.ethertypes.most_common()), ""]
    if a.flows:
        out += ["| Connection (client ⇄ server) | Kind | Packets out/back | Bytes out/back |", "|---|---|---|---|"]
        flows = sorted(a.flows.items(), key=lambda kv: -sum(kv[1].packets))
        for (proto, src, sport, dst, dport), f in flows[:40]:
            ends = f"{src}:{sport} ⇄ {dst}:{dport}" if sport or dport else f"{src} → {dst}"
            out.append(f"| {ends} | {proto.upper()} {f.name} | {f.packets[0]}/{f.packets[1]} | {f.size[0]}/{f.size[1]} |")
        if len(flows) > 40:
            out.append(f"| … {len(flows) - 40} more | | | |")
        out.append("")
    if a.facts:
        out += ["Seen:", ""] + [f"- {text}" + (f" ({n}×)" if n > 1 else "") for text, n in a.facts.items()] + [""]
    if a.offers:
        out += ["SOME/IP services (from service discovery):", "",
                "| Service | Instance | Version | Provider | Endpoints | Offers |", "|---|---|---|---|---|---|"]
        for (src, service, instance), o in sorted(a.offers.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            out.append(f"| {service:04X} | {instance:04X} | {o['version']} | {src} | {', '.join(sorted(o['ends'])) or '-'} | "
                       f"{o['n']}{' (last: unsubscribed)' if o['stopped'] else ''} |")
        out.append("")
    if a.subscriptions:
        out += ["SOME/IP-Abos:", ""]
        out += [f"- {src} {what} at {dst}: service {service:04X}, instance {instance:04X}, event group {group:04X} ({n}×)"
                for (src, dst, what, service, instance, group), n in a.subscriptions.items()]
        out.append("")
    return out
