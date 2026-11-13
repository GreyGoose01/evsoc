"""Find values in broadcast frames: which cyclic CAN message carries the state of charge?

Behind a gateway (or on cars without one) control units send their values by themselves, no
request needed. This module takes a passive capture plus reference values with a time stamp
("at 12:01:10 the state of charge was 54.3 %") and searches every message for a bit field and a
scaling that reproduce all reference values.

The reference values come from the capture file ('# (t) value soc=54.3' lines, typed while
listening) or automatically: `Reference` reads the car through a second adapter (e.g. ENET at
the OBD socket) while the first one listens, so the known diagnostic value becomes the yardstick.

One reference value proves little, since many bytes hold "54" by chance. Candidates are ranked by
how many different reference values they reproduce.
"""

from __future__ import annotations

import bisect
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .decoders import Response as Resp
from .decoders import make_decoder
from .elm import AdapterError
from .profiles import Profile
from .reader import autodetect, read, run_init
from .safety import SafetyError
from .transports import TransportError

Log = Callable[[str], None]

# Scalings and offsets car makers actually use; a fitted factor close to one of them is taken as that.
SCALES = [1, 0.5, 0.4, 0.25, 0.2, 0.1, 0.05, 0.025, 0.02, 0.01, 0.005, 0.001, 0.0025, 0.0625, 0.125, 0.75,
          1 / 2.55, 1 / 2.56, 100 / 1023, 1 / 512, 1 / 1024, 2, 4, 5, 10]
OFFSETS = [0, -40, -48, -50, -100, -273.15, -500, -1000, -1200, 40]


class Recorder:
    """Keeps, per CAN id, the points in time at which its data changed (compact for cyclic frames)."""

    def __init__(self):
        self.ids: dict[tuple[int, bool], tuple[list[float], list[bytes]]] = {}
        self.counts: dict[tuple[int, bool], int] = {}
        self.last_t: float | None = None

    def feed(self, frame) -> None:
        key = (frame.id, frame.ext)
        times, datas = self.ids.setdefault(key, ([], []))
        self.counts[key] = self.counts.get(key, 0) + 1
        self.last_t = frame.t
        if not datas or datas[-1] != frame.data:
            times.append(frame.t)
            datas.append(frame.data)

    def at(self, key: tuple[int, bool], t: float, max_age: float) -> bytes | None:
        """The data of that id valid at time t (last change before t, or the first frame shortly after)."""
        times, datas = self.ids[key]
        i = bisect.bisect_right(times, t) - 1
        if i >= 0:
            return datas[i]
        return datas[0] if times[0] - t <= max_age else None


@dataclass
class Signal:
    name: str
    can_id: int
    ext: bool
    spec: dict             # decoder spec for a profile field ("dbc" type)
    where: str             # human description of the bit field
    values: list[float]    # decoded at the reference times
    wanted: list[float]
    distinct: int          # number of different reference values (all reproduced)
    error: float           # largest deviation
    snapped: bool          # scaling is a usual one, not a fitted odd number
    moves: bool            # the raw value changed during the capture

    @property
    def formula(self) -> str:
        f, o = self.spec["factor"], self.spec["offset"]
        return f"{self.where} × {f:g}" + (f" {'+' if o > 0 else '−'} {abs(o):g}" if o else "")

    def step(self) -> dict:
        return {"id": f"b{self.can_id:X}", "at": ["ATSP6", "ATCAF0", "ATCEA"], "listen": f"{self.can_id:0{8 if self.ext else 3}X}"}


