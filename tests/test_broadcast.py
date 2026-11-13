"""Search for values in broadcast frames: a synthetic bus with hidden signals and reference values."""

import json

import pytest

from evsoc import broadcast
from evsoc.cli import main, open_adapter
from evsoc.profiles import load_all
from evsoc.sniff import Frame, Marker, Sniffer

SOC = [54.3, 54.8, 55.6, 57.0, 58.4, 60.1]     # what the reference reads at t = 10, 20, ... 60 s
TEMP = [21, 21, 22, 22, 23, 24]


def bus(seconds=65, step=0.5):
    """Cyclic frames like behind a gateway: the state of charge in three encodings, a temperature, noise."""
    frames = []
    for n in range(int(seconds / step)):
        t = 1000.0 + n * step
        i = min(int(n * step // 10), len(SOC)) - 1 if n * step >= 10 else 0
        i = max(0, min(int((n * step + 5) // 10) - 1, len(SOC) - 1))   # value changes 5 s before each reference time
        soc, temp = SOC[i], TEMP[i]
        raw16 = round(soc * 100)
        raw10 = round(soc * 10)
        frames += [
            Frame(t, 0x3A5, False, bytes([0x11, n & 0xFF, raw16 >> 8, raw16 & 0xFF, 0, 0, 0xFF, 0x00])),      # 16 bit BE /100
            Frame(t, 0x1F0, False, bytes([0x00, round(soc * 2), 0x7F, 0x00])),                                 # 1 byte /2
            Frame(t, 0x2D5, False, bytes([0, 0, 0x4F, 0x14, raw10 >> 8, raw10 & 0xFF, 0, 0])),                # 10 bit /10 (smart)
            Frame(t, 0x400, False, bytes([temp + 40, 0x33, raw16 & 0xFF, raw16 >> 8])),                        # temp -40; 16 bit LE
            Frame(t, 0x0C0, False, bytes([n & 0xFF, (n * 7) & 0xFF, 0x50, 0x00])),                              # counters
            Frame(t, 0x510, False, bytes([0x36, 0x36, 0x36, 0x36])),                                           # constant
        ]
    return frames


def markers():
    out = []
    for k, (soc, temp) in enumerate(zip(SOC, TEMP, strict=True)):
        t = 1000.0 + 10 * (k + 1)
        out += [Marker("soc", soc, t, 0.1), Marker("batt_temp", temp, t, 1.0)]
    return out


def recorder(frames):
    rec = broadcast.Recorder()
    for f in frames:
        rec.feed(f)
    return rec


def test_finds_the_hidden_signals_with_usual_scalings():
    rec = recorder(bus())
    found = broadcast.find(rec, markers())
    soc = {(s.can_id, s.where.split(" (")[0], s.spec["factor"], s.spec["offset"]) for s in found["soc"]}
    assert (0x3A5, "Byte 3–4", 0.01, 0) in soc
    assert (0x1F0, "Byte 2", 0.5, 0) in soc
    assert (0x400, "Byte 3–4", 0.01, 0) in soc                      # the little-endian copy
    assert sum(s.can_id == 0x2D5 and s.spec["factor"] == 0.1 for s in found["soc"]) == 1   # wider fields merged into one
    assert all(s.distinct == 6 and s.snapped and s.moves for s in found["soc"])
    assert not any(s.can_id in (0x0C0, 0x510) for s in found["soc"])   # counters and constants do not follow the value
    best = found["soc"][0]
    assert best.spec["len"] in (8, 16) and best.error <= 0.1          # plain bytes rank before odd bit fields

    temp = found["batt_temp"][0]
    assert (temp.can_id, temp.spec["start"], temp.spec["factor"], temp.spec["offset"]) == (0x400, 0, 1, -40)
    assert temp.formula == "Byte 1 × 1 − 40" and temp.step()["listen"] == "400"

    lines = []
    broadcast.report(rec, found, markers(), lines.append)
    text = "\n".join(lines)
    assert "soc: 6 reference values, 6 different" in text and "3A5  Byte 3–4" in text and "For a profile" in text


def test_found_decoder_works_in_a_profile():
    """The printed step and decoder are exactly what a profile needs."""
    from evsoc.decoders import Response, make_decoder
    found = broadcast.find(recorder(bus()), markers())
    best = next(s for s in found["soc"] if s.can_id == 0x3A5)
    frame = bytes([0x11, 0x00, 0x15, 0x36, 0, 0, 0xFF, 0x00])        # 0x1536 = 5430
    assert make_decoder(best.spec)(Response(frame, frame)) == pytest.approx(54.3)


def test_one_reference_value_is_flagged_as_weak():
    rec = recorder(bus())
    one = [Marker("soc", 54.3, 1010.0, 0.1)]
    found = broadcast.find(rec, one)
    assert found["soc"] and found["soc#total"] >= 3                  # many things hold "54.3" at one moment
    lines = []
    broadcast.report(rec, found, one, lines.append)
    assert any("chance matches" in line for line in lines)


def test_value_that_is_not_on_the_bus():
    rec = recorder(bus())
    ms = [Marker("odometer", 23150 + 37 * k, 1000.0 + 10 * (k + 1), 1.0) for k in range(6)]
    found = broadcast.find(rec, ms)
    assert found["odometer"] == []
    lines = []
    broadcast.report(rec, found, ms, lines.append)
    assert any("no signal found" in line for line in lines)


def test_capture_file_with_noted_values_reports_broadcast_signals(tmp_path, capsys):
    log = tmp_path / "bus.log"
    lines = [f"({f.t:.3f}) can0 {f.id:03X}#{f.data.hex().upper()}" for f in bus()]
    lines += [f"# ({m.t:.3f}) value {m.name}={m.value:.1f}" for m in markers() if m.name == "soc"]
    log.write_text("\n".join(lines) + "\n")
    assert main(["sniff", "-d", str(log)]) == 0
    out = capsys.readouterr().out
    assert "Broadcast frames: 6 IDs" in out and "3A5  Byte 3–4 (16 bit, big endian) × 0.01" in out
    assert main(["sniff", "-d", str(log), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(c["id"] == "3A5" and c["decode"]["factor"] == 0.01 for c in data["broadcast"]["soc"])


def test_diagnostic_ids_are_not_searched():
    s = Sniffer()
    for f in bus(seconds=25):
        s.feed(f)
    for t in (1010.0, 1020.0):   # a tester asks, the car answers 0x1536 = 54.30 as well
        s.feed(Frame(t, 0x6B4, False, bytes.fromhex("0322D81000000000")))
        s.feed(Frame(t + 0.01, 0x694, False, bytes.fromhex("0562D81015360000")))
    s.markers += [Marker("soc", 54.3, 1010.0, 0.1), Marker("soc", 54.8, 1020.0, 0.1)]
    assert not any(c.can_id in (0x6B4, 0x694) for c in s.broadcast_signals()["soc"])


def test_reference_reads_the_car_through_a_second_adapter():
    feed = broadcast.Feed()
    ref = broadcast.Reference(lambda: open_adapter("mock://corsa-e", None), load_all(),
                              feed, profile=load_all()["evsoc_stellantis_ecmp"], interval=0.05, log=lambda _m: None)
    ref.start()
    got = []
    for line in feed:
        got.append(line)
        if len(got) >= 25:
            break
    ref.finish()
    feed.close()
    assert ref.error is None and ref.readings >= 2
    names = {line.split()[0] for line in got}
    assert {"soc", "soh", "voltage", "batt_temp"} <= names
    assert float(next(line for line in got if line.startswith("soc ")).split()[1]) == pytest.approx(79.96, abs=0.01)

    broken = broadcast.Reference(lambda: open_adapter("tcp://127.0.0.1:1", None), load_all(), broadcast.Feed(),
                                 log=lambda _m: None)
    broken.start()
    broken.finish()
    assert "No connection" in broken.error


def test_listening_with_a_reference_adapter(tmp_path, capsys):
    out = tmp_path / "m.log"
    assert main(["sniff", "-a", "mock://corsa-e", "--dauer", "1.5", "-o", str(out), "--referenz", "mock://corsa-e",
                 "--referenz-profil", "evsoc_stellantis_ecmp", "--referenz-abstand", "0.3"]) == 0
    text = capsys.readouterr().out
    assert "Reference: reading evsoc_stellantis_ecmp" in text and "noted: soc = 79.959" in text
    assert "value soc=79.959" in out.read_text()                      # reference values are saved with the capture
    assert main(["sniff", "-a", "mock://corsa-e", "--dauer", "0.2", "--referenz", "mock://corsa-e",
                 "--referenz-profil", "gibt_es_nicht"]) == 2
