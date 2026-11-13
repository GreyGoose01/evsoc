"""Listen in on other OBD apps through a Y cable and learn what they ask the car.

    car ── Y cable ──┬── adapter + app (Car Scanner, BimmerLink, Leaf Spy, ...)
                     └── second adapter for evsoc: CAN interface (listen-only)
                         or ELM327/OBDLink/evsoc box in monitor mode (ATMA)

evsoc transmits nothing here. It reassembles ISO-TP in both directions, pairs
every request of the app with the ECU's answer, says which of them the
profiles already know (and decodes them), and searches formulas for values
read off the app ("soc 80.5"). The result can become a new evsoc profile.
"""

from __future__ import annotations

import json
import math
import queue
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .broadcast import Recorder
from .decoders import Response
from .elm import _NRC, AdapterError, at_family
from .equation import Equation, EquationError
from .profiles import Profile, Step, parse_profile
from .safety import SafetyError, check_request, decode_request

Log = Callable[[str], None]

FUNCTIONAL = {0x7DF, 0x18DB33F1}
REQUEST_SIDS = {0x01, 0x02, 0x03, 0x04, 0x06, 0x07, 0x09, 0x0A, 0x10, 0x11, 0x14, 0x19, 0x1A, 0x21, 0x22, 0x23,
                0x27, 0x28, 0x2C, 0x2E, 0x2F, 0x31, 0x34, 0x35, 0x36, 0x37, 0x3B, 0x3D, 0x3E, 0x85}
SERVICES = {
    0x01: "OBD current data", 0x02: "OBD freeze frame", 0x03: "OBD read faults", 0x04: "OBD CLEAR faults",
    0x09: "OBD vehicle info", 0x10: "session", 0x11: "control unit RESET", 0x14: "CLEAR fault memory",
    0x19: "read fault memory", 0x1A: "KWP identification", 0x21: "KWP read", 0x22: "UDS read", 0x23: "read memory",
    0x27: "security access", 0x28: "communication control", 0x2E: "UDS WRITE", 0x2F: "actuator control",
    0x31: "routine", 0x34: "download", 0x36: "data transfer", 0x3B: "KWP WRITE", 0x3E: "TesterPresent",
    0x85: "fault memory control",
}
READ_SIDS = {0x01, 0x09, 0x1A, 0x21, 0x22}
PENDING_WINDOW = 3.0


@dataclass
class Frame:
    t: float
    id: int
    ext: bool
    data: bytes


def fmt_id(can_id: int, ext: bool) -> str:
    return f"{can_id:08X}" if ext else f"{can_id:03X}"