def _fields(n_bytes: int):
    """(spec fragment, description) of the bit fields tried on a frame of n bytes."""
    for i in range(n_bytes):
        yield {"start": i * 8, "len": 8, "little": True, "signed": False}, f"Byte {i + 1}"
    for i in range(n_bytes - 1):
        for signed in (False, True):
            s = ", signed" if signed else ""
            yield ({"start": i * 8 + 7, "len": 16, "little": False, "signed": signed},
                   f"Byte {i + 1}–{i + 2} (16 bit, big endian{s})")
            yield ({"start": i * 8, "len": 16, "little": True, "signed": signed},
                   f"Byte {i + 1}–{i + 2} (16 bit, little endian{s})")
    for length in (10, 12):
        for bit in range(n_bytes * 8 - length + 1):
            if bit % 8 == 0 or (bit + length) % 8 == 0:  # fields that touch a byte border; others are rare
                yield ({"start": (bit // 8) * 8 + (7 - bit % 8), "len": length, "little": False, "signed": False},
                       f"{length} bits from byte {bit // 8 + 1} bit {7 - bit % 8} (big endian)")
                yield ({"start": bit, "len": length, "little": True, "signed": False},
                       f"{length} bits from bit {bit} (little endian)")


def _raw(frame: bytes, f: dict) -> int:
    if f["little"]:
        raw = (int.from_bytes(frame, "little") >> f["start"]) & ((1 << f["len"]) - 1)
    else:
        msb = (f["start"] // 8) * 8 + (7 - f["start"] % 8)
        raw = (int.from_bytes(frame, "big") >> (len(frame) * 8 - msb - f["len"])) & ((1 << f["len"]) - 1)
    if f["signed"] and raw & (1 << (f["len"] - 1)):
        raw -= 1 << f["len"]
    return raw


def _fit(raws: list[int], wanted: list[float], tols: list[float]) -> tuple[float, float, bool] | None:
    """(factor, offset, snapped) so that raw*factor+offset reproduces every wanted value, else None."""
    def ok(a: float, b: float, usual: bool = True) -> bool:
        return all(abs(r * a + b - w) <= t + step_allowance(a, usual) for r, w, t in zip(raws, wanted, tols, strict=True))

    if len(set(raws)) < 2:  # constant raw value: only usual scalings, a fit would be meaningless
        for a in SCALES:
            for b in OFFSETS[:2]:
                if ok(a, b):
                    return a, b, True
        return None
    n = len(raws)
    mr, mw = sum(raws) / n, sum(wanted) / n
    var = sum((r - mr) ** 2 for r in raws)
    a = sum((r - mr) * (w - mw) for r, w in zip(raws, wanted, strict=True)) / var
    b = mw - a * mr
    if a == 0:
        return None
    for sa in sorted(SCALES, key=lambda s: abs(s - a)):
        if abs(sa - a) > abs(a) * 0.08:  # coarse signals (one byte for 0-100 %) fit only roughly
            break
        for sb in sorted(OFFSETS, key=lambda o: abs(o - b))[:2]:
            if ok(sa, sb):
                return sa, sb, True
    return (round(a, 6), round(b, 4), False) if ok(a, b, usual=False) else None


def step_allowance(factor: float, usual: bool) -> float:
    """A signal cannot be finer than one raw step: half a step counts as a match, for usual fine scalings
    only (a fitted odd factor of 40 would otherwise 'match' anything that grows)."""
    return abs(factor) / 2 if usual and abs(factor) <= 1 else 0.0


def _tolerance(marker, tolerance: float | None) -> float:
    """How far a decoded value may be from the reference: its display resolution, not a share of its size
    (a share would let anything pass for big numbers like the odometer)."""
    if tolerance is not None:
        return tolerance
    return marker.tol * 1.01 if marker.tol else max(abs(marker.value) * 0.005, 0.06)


def find(rec: Recorder, markers: list, tolerance: float | None = None, limit: int = 6, max_age: float = 3.0,
         skip: set[tuple[int, bool]] | None = None) -> dict[str, list[Signal]]:
    """For every reference value name: the bit fields in broadcast frames that reproduce its values."""
    out: dict[str, list[Signal]] = {}
    for name in dict.fromkeys(m.name for m in markers):
        ms = [m for m in markers if m.name == name]
        times = [m.t if m.t is not None else (rec.last_t or 0.0) for m in ms]
        wanted = [m.value for m in ms]
        tols = [_tolerance(m, tolerance) for m in ms]
        distinct_wanted = len({round(w / max(t, 1e-9)) for w, t in zip(wanted, tols, strict=True)})
        found: list[Signal] = []
        for key, (_times, datas) in rec.ids.items():
            if skip and key in skip:
                continue
            frames = [rec.at(key, t, max_age) for t in times]
            if any(f is None for f in frames):
                continue
            if distinct_wanted > 1 and len(set(frames)) < 2:
                continue  # the value moved, this message did not
            n_bytes = min(len(f) for f in frames)
            for f, where in _fields(n_bytes):
                raws = [_raw(frame[:n_bytes], f) for frame in frames]
                if distinct_wanted > 1 and len(set(raws)) < 2:
                    continue
                if f["signed"] and min(raws) >= 0:
                    continue  # same as the unsigned field here
                fit = _fit(raws, wanted, tols)
                if fit is None:
                    continue
                a, b, snapped = fit
                spec = {"type": "dbc", **f, "factor": a, "offset": b}
                dec = make_decoder(spec)  # make sure the profile decoder computes the same
                values = [dec(Resp(frame[:n_bytes], frame[:n_bytes])) for frame in frames]
                if any(abs(v - w) > t + step_allowance(a, snapped) for v, w, t in zip(values, wanted, tols, strict=True)):
                    continue
                err = max(abs(v - w) for v, w in zip(values, wanted, strict=True))
                series = [_raw(d[:n_bytes], f) for d in datas if len(d) >= n_bytes]
                moves = len(set(series)) > 1
                changes = sum(x != y for x, y in zip(series, series[1:], strict=False))
                if not snapped and changes > rec.counts[key] * 0.5:
                    continue  # a counter runs in step with anything that grows steadily; only odd factors "fit"
                found.append(Signal(name, key[0], key[1], spec, where, [round(v, 4) for v in values], wanted,
                                    distinct_wanted, err, snapped, moves))
        # more reproduced values first, usual scalings before odd ones, plain bytes before odd bit fields
        if any(s.snapped for s in found):
            found = [s for s in found if s.snapped]  # odd fitted factors are only worth showing when nothing usual fits
        found.sort(key=lambda s: (not s.snapped, not s.moves, s.spec["len"] not in (8, 16),
                                  round(s.error / max(tols), 2), s.spec["len"], s.can_id))
        unique: dict[tuple, Signal] = {}
        for sig in found:  # a wider field around the same bits decodes to the same numbers: keep the simplest
            unique.setdefault((sig.can_id, sig.ext, sig.spec["factor"], sig.spec["offset"], tuple(sig.values)), sig)
        found = list(unique.values())
        out[name] = found[:limit]
        out[name + "#total"] = len(found)  # type: ignore[assignment]
    return out


def report(rec: Recorder, signals: dict, markers: list, out: Log = print) -> None:
    names = [n for n in signals if not n.endswith("#total")]
    if not names:
        return
    out(f"\nBroadcast frames: {len(rec.ids)} IDs. Searching for the noted values:")
    for name in names:
        ms = [m for m in markers if m.name == name]
        distinct = len({m.value for m in ms})
        total = signals[name + "#total"]
        out(f"\n  {name}: {len(ms)} reference values, {distinct} different ({min(m.value for m in ms):g} … {max(m.value for m in ms):g})")
        if not signals[name]:
            out("    no signal found. Is the value on this bus? Do the times of the values match the capture?")
            continue
        for s in signals[name]:
            flags = ("" if s.snapped else "  [odd scaling]") + ("" if s.moves else "  [does not move in the capture]")
            out(f"    {s.can_id:0{8 if s.ext else 3}X}  {s.formula}   deviation at most {round(s.error, 4):g}, "
                f"{s.distinct} different values matched{flags}")
        if total > len(signals[name]):
            out(f"    … and {total - len(signals[name])} more candidates")
        if distinct < 3:
            out("    Careful: with fewer than three different reference values, chance matches are common. Record longer while the value changes (driving or charging).")
        else:
            best = signals[name][0]
            out(f"    For a profile: step {best.step()}  field decoder {best.spec}")


def report_json(signals: dict) -> dict:
    return {n: [{"id": f"{s.can_id:X}", "ext": s.ext, "formula": s.formula, "decode": s.spec, "step": s.step(),
                 "distinct": s.distinct, "error": s.error, "snapped": s.snapped, "moves": s.moves}
                for s in v] for n, v in signals.items() if not n.endswith("#total")}


# -- reference values from a second adapter ----------------------------------------------------------

class Feed:
    """Stands in for the keyboard of `sniff.run_live`: lines like 'soc 54.3', from any thread."""

    def __init__(self):
        self.queue: queue.Queue[str | None] = queue.Queue()

    def isatty(self) -> bool:
        return True

    def put(self, line: str) -> None:
        self.queue.put(line)

    def close(self) -> None:
        self.queue.put(None)

    def __iter__(self):
        while (line := self.queue.get()) is not None:
            yield line


class Reference(threading.Thread):
    """Reads the car through a second adapter every `interval` seconds and feeds the plausible values in
    as reference ('soc 54.3'), while the first adapter only listens."""

    def __init__(self, connect, profiles: dict[str, Profile], feed: Feed, profile: Profile | None = None,
                 car: str | None = None, interval: float = 10, log: Log = print):
        super().__init__(daemon=True)
        self.connect, self.profiles, self.feed = connect, profiles, feed
        self.profile, self.car, self.interval, self.log = profile, car, interval, log
        self.stop = threading.Event()
        self.readings = 0
        self.error: str | None = None

    def run(self) -> None:
        adapter = None
        try:
            adapter = self.connect()
            if self.profile is None:
                det = autodetect(adapter, self.profiles, car=self.car, log=lambda _m: None)
                if det is None:
                    raise AdapterError("Reference: no profile returns a plausible state of charge")
                self.profile = det.profile
            self.log(f"Reference: reading {self.profile.name} every {self.interval:g} s")
            run_init(adapter, self.profile)
            while not self.stop.is_set():
                reading = read(adapter, self.profile)
                for name, v in reading.values.items():
                    if v.plausible and v.value is not None:
                        self.feed.put(f"{name} {v.value}")
                self.readings += 1
                self.stop.wait(self.interval)
        except (AdapterError, TransportError, SafetyError, OSError) as e:
            self.error = str(e)
            self.log(f"Reference failed: {e}")
        finally:
            if adapter is not None:
                try:
                    adapter.close()
                except Exception:  # noqa: BLE001 - closing a dead link may fail any way
                    pass

    def finish(self) -> None:
        self.stop.set()
        self.join(self.interval + 15)


def now() -> float:
    return time.time()
