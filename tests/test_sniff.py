import json

import pytest

from evsoc import sniff
from evsoc.cli import main
from evsoc.elm import ElmAdapter
from evsoc.mock import MockElmTransport
from evsoc.profiles import load_all, parse_profile
from evsoc.reader import read, run_init
from evsoc.sniff import Frame, KnownIndex, Marker, MockAppSource, Sniffer


@pytest.fixture(scope="module")
def known():
    return KnownIndex(load_all())


def capture(vehicle, known=None, cycles=2):
    s = Sniffer(known)
    for f in MockAppSource(vehicle, cycles=cycles, realtime=False).frames():
        if f is not None:
            s.feed(f)
    s.tick(float("inf"))
    return s


def conv(s, request):
    return next(c for c in s.conversations if c.request == bytes.fromhex(request))


def test_pairs_requests_and_answers_and_knows_profiles(known):
    s = capture("corsa-e", known)
    c = conv(s, "22D410")
    assert (c.tx, c.ecu, c.count, len(c.answers)) == (0x6B4, 0x694, 2, 2)
    assert c.answers[-1].data == bytes.fromhex("9FEB")
    soc = [v for v in c.known_values() if v.profile == "evsoc_stellantis_ecmp" and v.field == "soc"]
    assert soc and soc[0].value == pytest.approx(79.96, abs=0.01)
    assert not s.broadcast_ids()


def test_multiframe_with_flow_control(known):
    s = capture("ioniq5", known)
    c = conv(s, "220101")
    assert c.ecu == 0x7EC and len(c.answers[-1].data) == 56 and c.answers[-1].data[4] == 160
    assert c.fc and c.fc[0] == 0x7E4
    assert c.known
    assert conv(s, "0902").ecu == 0x7E8  # functional request 7DF


def test_bmw_extended_addressing(known):
    s = capture("bmw-i3", known)
    c = conv(s, "22DDBC")
    assert (c.tx, c.target, c.ecu) == (0x6F1, 0x07, 0x607)
    assert c.known and "ATCEA07" in sniff.step_at(c)


def test_29bit(known):
    s = capture("id4", known)
    c = conv(s, "223DEF")
    assert c.ext and c.tx == 0x17FC0076 and c.ecu == 0x17FE0076
    assert sniff.step_at(c)[:4] == ["ATSP7", "ATCP17", "ATSHFC0076", "ATCRA17FE0076"]
    assert conv(s, "222AB2").ecu == 0x77A  # 11-bit ECU in the same car


def test_unknown_request_without_answer_and_negative():
    s = Sniffer()
    s.feed(Frame(0.0, 0x7E4, False, bytes.fromhex("0322AAAA00000000")))
    s.feed(Frame(0.1, 0x7E4, False, bytes.fromhex("0322BBBB00000000")))
    s.feed(Frame(0.2, 0x7EC, False, bytes.fromhex("037F223100000000")))
    s.tick(10)
    assert conv(s, "22AAAA").unanswered == 1
    assert conv(s, "22BBBB").nrc[0x31] == 1


def test_write_service_is_flagged():
    s = Sniffer()
    events = s.feed(Frame(0.0, 0x7E0, False, bytes.fromhex("042E010203000000")))
    assert events and events[0][0] == "write"
    assert "WRITE" in sniff.describe_event(*events[0])


def test_broadcast_is_not_diagnostic():
    s = Sniffer()
    for i in range(5):
        s.feed(Frame(i * 0.1, 0x55B, False, bytes([0xA2, i, 0, 0, 0, 0, 0, 0])))
    assert not s.convs
    assert s.broadcast_ids()[(0x55B, False)].varying == {1}


def test_formula_search_two_values():
    s = Sniffer()
    for t, data in ((0.0, "6D9D"), (100.0, "9FEB")):  # Corsa-e log: 54.79 % and 79.96 %
        s.feed(Frame(t, 0x6B4, False, bytes.fromhex("0322D41000000000")))
        s.feed(Frame(t + 0.05, 0x694, False, bytes.fromhex(f"0562D410{data}0000")))
    s.markers += [Marker("soc", 54.79, 1.0, 0.01), Marker("soc", 79.96, 101.0, 0.01)]
    best = sniff.find_formulas(s.conversations, s.markers)["soc"]
    assert best[0].expr == "INT16(A,B)/512"


def test_resolution_tolerance():
    assert sniff.resolution("79.96") == pytest.approx(0.01)
    assert sniff.resolution("80") == 1
    assert sniff.parse_marker("soc 80,5").value == 80.5