def clock(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


def letters(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA (byte names of the equation syntax)."""
    name, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(ord("A") + r) + name
    return name


def _related(tx: int, rx: int, ext: bool) -> bool:
    if not ext:
        return rx == tx + 8 or (tx == 0x7DF and 0x7E8 <= rx <= 0x7EF)
    return (rx >> 16) & 0xFF == (tx >> 16) & 0xFF and (rx & 0xFF, (rx >> 8) & 0xFF) == ((tx >> 8) & 0xFF, tx & 0xFF) \
        or (tx == 0x18DB33F1 and (rx >> 8) & 0xFFFF == 0xDAF1)


def _echo(req: bytes) -> int:
    """Bytes of the request a positive answer repeats (SID counted)."""
    return min(len(req), {0x22: 3, 0x2E: 3, 0x31: 4}.get(req[0], 2))


# -- what the profiles already know ------------------------------------------------

Key = tuple[int, bool, "int | None", bytes]  # request id, 29 bit, extended address, request bytes


def step_key(profile: Profile, step: Step) -> Key | None:
    """CAN id, addressing and request bytes a profile step puts on the bus."""
    if not step.request:
        return None
    ext, header, prio, target, caf, user_pb = False, None, 0x18, None, True, None
    for cmd in profile.init + step.at:
        c = cmd.replace(" ", "").upper()
        if c in ("ATZ", "ATD", "ATWS"):
            ext, header, prio, target, caf = False, None, 0x18, None, True
            continue
        fam = at_family(c)
        arg = c[2 + len(fam):] if fam else ""
        if fam == "SP":
            a = arg.lstrip("A")
            if a in ("6", "8"):
                ext = False
            elif a in ("7", "9"):
                ext = True
            elif a in ("B", "C") and user_pb is not None:
                ext = user_pb
        elif fam == "PB" and len(arg) >= 2:
            user_pb = not int(arg[:2], 16) & 0x80
        elif fam == "SH":
            header = arg
            ext = ext or len(arg) == 8
        elif fam == "CP" and arg:
            prio = int(arg, 16)
        elif fam == "CEA":
            target = int(arg, 16) if arg else None
        elif fam == "CAF":
            caf = arg.endswith("1")
    try:
        req = decode_request(step.request, caf)
        if ext:
            h = header or "DB33F1"
            tx = int(h, 16) if len(h) == 8 else (prio << 24) | (int(h, 16) & 0xFFFFFF)
        else:
            tx = int(header or "7DF", 16) & 0x7FF
    except (SafetyError, ValueError):
        return None
    return tx, ext, target, req


class KnownIndex:
    def __init__(self, profiles: dict[str, Profile]):
        self._by_key: dict[Key, list[tuple[Profile, Step]]] = {}
        for p in profiles.values():
            for step in p.steps.values():
                key = step_key(p, step)
                if key:
                    self._by_key.setdefault(key, []).append((p, step))

    def lookup(self, key: Key) -> list[tuple[Profile, Step]]:
        return self._by_key.get(key, [])


@dataclass
class KnownValue:
    profile: str
    field: str
    value: float | None
    unit: str
    plausible: bool


# -- conversations -------------------------------------------------------------------

@dataclass
class Answer:
    t: float
    ecu: int
    payload: bytes   # complete UDS answer
    data: bytes      # after SID + echo, i.e. byte A of the equations
    raw: bytes       # all CAN data bytes of the frames (WiCAN indexing)


@dataclass
class Conversation:
    tx: int
    ext: bool
    target: int | None
    request: bytes
    first: float
    last: float = 0.0
    count: int = 0
    unanswered: int = 0
    nrc: Counter = field(default_factory=Counter)
    answers: list[Answer] = field(default_factory=list)
    ecus: Counter = field(default_factory=Counter)
    fc: tuple[int, bytes] | None = None   # flow control the app's adapter sent: (CAN id, frame data)
    varying: set[int] = field(default_factory=set)
    changed: set[int] = field(default_factory=set)  # bytes that changed with the last answer
    known: list[tuple[Profile, Step]] = field(default_factory=list)
    session: bytes | None = None   # session change (10 xx) the app sent to this ECU before reading
    announced: bool = False

    @property
    def key(self) -> Key:
        return self.tx, self.ext, self.target, self.request

    @property
    def ecu(self) -> int | None:
        return self.ecus.most_common(1)[0][0] if self.ecus else None

    @property
    def service(self) -> str:
        return SERVICES.get(self.request[0], f"service {self.request[0]:02X}")

    @property
    def writes(self) -> bool:
        try:
            check_request(self.request)
            return False
        except SafetyError:
            return True

    @property
    def label(self) -> str:
        ecu = fmt_id(self.ecu, self.ext) if self.ecu is not None else "?"
        target = f"[{self.target:02X}]" if self.target is not None else ""
        return f"{fmt_id(self.tx, self.ext)}{target} → {ecu}  {self.request.hex(' ').upper()}"

    @property
    def rate(self) -> float:
        span = self.last - self.first
        return (self.count - 1) / span if span > 0 and self.count > 1 else 0.0

    def add(self, answer: Answer) -> None:
        prev = self.answers[-1].data if self.answers else None
        self.answers.append(answer)
        self.ecus[answer.ecu] += 1
        self.changed = set()
        if prev is not None:
            self.changed = {i for i in range(max(len(prev), len(answer.data)))
                            if i >= len(prev) or i >= len(answer.data) or prev[i] != answer.data[i]}
            self.varying |= self.changed

    def known_values(self, answer: Answer | None = None) -> list[KnownValue]:
        answer = answer or (self.answers[-1] if self.answers else None)
        if answer is None:
            return []
        out = []
        for profile, step in self.known:
            for f in profile.fields.values():
                if f.step != step.id:
                    continue
                try:
                    v = f.decoder(Response(answer.data, answer.raw))
                except (EquationError, ValueError, IndexError, ZeroDivisionError):
                    v = None
                out.append(KnownValue(profile.name, f.name, v, f.unit, v is not None and f.in_range(v)))
        return out

    def known_summary(self, limit: int = 2) -> str:
        values = self.known_values()
        by_profile: dict[str, list[KnownValue]] = {}
        for v in values:
            by_profile.setdefault(v.profile, []).append(v)
        ranked = sorted(by_profile.items(), key=lambda kv: (-sum(v.plausible for v in kv[1]), _rank_name(kv[0])))
        parts = []
        for name, vals in ranked[:limit]:
            shown = ", ".join(f"{v.field} {v.value:.4g} {v.unit}".strip() for v in vals if v.plausible)
            parts.append(f"{name} ({shown or 'nothing plausible'})")
        more = f" +{len(ranked) - limit} more" if len(ranked) > limit else ""
        return "; ".join(parts) + more


def _rank_name(name: str) -> int:
    return {"evsoc": 0, "obdb": 1, "abrp": 2, "wican": 3}.get(name.split("_", 1)[0], 4)


@dataclass
class Marker:
    name: str
    value: float
    t: float | None = None     # None: compare with the last answer
    tol: float | None = None   # resolution of the noted value, e.g. 0.01 for "79.96"


@dataclass
class _Partial:
    expected: int
    buf: bytearray
    raw: list[bytes]
    seq: int
    t: float
    target: int | None


@dataclass
class _Message:
    t: float
    id: int
    ext: bool
    target: int | None
    payload: bytes
    raw: bytes
    peer: int | None = None   # only this sender may answer (DoIP: logical address of the ECU)


@dataclass
class _Pending:
    msg: _Message
    deadline: float
    answered: bool = False


@dataclass
class IdStats:
    count: int = 0
    first: float = 0.0
    last: float = 0.0
    data: bytes = b""
    varying: set[int] = field(default_factory=set)


class Sniffer:
    """Feed CAN frames in, get the diagnostic conversations of other testers out."""

    def __init__(self, known: KnownIndex | None = None):
        self.known = known
        self.convs: dict[Key, Conversation] = {}
        self.ids: dict[tuple[int, bool], IdStats] = {}
        self.markers: list[Marker] = []
        self.recorder = Recorder()   # every frame by id, for the search in broadcast frames (broadcast.py)
        self.frames = 0
        self.first_t: float | None = None
        self.last_t: float | None = None
        self._partial: dict[tuple[int, bool], _Partial] = {}
        self._pending: list[_Pending] = []
        self._fc: dict[tuple[int, bool], tuple[int, bytes]] = {}  # sender of a multi-frame -> FC seen
        self._diag: set[tuple[int, bool]] = set()
        self._bmw = False
        self._sessions: dict[tuple[int, bool, int | None], bytes] = {}  # last accepted 10 xx per ECU

    # -- input -------------------------------------------------------------------------

    def feed(self, f: Frame) -> list[tuple[str, Conversation]]:
        self.frames += 1
        self.recorder.feed(f)
        self.first_t = f.t if self.first_t is None else self.first_t
        self.last_t = f.t
        st = self.ids.setdefault((f.id, f.ext), IdStats(first=f.t))
        if st.count and st.data != f.data:
            st.varying |= {i for i in range(max(len(st.data), len(f.data)))
                           if i >= len(st.data) or i >= len(f.data) or st.data[i] != f.data[i]}
        st.count, st.last, st.data = st.count + 1, f.t, f.data
        events = self.tick(f.t)
        msg = self._isotp(f)
        if msg is not None:
            events += self._message(msg)
        return events

    def feed_message(self, t: float, src: int, dst: int, payload: bytes,
                     functional: bool = False) -> list[tuple[str, Conversation]]:
        """A complete diagnostic message with source and target address (DoIP), no CAN frames involved."""
        if not payload:
            return []
        self.frames += 1
        self.first_t = t if self.first_t is None else self.first_t
        self.last_t = t
        self._diag.add((src, False))
        events = self.tick(t)
        return events + self._message(_Message(t, src, False, dst, payload, payload, None if functional else dst))

    def tick(self, now: float) -> list[tuple[str, Conversation]]:
        """Expire requests that got no answer in time."""
        events = []
        keep = []
        for p in self._pending:
            if p.deadline >= now:
                keep.append(p)
                continue
            if p.answered:
                continue
            key = (p.msg.id, p.msg.ext, p.msg.target, p.msg.payload)
            conv = self.convs.get(key)
            if conv is None and self._is_diag_id(p.msg.id, p.msg.ext):
                conv = self._conv(p.msg)
            if conv is not None:
                conv.unanswered += 1
                if not conv.announced:
                    conv.announced = True
                    events.append(("new", conv))
        self._pending = keep
        return events

    def mark(self, name: str, value: float, t: float | None = None) -> Marker:
        m = Marker(name, value, t)
        self.markers.append(m)
        return m

    # -- ISO-TP --------------------------------------------------------------------------

    def _split_ext(self, f: Frame) -> tuple[int | None, bytes]:
        if not f.ext and f.id == 0x6F1 and len(f.data) >= 2:
            self._bmw = True
            return f.data[0], f.data[1:]
        if self._bmw and not f.ext and 0x600 <= f.id <= 0x6FF and f.data[:1] == b"\xf1":
            return 0xF1, f.data[1:]
        return None, f.data

    def _isotp(self, f: Frame) -> _Message | None:
        target, d = self._split_ext(f)
        if not d:
            return None
        key = (f.id, f.ext)
        kind = d[0] >> 4
        if kind == 0:
            length, body = d[0] & 0x0F, d[1:]
            if length == 0 and len(d) > 8:  # CAN-FD escape
                length, body = d[1], d[2:]
            if not 0 < length <= len(body):
                return None
            return _Message(f.t, f.id, f.ext, target, bytes(body[:length]), f.data)
        if kind == 1:
            expected, body = ((d[0] & 0x0F) << 8) | d[1], d[2:]
            if expected == 0 and len(d) >= 6:
                expected, body = int.from_bytes(d[2:6], "big"), d[6:]
            if expected <= len(body):
                return None
            self._partial[key] = _Partial(expected, bytearray(body), [f.data], 1, f.t, target)
            return None
        if kind == 2:
            p = self._partial.get(key)
            if p is None or d[0] & 0x0F != p.seq & 0x0F or f.t - p.t > 2.0:
                self._partial.pop(key, None)
                return None
            p.buf.extend(d[1:])
            p.raw.append(f.data)
            p.seq, p.t = p.seq + 1, f.t
            if len(p.buf) < p.expected:
                return None
            del self._partial[key]
            return _Message(f.t, f.id, f.ext, p.target, bytes(p.buf[: p.expected]), b"".join(p.raw))
        if kind == 3:  # flow control: belongs to whoever just started a multi-frame message
            for sender, p in self._partial.items():
                if sender != key and f.t - p.t < 1.0 and len(p.raw) == 1:
                    self._fc[sender] = (f.id, f.data)
                    self._diag.update({key, sender})
        return None

    # -- pairing ---------------------------------------------------------------------------

    def _is_diag_id(self, can_id: int, ext: bool) -> bool:
        if (can_id, ext) in self._diag or can_id in FUNCTIONAL:
            return True
        if not ext:
            return 0x7E0 <= can_id <= 0x7E7 or can_id == 0x6F1
        return (can_id >> 8) & 0xFFFF == 0xDA00 | (can_id >> 8) & 0xFF and can_id & 0xFF == 0xF1

    def _conv(self, msg: _Message) -> Conversation:
        key = (msg.id, msg.ext, msg.target, msg.payload)
        conv = self.convs.get(key)
        if conv is None:
            conv = self.convs[key] = Conversation(msg.id, msg.ext, msg.target, msg.payload, first=msg.t, last=msg.t,
                                                  count=1)
            if self.known:
                conv.known = self.known.lookup(key)
        return conv

    def _message(self, msg: _Message) -> list[tuple[str, Conversation]]:
        sid = msg.payload[0]
        if sid == 0x7F or (sid >= 0x40 and sid - 0x40 in REQUEST_SIDS):
            return self._answer(msg)
        if sid in REQUEST_SIDS:
            key = (msg.id, msg.ext, msg.target, msg.payload)
            conv = self.convs.get(key)
            events = []
            if conv is not None:
                conv.count += 1
                conv.last = msg.t
            elif self._is_diag_id(msg.id, msg.ext):
                conv = self._conv(msg)
            if conv is not None and conv.writes and conv.count == 1:
                events.append(("write", conv))
            if not (msg.payload[0] == 0x3E and len(msg.payload) > 1 and msg.payload[1] & 0x80):
                self._pending.append(_Pending(msg, msg.t + PENDING_WINDOW))
            return events
        return []

    def _answer(self, msg: _Message) -> list[tuple[str, Conversation]]:
        pl = msg.payload
        best: _Pending | None = None
        for p in reversed(self._pending):
            req = p.msg.payload
            if p.msg.ext != msg.ext or msg.t > p.deadline:
                continue
            if pl[0] == 0x7F:
                ok = len(pl) >= 3 and pl[1] == req[0]
            else:
                n = _echo(req)
                ok = pl[0] == req[0] + 0x40 and pl[1:n] == req[1:n]
            if not ok:
                continue
            if self._bmw and p.msg.target not in (None, 0xDF) and msg.id != 0x600 + p.msg.target:
                continue
            if p.msg.peer is not None and msg.id != p.msg.peer:
                continue
            if best is None or (_related(p.msg.id, msg.id, msg.ext) and not _related(best.msg.id, msg.id, msg.ext)):
                best = p
        if best is None:
            return []
        req = best.msg
        conv = self._conv(req)
        self._diag.update({(req.id, req.ext), (msg.id, msg.ext)})
        if conv.count == 0:
            conv.count = 1
        conv.last = msg.t
        events: list[tuple[str, Conversation]] = []
        if pl[0] == 0x7F:
            if pl[2] == 0x78:  # response pending: the real answer comes later
                best.deadline = msg.t + 5.0
                return events
            conv.nrc[pl[2]] += 1
        else:
            prev = conv.known_values() if conv.known else []
            conv.add(Answer(msg.t, msg.id, pl, pl[len(req.payload):], msg.raw))
            if req.payload[0] == 0x10 and len(req.payload) >= 2:
                self._sessions[(req.id, req.ext, req.target)] = req.payload[:2]
            elif conv.session is None:
                conv.session = self._sessions.get((req.id, req.ext, req.target))
            fc = self._fc.pop((msg.id, msg.ext), None)
            if fc:
                conv.fc = fc
            if conv.announced and conv.known:
                now = conv.known_values()
                if [(v.field, v.value) for v in now if v.plausible] != [(v.field, v.value) for v in prev if v.plausible]:
                    events.append(("value", conv))
            events.append(("answer", conv))
        if req.id not in FUNCTIONAL:
            best.answered = True
            self._pending.remove(best)
        else:
            best.answered = True
        if not conv.announced:
            conv.announced = True
            events.insert(0, ("new", conv))
        return events

    # -- results ---------------------------------------------------------------------------

    @property
    def conversations(self) -> list[Conversation]:
        return sorted(self.convs.values(), key=lambda c: (c.ecu or 0, c.request))

    def broadcast_signals(self, tolerance: float | None = None) -> dict:
        """Bit fields in broadcast frames that reproduce the noted values (see broadcast.find)."""
        from . import broadcast
        if not self.markers:
            return {}
        asked = {(i, c.ext) for c in self.convs.values() for i in (c.tx, c.ecu) if i is not None}
        return broadcast.find(self.recorder, self.markers, tolerance, skip=asked)  # requests and answers are not broadcast

    def broadcast_ids(self) -> dict[tuple[int, bool], IdStats]:
        return {k: v for k, v in self.ids.items() if k not in self._diag and k not in {(c.tx, c.ext) for c in self.convs.values()}}


# -- formula search ----------------------------------------------------------------------

_SCALES = [(1, ""), (2, "/2"), (4, "/4"), (5, "/5"), (10, "/10"), (16, "/16"), (20, "/20"), (2.5, "/2.5"),
           (2.55, "*100/255"), (32, "/32"), (50, "/50"), (64, "/64"), (100, "/100"), (128, "/128"), (256, "/256"),
           (512, "/512"), (1000, "/1000"), (1024, "/1024"), (10000, "/10000"), (0.5, "*2"), (0.1, "*10")]
_OFFSETS = [(0, ""), (-40, "-40"), (-50, "-50")]


def _transforms(n: int):
    """(name, complexity, width, raw(data, i), expr(i)) for every way to read a number at byte i."""
    L = letters
    yield "u8", 0, 1, lambda d, i: d[i], lambda i: L(i)
    yield "u16", 1, 2, lambda d, i: d[i] << 8 | d[i + 1], lambda i: f"INT16({L(i)},{L(i + 1)})"
    yield "s8", 2, 1, lambda d, i: d[i] - 256 if d[i] > 127 else d[i], lambda i: f"Signed({L(i)})"
    yield "u16le", 2, 2, lambda d, i: d[i + 1] << 8 | d[i], lambda i: f"INT16({L(i + 1)},{L(i)})"
    yield "s16", 3, 2, lambda d, i: (d[i] << 8 | d[i + 1]) - (65536 if d[i] > 127 else 0), \
        lambda i: f"(INT16({L(i)},{L(i + 1)})-({L(i)}>127)*65536)"
    yield "u24", 3, 3, lambda d, i: d[i] << 16 | d[i + 1] << 8 | d[i + 2], \
        lambda i: f"INT24({L(i)},{L(i + 1)},{L(i + 2)})"


@dataclass
class Candidate:
    name: str
    conv: Conversation
    expr: str
    values: list[float]     # what the formula gives for each sample
    wanted: list[float]
    score: float

    @property
    def error(self) -> float:
        return max(abs(a - b) for a, b in zip(self.values, self.wanted, strict=True))


def resolution(text: str) -> float:
    """'79.96' -> 0.01, '80' -> 1: an app shows rounded (or cut off) values."""
    _, _, decimals = text.replace(",", ".").partition(".")
    return 10.0 ** -len(decimals)


def _tol(m: Marker, tolerance: float | None) -> float:
    if tolerance is not None:
        return tolerance
    if m.tol is None:
        return max(abs(m.value) * 0.01, 0.06)
    return max(m.tol * 1.01, abs(m.value) * 0.0025)  # apps do not always round exactly (Corsa-e: 54.79 vs 54.81)


def samples_for(conv: Conversation, markers: list[Marker], max_gap: float = 30.0) -> list[tuple[bytes, Marker]] | None:
    out = []
    for m in markers:
        if not conv.answers:
            return None
        if m.t is None:
            a = conv.answers[-1]
        else:
            a = min(conv.answers, key=lambda x: abs(x.t - m.t))
            if abs(a.t - m.t) > max_gap:
                return None
        out.append((a.data, m))
    return out


def find_formulas(convs: list[Conversation], markers: list[Marker], tolerance: float | None = None,
                  limit: int = 8) -> dict[str, list[Candidate]]:
    """For every value name: formulas on any answer byte(s) that reproduce all noted values."""
    results: dict[str, list[Candidate]] = {}
    for name in dict.fromkeys(m.name for m in markers):
        ms = [m for m in markers if m.name == name]
        found: list[Candidate] = []
        for conv in convs:
            if conv.request[0] not in READ_SIDS:
                continue
            samples = samples_for(conv, ms)
            if not samples:
                continue
            n = min(len(d) for d, _ in samples)
            for tname, cx, width, raw, expr in _transforms(n):
                for i in range(n - width + 1):
                    raws = [raw(d, i) for d, _ in samples]
                    if tname.startswith("s") and min(raws) >= 0:
                        continue  # same as unsigned here
                    for si, (div, stext) in enumerate(_SCALES):
                        for oi, (off, otext) in enumerate(_OFFSETS):
                            vals = [r / div + off for r in raws]
                            if all(abs(v - m.value) <= _tol(m, tolerance) for v, (_, m) in zip(vals, samples, strict=True)):
                                text = expr(i) + stext + otext
                                # exact hits beat simple formulas; a raw value that moves with the
                                # noted values beats a constant byte
                                fit = max(abs(v - m.value) / _tol(m, tolerance) for v, (_, m) in zip(vals, samples, strict=True))
                                score = cx + si * 0.1 + oi * 1.5 + fit * 6 - 2 * (len(set(raws)) > 1)
                                found.append(Candidate(name, conv, text, vals, [m.value for _, m in samples], score))
        found.sort(key=lambda c: c.score)
        verified = []
        for c in found:  # make sure the formula text means what we computed
            try:
                eq = Equation(c.expr)
                got = [eq(d) for d, _ in samples_for(c.conv, ms)]
            except EquationError:
                continue
            if all(abs(g - v) < 1e-6 for g, v in zip(got, c.values, strict=True)):
                verified.append(c)
            if len(verified) >= limit:
                break
        results[name] = verified
    return results


# -- profile export --------------------------------------------------------------------------

_UNITS = [("soc", "%", -5, 105), ("soh", "%", 50, 110), ("cell", "V", 2.0, 4.5), ("volt", "V", 0, 1000),
          ("current", "A", -1000, 1000), ("temp", "°C", -40, 80), ("energy", "kWh", 0, 200), ("capacity", "kWh", 0, 200),
          ("power", "kW", -500, 500), ("odometer", "km", 0, 2_000_000), ("range", "km", 0, 1500)]


def step_at(conv: Conversation, bitrate: int = 500_000) -> list[str]:
    """AT commands that make an ELM adapter send exactly the app's request."""
    at = [("ATSP7" if conv.ext else "ATSP6") if bitrate == 500_000 else ("ATSP9" if conv.ext else "ATSP8")]
    ecu = conv.ecu
    if conv.ext:
        if conv.tx >> 24 != 0x18:
            at.append(f"ATCP{conv.tx >> 24:02X}")
        at.append(f"ATSH{conv.tx & 0xFFFFFF:06X}")
        if ecu is not None:
            at.append(f"ATCRA{ecu:08X}")
    else:
        at.append(f"ATSH{conv.tx:03X}")
        if ecu is not None:
            at.append(f"ATCRA{ecu:03X}")
    at.append(f"ATCEA{conv.target:02X}" if conv.target is not None else "ATCEA")
    if conv.fc and conv.fc[0] != conv.tx:
        fc_id, fc_data = conv.fc
        body = fc_data[1:] if conv.target is not None else fc_data
        at += [f"ATFCSH{fmt_id(fc_id, conv.ext) if conv.ext else f'{fc_id:03X}'}", f"ATFCSD{body[:3].hex().upper()}",
               "ATFCSM1"]
    return at


def build_profile(name: str, picks: list[Candidate], car: str | None = None, bitrate: int = 500_000) -> dict:
    if not name.startswith("evsoc_"):
        name = "evsoc_" + name
    steps, fields = [], {}
    step_ids: dict[Key, str] = {}
    for c in picks:
        sid = step_ids.get(c.conv.key)
        if sid is None:
            sid = step_ids[c.conv.key] = f"s{len(step_ids) + 1}_{c.conv.request.hex().upper()}"
            step = {"id": sid, "at": step_at(c.conv, bitrate), "request": c.conv.request.hex().upper()}
            if c.conv.session and c.conv.session[1] & 0x7F != 0x01:
                step["pre"] = [c.conv.session.hex().upper()]  # e.g. 1003: extended session first
            steps.append(step)
        unit, lo, hi = next(((u, a, b) for k, u, a, b in _UNITS if k in c.name.lower()), ("", None, None))
        f = {"step": sid, "decode": {"type": "equation", "expr": c.expr}, "unit": unit}
        if lo is not None:
            f.update(min=lo, max=hi)
        fields[c.name] = f
    vehicles = []
    if car:
        make, _, model = car.strip().partition(" ")
        vehicles.append({"make": make, "model": model, "years": [None, None]})
    checked = ", ".join(f"{c.name}={'/'.join(f'{w:g}' for w in c.wanted)}" for c in picks)
    return {
        "name": name,
        "description": f"{car or 'Vehicle'}: derived with 'evsoc sniff' from the traffic of another app",
        "source": f"own capture {time.strftime('%Y-%m')} (evsoc sniff)",
        "license": "own work",
        "verified": f"checked against app values {checked}",
        "vehicles": vehicles,
        "init": [],
        "steps": steps,
        "fields": fields,
    }


# -- sources -----------------------------------------------------------------------------------

class CanSource:
    """Any python-can interface. Listen-only where the hardware can do it."""

    def __init__(self, interface: str, channel: str, bitrate: int = 500_000, fd: bool = False,
                 listen_only: bool = True, bus=None, log: Log = print):
        try:
            import can
        except ImportError as e:
            raise AdapterError("python-can missing: pip install python-can") from e
        self.description = f"CAN-Interface {interface}:{channel}, {bitrate // 1000} kbit/s"
        self.bitrate = bitrate
        self.silent = False
        if bus is None:
            kwargs = {"listen_only": True} if listen_only and interface == "slcan" else {}
            try:
                bus = can.Bus(interface=interface, channel=channel, bitrate=bitrate, fd=fd, **kwargs)
            except (can.CanError, OSError, ValueError) as e:
                raise AdapterError(f"CAN interface {interface}:{channel} cannot be opened: {e}") from e
            self.silent = bool(kwargs)
        self._bus = bus
        if listen_only and not self.silent:
            try:
                bus.state = can.BusState.PASSIVE
                self.silent = True
            except (NotImplementedError, can.CanError, AttributeError):
                hint = " (SocketCAN: ip link set can0 type can bitrate 500000 listen-only on)" \
                    if interface == "socketcan" else ""
                log(f"Note: {interface} has no listen-only mode{hint}. It acknowledges frames (ACK) "
                    "like any control unit but sends nothing itself.")
        self.description += ", listen only" if self.silent else ""
        self._stop = False

    def frames(self) -> Iterator[Frame | None]:
        while not self._stop:
            msg = self._bus.recv(0.2)
            if msg is None:
                yield None
            elif not msg.is_error_frame and not msg.is_remote_frame:
                yield Frame(time.time(), msg.arbitration_id, msg.is_extended_id, bytes(msg.data))

    def close(self) -> None:
        self._stop = True
        self._bus.shutdown()


_HEX = re.compile(r"^[0-9A-F]+$")


class ElmMonitorSource:
    """ELM327, OBDLink or evsoc box in monitor mode (ATMA). Silent monitoring: no ACK, nothing sent."""

    def __init__(self, adapter, protocol: str = "6", pins: tuple[int, ...] = (6, 14), log: Log = print):
        self.adapter = adapter
        self.t = adapter.t
        self.bitrate = 250_000 if protocol in ("8", "9") else 500_000
        adapter.at("ATCAF0")   # raw frames incl. ISO-TP PCI
        adapter.at("ATCSM1")   # silent monitoring (default on genuine ELM327, some clones ignore it)
        adapter.at(f"ATSP{protocol}")
        if hasattr(adapter, "select_bus"):
            from .connection import Bus
            adapter.select_bus(Bus("can", tuple(pins), self.bitrate, listen_only=True))
        self.description = f"{adapter.version or 'ELM327'} in listen mode (ATMA), protocol {protocol}"
        self.overflows = 0
        self.errors = Counter()
        self._stop = False
        self._log = log

    def frames(self) -> Iterator[Frame | None]:
        self.t.write(b"ATMA\r")
        buf = b""
        while not self._stop:
            chunk = self.t.read(0.2)
            if not chunk:
                yield None
                continue
            buf += chunk
            *lines, buf = re.split(rb"[\r\n>]+", buf)
            for line in lines:
                compact = line.decode("ascii", "replace").replace(" ", "").upper()
                if not compact or compact == "ATMA":
                    continue
                if _HEX.match(compact) and len(compact) > 3:
                    hdr = 3 if len(compact) % 2 else 8
                    if len(compact) > hdr:
                        yield Frame(time.time(), int(compact[:hdr], 16), hdr == 8, bytes.fromhex(compact[hdr:]))
                elif "BUFFERFULL" in compact or compact == "STOPPED":
                    self.overflows += 1
                    if self.overflows in (1, 10, 100):
                        self._log("Note: adapter buffer full, listening restarted. An OBDLink or a CAN interface misses less.")
                    self.t.write(b"ATMA\r")
                else:
                    self.errors[compact] += 1

    def close(self) -> None:
        self._stop = True
        try:
            self.t.write(b"\r")  # any character ends monitoring
            self.t.read(0.5)
        finally:
            self.adapter.close()


class MockAppSource:
    """Plays an app that polls the mock cars of evsoc.mock, for trying 'sniff' without a car."""

    def __init__(self, vehicle: str, cycles: int | None = None, realtime: bool = True):
        from .mock import BROADCAST, VEHICLES
        if vehicle not in VEHICLES and vehicle not in BROADCAST:
            raise ValueError(f"Unknown test vehicle {vehicle!r}, available: {', '.join([*VEHICLES, *BROADCAST])}")
        self.table = VEHICLES.get(vehicle, {})
        self.broadcast = BROADCAST.get(vehicle, {})
        self.cycles, self.realtime = cycles, realtime
        self.description = f"simulated app on test vehicle {vehicle}"
        self.bitrate = 500_000
        self._stop = False

    def _cycle(self) -> list[tuple[int, bool, bytes]]:
        from .elm import isotp_segment
        out = []
        for (header, cea, request), (resp_id, payload) in self.table.items():
            ext = len(resp_id) == 8
            tx = (int(resp_id[:2], 16) << 24 | int(header, 16)) if ext and len(header) == 6 else int(header, 16)
            rx = int(resp_id, 16)
            pad = lambda b: b + b"\x00" * (8 - len(b))  # noqa: E731
            out += [(tx, ext, pad(f)) for f in isotp_segment(bytes.fromhex(request), cea)]
            frames = isotp_segment(bytes.fromhex(payload), 0xF1 if cea is not None else None)
            out.append((rx, ext, pad(frames[0])))
            if len(frames) > 1:
                prefix = bytes([cea]) if cea is not None else b""
                out.append((tx, ext, pad(prefix + b"\x30\x00\x00")))
                out += [(rx, ext, pad(f)) for f in frames[1:]]
        out += [(int(i, 16), len(i) == 8, bytes.fromhex(d)) for i, d in self.broadcast.items()]
        return out

    def frames(self) -> Iterator[Frame | None]:
        n, t = 0, time.time()
        while not self._stop and (self.cycles is None or n < self.cycles):
            for can_id, ext, data in self._cycle():
                t = time.time() if self.realtime else t + 0.005
                yield Frame(t, can_id, ext, data)
                if self.realtime:
                    time.sleep(0.005)
            n += 1
            if self.realtime:
                for _ in range(5):
                    time.sleep(0.1)
                    yield None
            else:
                t += 0.5

    def close(self) -> None:
        self._stop = True


# -- log files -----------------------------------------------------------------------------------

class LogWriter:
    """candump -L format (readable by can-utils, SavvyCAN, python-can) plus '#' lines for noted values."""

    def __init__(self, path: str, description: str):
        self.path = path
        self._f = open(path, "a", encoding="utf-8")
        self._f.write(f"# evsoc sniff {time.strftime('%Y-%m-%d %H:%M:%S')}  {description}\n")

    def frame(self, f: Frame) -> None:
        self._f.write(f"({f.t:.6f}) can0 {fmt_id(f.id, f.ext)}#{f.data.hex().upper()}\n")

    def marker(self, m: Marker) -> None:
        value = f"{m.value:.{max(0, round(-math.log10(m.tol)))}f}" if m.tol else f"{m.value:g}"
        self._f.write(f"# ({m.t or time.time():.6f}) value {m.name}={value}\n")
        self._f.flush()

    def note(self, t: float, text: str) -> None:
        self._f.write(f"# ({t:.6f}) note {text}\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


_CANDUMP_L = re.compile(r"^\((?P<t>[\d.]+)\)\s+\S+\s+(?P<id>[0-9A-Fa-f]{1,8})#(?P<fd>#[0-9A-Fa-f])?(?P<data>[0-9A-Fa-f]*)")
_CANDUMP = re.compile(r"^(?:\((?P<t>[\d.]+)\)\s+)?\S+\s+(?P<id>[0-9A-Fa-f]{3,8})\s+\[\d+\]\s+(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)$")
# CSS Electronics CL1000/CL2000 text log: "Timestamp;Type;ID;Data", e.g. "14T105959123;0;7e8;0341050300000000"
_CL2000 = re.compile(r"^(?P<ts>[0-9T]*)[;,](?P<type>[0-9])[;,](?P<id>[0-9A-Fa-f]{1,8})[;,](?P<data>(?:[0-9A-Fa-f]{2})*)$")
_MARKER = re.compile(r"^#\s*\((?P<t>[\d.]+)\)\s+(?:value|wert)\s+(?P<name>[\w.-]+)=(?P<value>-?[\d.]+)")


def _cl2000_seconds(stamp: str) -> float | None:
    """The logger's time formats end in [HH][MM]SSkkk (milliseconds), with an optional date before a 'T'."""
    date, _, clock_part = stamp.rpartition("T")
    if not clock_part.isdigit() or len(clock_part) < 4:
        return None
    ms, rest = int(clock_part[-3:]), clock_part[:-3].rjust(6, "0")
    day = int(date[-2:]) if date[-2:].isdigit() else 0
    return day * 86400 + int(rest[-6:-4]) * 3600 + int(rest[-4:-2]) * 60 + int(rest[-2:]) + ms / 1000


def read_log(path: str) -> tuple[list[Frame], list[Marker]]:
    """candump (-L, default, -ta), raw ATMA text, CL1000/CL2000 text logs, or anything python-can reads
    (.asc, .blf, .trc, .csv, .mf4)."""
    if Path(path).suffix.lower() in (".asc", ".blf", ".trc", ".csv", ".mf4", ".db"):
        import can
        return [Frame(m.timestamp, m.arbitration_id, m.is_extended_id, bytes(m.data))
                for m in can.LogReader(path) if not m.is_error_frame and not m.is_remote_frame], []
    frames, markers, t = [], [], 0.0
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#"):
            m = _MARKER.match(line)
            if m:
                markers.append(Marker(m.group("name"), float(m.group("value")), float(m.group("t")),
                                      resolution(m.group("value"))))
            continue
        m = _CANDUMP_L.match(line) or _CANDUMP.match(line)
        if m:
            t = float(m.group("t")) if m.group("t") else t + 0.001
            cid = m.group("id")
            frames.append(Frame(t, int(cid, 16), len(cid) > 3, bytes.fromhex(m.group("data").replace(" ", ""))))
            continue
        m = _CL2000.match(line)
        if m:
            stamp = _cl2000_seconds(m.group("ts"))
            t = stamp if stamp is not None else t + 0.001
            frames.append(Frame(t, int(m.group("id"), 16), m.group("type") == "1", bytes.fromhex(m.group("data"))))
            continue
        compact = line.replace(" ", "").upper()
        if _HEX.match(compact) and len(compact) > 4:  # ELM monitor output: 7E80641...
            hdr = 3 if len(compact) % 2 else 8
            t += 0.001
            frames.append(Frame(t, int(compact[:hdr], 16), hdr == 8, bytes.fromhex(compact[hdr:])))
    return frames, markers


_NOTE = re.compile(r"^#\s*\((?P<t>[\d.]+)\)\s+(?:note|notiz)\s+(?P<text>.+)$")


def read_notes(path: str) -> list[tuple[float, str]]:
    """Free-text notes typed while recording ('# (t) note door open'), from a log or the side file of a pcap."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found = (_NOTE.match(line.strip()) for line in lines if line.startswith("#"))
    return [(float(m.group("t")), m.group("text").strip()) for m in found if m]


def parse_marker(text: str, day_of: float | None = None) -> Marker:
    """'soc=80.5', 'soc 80,5' or 'soc=80.5@21:03:12' (time of day of the recording)."""
    text = text.strip()
    when = None
    if "@" in text:
        text, _, hhmmss = text.partition("@")
        base = time.localtime(day_of or time.time())
        parts = [int(p) for p in hhmmss.split(":")] + [0, 0]
        when = time.mktime((base.tm_year, base.tm_mon, base.tm_mday, parts[0], parts[1], parts[2], 0, 0, -1))
    m = re.match(r"^([A-Za-z_][\w.-]*)\s*[=: ]\s*(-?\d+(?:[.,]\d+)?)$", text.strip())
    if not m:
        raise ValueError(f"Value {text!r} not understood, example: soc=80.5 or soc=80.5@21:03:12")
    return Marker(m.group(1), float(m.group(2).replace(",", ".")), when, resolution(m.group(2)))


# -- live --------------------------------------------------------------------------------------------

def _hex_marked(data: bytes, changed: set[int]) -> str:
    return " ".join(f"[{b:02X}]" if i in changed else f"{b:02X}" for i, b in enumerate(data))


def describe_event(kind: str, conv: Conversation, show_all: bool = False) -> str | None:
    t = clock(conv.last)
    if kind == "new":
        if conv.answers:
            n = len(conv.answers[-1].data)
            status = f"known: {conv.known_summary()}" if conv.known else "NEW to evsoc"
            return f"{t}  {conv.label:<34} {n:>3} Bytes  {status}"
        if conv.nrc:
            nrc = next(iter(conv.nrc))
            return f"{t}  {conv.label:<34} refused (NRC {nrc:02X} {_NRC.get(nrc, '')})"
        return f"{t}  {conv.label:<34} without answer"
    if kind == "value" and not show_all:
        return f"{t}  {conv.label:<34} value: {conv.known_summary(1)}"
    if kind == "answer" and show_all:
        a = conv.answers[-1]
        return f"{t}  {conv.label:<34} {_hex_marked(a.data, conv.changed)}"
    if kind == "write":
        return (f"{t}  WARNING: the app sends {conv.service} ({conv.request[:3].hex(' ').upper()} …) to {fmt_id(conv.tx, conv.ext)}. This is not a read command. evsoc itself sends nothing.")
    return None


def run_live(source, sniffer: Sniffer, writer: LogWriter | None, duration: float | None = None,
             show_all: bool = False, out: Log = print, stdin=None,
             notes: list[tuple[float, str]] | None = None, status: Callable[[], str] | None = None) -> None:
    """Capture until Ctrl+C or `duration`; values typed on stdin ('soc 80.5') are noted with a timestamp.

    With `notes`, any other typed line is kept as a free-text note ('door open')."""
    typed: queue.Queue[str] = queue.Queue()
    stdin = stdin if stdin is not None else sys.stdin
    if stdin is not None and stdin.isatty():
        def read_stdin():
            for line in stdin:
                typed.put(line)
        threading.Thread(target=read_stdin, daemon=True).start()
    end = time.monotonic() + duration if duration else None
    next_status = time.monotonic() + 30
    try:
        for frame in source.frames():
            while not typed.empty():
                line = typed.get().strip()
                if not line:
                    continue
                try:
                    m = parse_marker(line)
                    m.t = time.time()
                    sniffer.markers.append(m)
                except ValueError as e:
                    if notes is None:
                        out(str(e))
                        continue
                    now_t = time.time()
                    notes.append((now_t, line))
                    if writer:
                        writer.note(now_t, line)
                    out(f"{clock(now_t)}  noted: {line}")
                    continue
                if writer:
                    writer.marker(m)
                out(f"{clock(m.t)}  noted: {m.name} = {m.value:g}")
            if frame is not None:
                if writer:
                    writer.frame(frame)
                events = sniffer.feed(frame)
            else:
                events = sniffer.tick(time.time())
            for kind, conv in events:
                text = describe_event(kind, conv, show_all)
                if text:
                    out(text)
            now = time.monotonic()
            if now >= next_status:
                next_status = now + 30
                unknown = sum(1 for c in sniffer.convs.values() if not c.known)
                out(f"{clock(time.time())}  … " + (status() if status else
                    f"{sniffer.frames} frames, {len(sniffer.convs)} requests ({unknown} new to evsoc), {len(sniffer.broadcast_ids())} other IDs"))
            if end and now >= end:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        if writer:
            writer.close()


# -- report ---------------------------------------------------------------------------------------------

def report(sniffer: Sniffer, formulas: dict[str, list[Candidate]], out: Log = print) -> None:
    span = (sniffer.last_t or 0) - (sniffer.first_t or 0)
    out(f"\nCapture: {sniffer.frames} frames in {span:.0f} s")
    convs = sniffer.conversations
    if not convs:
        out("No diagnostic requests seen. Is the app running and asking for values right now? Right protocol (--protocol 7 for 29-bit cars like VW ID., Renault)?")
    else:
        out(f"\nThe app's requests ({len(convs)}):")
        for c in convs:
            if c.answers:
                status = f"known: {c.known_summary()}" if c.known else "NEW to evsoc"
                n = f"{len(c.answers[-1].data)} B"
            elif c.nrc:
                status = "refused: " + ", ".join(f"NRC {k:02X} {_NRC.get(k, '')}".strip() for k in c.nrc)
                n = "-"
            else:
                status, n = "no answer", "-"
            out(f"  {c.label:<34} {c.service:<20} {c.count:>5}× {c.rate:>5.1f}/s {n:>6}  {status}")
            if c.answers and c.request[0] in READ_SIDS:
                data = c.answers[-1].data
                shown = data[:24].hex(" ").upper() + (" …" if len(data) > 24 else "")
                var = ", ".join(letters(i) for i in sorted(c.varying)[:16]) + (" …" if len(c.varying) > 16 else "")
                out(f"      last {shown}" + (f"   changing: {var}" if var else ""))
            if c.session and c.session[1] & 0x7F != 0x01:
                out(f"      session change {c.session.hex(' ').upper()} before (goes into the profile as \"pre\")")
            if c.fc and c.fc[0] != c.tx:
                out(f"      flow control comes from {fmt_id(*c.fc[:1], c.ext)} (not from the sender of the request)")
        writes = [c for c in convs if c.writes]
        if writes:
            out("\nWARNING, the app sent services that are not read commands: "
                + ", ".join(f"{c.service} to {fmt_id(c.tx, c.ext)}" for c in writes))
    others = sniffer.broadcast_ids()
    if others:
        top = sorted(others.items(), key=lambda kv: -kv[1].count)[:8]
        out(f"\nOther frames (not diagnostics, e.g. broadcast): {len(others)} IDs, most frequent: "
            + ", ".join(f"{fmt_id(*k)} ({v.count})" for k, v in top))
    if sniffer.markers:
        out("\nFormula search (noted values):")
        for name, cands in formulas.items():
            wanted = [m.value for m in sniffer.markers if m.name == name]
            out(f"  {name} = {', '.join(f'{w:g}' for w in wanted)}")
            if not cands:
                out("    nothing found. Value read exactly? Give a larger --tolerance or a time @HH:MM:SS.")
            for c in cands:
                got = ", ".join(f"{v:.4g}" for v in c.values)
                tag = "  (already in profiles)" if c.conv.known else ""
                out(f"    {c.conv.label:<34} {c.expr:<34} ergibt {got}{tag}")
            if cands and len(wanted) < 2:
                out("    Tip: note a second, different value; then usually only one formula is left.")
    elif convs:
        out("\nTip: type values from the app while listening (e.g. \"soc 80.5\" + Enter) or give them with --value soc=80.5. evsoc then searches the matching formula.")
    from . import broadcast
    broadcast.report(sniffer.recorder, sniffer.broadcast_signals(), sniffer.markers, out)


def report_json(sniffer: Sniffer, formulas: dict[str, list[Candidate]]) -> dict:
    from . import broadcast
    return {
        "broadcast": broadcast.report_json(sniffer.broadcast_signals()),
        "frames": sniffer.frames,
        "seconds": round((sniffer.last_t or 0) - (sniffer.first_t or 0), 3),
        "requests": [{
            "tx": fmt_id(c.tx, c.ext), "ecu": fmt_id(c.ecu, c.ext) if c.ecu is not None else None,
            "ext_addr": c.target, "request": c.request.hex().upper(), "service": c.service, "count": c.count,
            "rate": round(c.rate, 2), "answers": len(c.answers), "unanswered": c.unanswered,
            "nrc": {f"{k:02X}": v for k, v in c.nrc.items()},
            "last": c.answers[-1].payload.hex().upper() if c.answers else None,
            "varying": [letters(i) for i in sorted(c.varying)],
            "known": [{"profile": v.profile, "field": v.field, "value": v.value, "unit": v.unit,
                       "plausible": v.plausible} for v in c.known_values()],
            "at": step_at(c) if c.ecu is not None else None,
            "session": c.session.hex().upper() if c.session else None,
            "writes": c.writes,
        } for c in sniffer.conversations],
        "other_ids": {fmt_id(*k): v.count for k, v in sniffer.broadcast_ids().items()},
        "markers": [{"name": m.name, "value": m.value, "t": m.t} for m in sniffer.markers],
        "formulas": {name: [{"request": c.conv.label, "expr": c.expr, "values": c.values,
                             "at": step_at(c.conv), "known": bool(c.conv.known)} for c in cands]
                     for name, cands in formulas.items()},
    }


def write_profile(path: str, name: str, formulas: dict[str, list[Candidate]], car: str | None,
                  bitrate: int, out: Log = print) -> bool:
    picks = [cands[0] for cands in formulas.values() if cands]
    if not picks:
        out("No profile written: no formula found (give values with --value or by typing).")
        return False
    d = build_profile(name, picks, car, bitrate)
    try:
        parse_profile(d)
    except ValueError as e:
        out(f"No profile written: {e}. At least one state of charge value needed, e.g. --value soc=80.5.")
        return False
    Path(path).write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out(f"\nProfile {d['name']} written: {path}")
    out(f"  Formulas: {', '.join(f'{c.name} = {c.expr}' for c in picks)}")
    out("  Check, then copy to evsoc/profiles/own/ and test: evsoc read -a … -p " + d["name"] + " --all")
    return True