def test_letters():
    assert [sniff.letters(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]


def test_exported_profile_reads_the_car(tmp_path):
    s = capture("corsa-e")
    s.markers += [Marker("soc", 79.96, None, 0.01), Marker("voltage", 426.2, None, 0.1)]
    formulas = sniff.find_formulas(s.conversations, s.markers)
    path = tmp_path / "evsoc_mein_corsa.json"
    assert sniff.write_profile(str(path), path.stem, formulas, "Opel Corsa-e", 500_000, out=lambda _m: None)
    profile = parse_profile(json.loads(path.read_text()))
    adapter = ElmAdapter(MockElmTransport("corsa-e"))
    adapter.reset()
    run_init(adapter, profile)
    r = read(adapter, profile)
    assert r.values["soc"].value == pytest.approx(79.96, abs=0.01)
    assert r.values["voltage"].value == pytest.approx(426.2, abs=0.1)


def test_log_roundtrip(tmp_path):
    path = tmp_path / "m.log"
    w = sniff.LogWriter(str(path), "Test")
    for f in MockAppSource("ioniq5", cycles=1, realtime=False).frames():
        if f:
            w.frame(f)
    w.marker(Marker("soc", 79.0, 123.0, 0.1))
    w.close()
    frames, markers = sniff.read_log(str(path))
    assert len(frames) > 10 and frames[0].id == 0x7E4
    assert markers[0].name == "soc" and markers[0].value == 79.0 and markers[0].tol == pytest.approx(0.1)


def test_read_other_log_formats(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("  can0  7E4   [8]  03 22 01 05 00 00 00 00\n"
                    "(1696874400.5) can0 18DAF1DB#0562D41012340000\n"
                    "7EC0562010500000000\n")
    frames, _ = sniff.read_log(str(path))
    assert [(f.id, f.ext) for f in frames] == [(0x7E4, False), (0x18DAF1DB, True), (0x7EC, False)]


class MonitorTransport:
    """ELM327 that answers setup commands and streams a canned ATMA output."""

    def __init__(self, lines):
        self.lines, self.out, self.sent, self.monitoring = lines, b"", [], False

    def write(self, data):
        cmd = data.decode().strip().upper()
        self.sent.append(cmd)
        if cmd == "ATMA":
            self.monitoring = True
            self.out += b"".join(l.encode() + b"\r" for l in self.lines)
            self.lines = []
        elif self.monitoring:
            self.monitoring = False
            self.out += b"\r>"
        else:
            self.out += (b"ELM327 v1.5" if cmd in ("ATZ", "ATI") else b"OK") + b"\r\r>"

    def read(self, timeout):
        out, self.out = self.out, b""
        return out

    def close(self):
        pass


def test_elm_monitor_source(known):
    t = MonitorTransport(["7E40322D41000000000", "BUFFER FULL", "", "18DAF1DB0562D4109FEB0000"])
    adapter = ElmAdapter(t)
    adapter.reset()
    src = sniff.ElmMonitorSource(adapter, "6", log=lambda _m: None)
    frames = []
    for f in src.frames():
        if f is None:
            break
        frames.append(f)
    src.close()
    assert "ATCAF0" in t.sent and "ATSP6" in t.sent and t.sent.count("ATMA") == 2
    assert [(f.id, f.ext, f.data[:3].hex()) for f in frames] == [(0x7E4, False, "0322d4"), (0x18DAF1DB, True, "0562d4")]
    assert src.overflows == 1


def test_cli_live_with_mock_and_profile(tmp_path, capsys):
    log = tmp_path / "m.log"
    prof = tmp_path / "evsoc_corsa_test.json"
    rc = main(["sniff", "-a", "mock://corsa-e", "--dauer", "0.8", "-o", str(log),
               "--wert", "soc=79.96", "--profil", str(prof), "--car", "Opel Corsa-e"])
    out = capsys.readouterr().out
    assert rc == 0 and log.exists() and prof.exists()
    assert "6B4 → 694  22 D4 10" in out and "INT16(A,B)/512" in out
    rc = main(["sniff", "-d", str(log), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and any(r["request"] == "22D410" and r["known"] for r in data["requests"])


def test_cli_rejects_enet():
    assert main(["sniff", "-a", "enet://auto"]) == 1


def test_can_source_on_virtual_bus(known):
    can = pytest.importorskip("can")
    import uuid
    channel = f"sniff-{uuid.uuid4().hex}"
    app = can.Bus(interface="virtual", channel=channel)
    src = sniff.CanSource("virtual", channel, log=lambda _m: None)
    s = Sniffer(known)
    app.send(can.Message(arbitration_id=0x6B4, data=bytes.fromhex("0322D41000000000"), is_extended_id=False))
    app.send(can.Message(arbitration_id=0x694, data=bytes.fromhex("0562D4109FEB0000"), is_extended_id=False))
    for f in src.frames():
        if f is None:
            break
        s.feed(f)
    src.close()
    app.shutdown()
    assert conv(s, "22D410").answers[-1].data == bytes.fromhex("9FEB")


def test_session_change_goes_into_profile(tmp_path):
    s = Sniffer()
    for t, data in ((0.0, "1234"), (50.0, "2345")):
        s.feed(Frame(t, 0x7E4, False, bytes.fromhex("0210030000000000")))
        s.feed(Frame(t + 0.02, 0x7EC, False, bytes.fromhex("0650030032019000")))
        s.feed(Frame(t + 0.05, 0x7E4, False, bytes.fromhex("0322AB1200000000")))
        s.feed(Frame(t + 0.07, 0x7EC, False, bytes.fromhex(f"0562AB12{data}0000")))
    c = conv(s, "22AB12")
    assert c.session == bytes.fromhex("1003")
    s.markers += [Marker("soc", 0x1234 / 100, 0.1, 0.01), Marker("soc", 0x2345 / 100, 50.1, 0.01)]
    formulas = sniff.find_formulas(s.conversations, s.markers)
    path = tmp_path / "evsoc_session.json"
    assert sniff.write_profile(str(path), path.stem, formulas, None, 500_000, out=lambda _m: None)
    step = json.loads(path.read_text())["steps"][0]
    assert step["request"] == "22AB12" and step["pre"] == ["1003"]
