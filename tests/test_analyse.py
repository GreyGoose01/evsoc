import math
import socket
import struct
import threading
import time

import pytest

from evsoc import analyse, pcap, sniff
from evsoc.cli import main
from evsoc.profiles import load_all
from evsoc.sniff import Frame, KnownIndex

T0 = 1762770000.0


# -- CAN ---------------------------------------------------------------------------------------

def can_log(path):
    """30 s of a made-up car: fast signals with counter and checksum, a door bit, a tester polling the SoC."""
    lines = ["# evsoc sniff test"]
    soc = 0x9FEB
    for k in range(3000):
        t = T0 + k * 0.01
        speed, current = int(5000 + 4000 * math.sin(k / 400)), int(1000 + 900 * math.sin(k / 150))
        body = bytes([0x30 | k & 0x0F, speed >> 8, speed & 0xFF, 0, current & 0xFF, current >> 8, 0x55])
        lines.append(f"({t:.6f}) can0 1A0#{body.hex()}{(sum(body) + 0x5A) & 0xFF:02X}")
        if k % 10 == 0:
            lines.append(f"({t + 0.001:.6f}) can0 3D2#00{1 if 1200 <= k < 2000 else 0:02X}FF{k // 10 & 0xFF:02X}")
        if k % 100 == 0:
            lines.append(f"({t + 0.002:.6f}) can0 18FEF100#0102030405060708")
        if k % 200 == 50:
            soc -= 40
            lines.append(f"({t + 0.003:.6f}) can0 6B4#0322D41000000000")
            lines.append(f"({t + 0.006:.6f}) can0 694#0562D410{soc:04X}0000")
        if k == 1200:
            lines.append(f"# ({t:.6f}) note door open")
        if k == 2500:
            lines.append(f"# ({t:.6f}) value soc=79.1")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture(scope="module")
def car(tmp_path_factory):
    return analyse.load(can_log(tmp_path_factory.mktemp("can") / "fahrt.log"), KnownIndex(load_all()))


def test_bytes_of_a_broadcast_message_are_classified(car):
    info = analyse.analyse_stream(car.can[(0x1A0, False)])
    assert info.cyclic and info.period == pytest.approx(0.01, abs=1e-4)
    assert info.pattern == "ZSS.SS.P"
    assert [(f.start, f.size, f.order) for f in info.fields] == [(1, 2, "BE"), (4, 2, "LE")]
    assert (info.fields[0].lo, info.fields[0].hi) == (1000, 8999)
    assert "sum" in info.bytes[7].text and info.bytes[7].text.endswith("5A)")


def test_rare_changes_are_listed_with_their_time(car):
    info = analyse.analyse_stream(car.can[(0x3D2, False)])
    assert info.pattern == ".F.Z"
    assert [(round(t - T0, 2), diff) for t, diff in info.changes] == [(12.0, [(1, 0, 1)]), (20.0, [(1, 1, 0)])]


def test_report_has_notes_diagnostics_and_all_ids(car):
    text = analyse.report(car)
    assert "+12.0 s (" in text and "door open" in text and "value read off soc = 79.1" in text
    assert "| 6B4 → 694  22 D4 10 | UDS read | 15 | 15 | known: evsoc_stellantis_ecmp" in text
    assert "| 18FEF100 | 30 | 1000 ms | 8 | `........` |" in text
    assert "Diagnostic IDs (evaluated above, not here): 694, 6B4" in text
    assert "### CAN 3D2" in text and "- +12.00 s  B 00→01" in text
    assert "### CAN 18FEF100" not in text  # nothing moves there
    assert "5 IDs (4× 11 bit, 1× 29 bit)" in text and "bus load about 3 %" in text
    assert len(text.splitlines()) < 150  # 3400 frames boiled down


def test_focus_on_one_id_shows_it_in_full(car):
    text = analyse.report(car, ["3d2"])
    assert "### CAN 3D2" in text and "### CAN 1A0" not in text and "## Diagnostics" not in text
    assert text.count("\n   ") + text.count("\n  ") >= 40
    assert "### response to 6B4 → 694  22 D4 10" in analyse.report(car, ["22D410"])
    assert "Nothing found" in analyse.report(car, ["7FF"])


def test_cli_writes_the_report_next_to_the_recording(tmp_path, capsys):
    log = can_log(tmp_path / "fahrt.log")
    assert main(["analyse", "-d", log]) == 0
    assert "fahrt.analyse.md" in capsys.readouterr().out
    assert (tmp_path / "fahrt.analyse.md").read_text(encoding="utf-8").startswith("# evsoc analysis: fahrt.log")
    assert main(["analyse", "-d", log, "--id", "1A0", "-o", "-"]) == 0
    assert "B–C number 16 bit BE" in capsys.readouterr().out


def test_live_recording_keeps_typed_notes(tmp_path, capsys):
    class Typed:
        def __init__(self, lines):
            self.lines = lines

        def isatty(self):
            return True

        def __iter__(self):
            return iter(self.lines)

    log = tmp_path / "live.log"
    notes = []
    source = sniff.MockAppSource("tesla-m3", cycles=3, realtime=True)
    sniff.run_live(source, sniff.Sniffer(), sniff.LogWriter(str(log), "test"), out=lambda _m: None,
                   stdin=Typed(["door open\n", "soc 80.5\n"]), notes=notes)
    assert [text for _, text in notes] == ["door open"]
    a = analyse.load(str(log))
    assert [text for _, text in a.notes] == ["door open"] and a.sniffer.markers[0].name == "soc"
    assert a.can_frames == 3


# -- Ethernet ----------------------------------------------------------------------------------

MAC_A, MAC_B = bytes.fromhex("02000000000a"), bytes.fromhex("02000000000b")


def ip(src, dst, proto, l4):
    head = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(l4), 0, 0, 64, proto, 0, socket.inet_aton(src), socket.inet_aton(dst))
    return head + l4


def eth(src_mac, dst_mac, etype, body, vlan=None):
    tag = struct.pack(">HH", 0x8100, 5 << 13 | vlan) if vlan is not None else b""
    return dst_mac + src_mac + tag + struct.pack(">H", etype) + body


def udp(src, sport, dst, dport, data, vlan=None, macs=(MAC_A, MAC_B)):
    return eth(*macs, 0x0800, ip(src, dst, 17, struct.pack(">HHHH", sport, dport, 8 + len(data), 0) + data), vlan)


class Tcp:
    def __init__(self, client, server, port):
        self.ends = {True: (client, 40000, server, port, MAC_A, MAC_B), False: (server, port, client, 40000, MAC_B, MAC_A)}
        self.seq = {True: 1000, False: 5000}

    def send(self, from_client, data, syn=False):
        src, sport, dst, dport, m1, m2 = self.ends[from_client]
        l4 = struct.pack(">HHIIBBHHH", sport, dport, self.seq[from_client], 0, 5 << 4, 0x02 if syn else 0x18, 8192, 0, 0) + data
        self.seq[from_client] += len(data) + syn
        return eth(m1, m2, 0x0800, ip(src, dst, 6, l4))


def doip(kind, body):
    return struct.pack(">BBHI", 0x02, 0xFD, kind, len(body)) + body


def someip(service, method, mtype, body, session=1):
    return struct.pack(">HHIHHBBBB", service, method, 8 + len(body), 0, session, 1, 1, mtype, 0) + body


def write_pcap(path, packets, pcapng=False):
    with open(path, "wb") as f:
        if pcapng:
            f.write(struct.pack("<IIIHHqI", 0x0A0D0D0A, 28, 0x1A2B3C4D, 1, 0, -1, 28))
            f.write(struct.pack("<IIHHII", 1, 20, 1, 0, 0, 20))
        else:
            f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for t, raw in packets:
            if pcapng:
                us, pad = int(t * 1e6), -len(raw) % 4
                total = 32 + len(raw) + pad
                f.write(struct.pack("<IIIIIII", 6, total, 0, us >> 32, us & 0xFFFFFFFF, len(raw), len(raw)))
                f.write(raw + b"\0" * pad + struct.pack("<I", total))
            else:
                f.write(struct.pack("<IIII", int(t), int(t % 1 * 1e6), len(raw), len(raw)) + raw)
    return str(path)


def car_network():
    """Tester talks DoIP to a gateway, a BMW app talks HSFZ, an ECU offers a SOME/IP service and sends events."""
    out = []
    t = T0
    out.append((t, udp("10.0.0.1", 13400, "255.255.255.255", 13400,
                       doip(0x0004, b"WVWZZZE1ZMP012345" + bytes.fromhex("1010") + bytes(12) + b"\0\0"))))
    d = Tcp("10.0.0.9", "10.0.0.1", 13400)
    out.append((t + 0.1, d.send(True, b"", syn=True)))
    out.append((t + 0.1, d.send(False, b"", syn=True)))
    out.append((t + 0.2, d.send(True, doip(0x0005, bytes.fromhex("0E8000") + bytes(4)))))
    out.append((t + 0.3, d.send(False, doip(0x0006, bytes.fromhex("0E80101010") + bytes(4)))))
    for k in range(5):
        tk = t + 1 + k
        request = doip(0x8001, bytes.fromhex("0E804076") + bytes.fromhex("22028C"))
        out.append((tk, d.send(True, request[:5])))            # split over two segments
        second = d.send(True, request[5:])
        out.append((tk + 0.001, second))
        out.append((tk + 0.002, second))                       # retransmission
        out.append((tk + 0.01, d.send(False, doip(0x8002, bytes.fromhex("40760E8000")))))
        answer = bytes.fromhex("62028C") + bytes([0xA0 + k, 0x11])
        out.append((tk + 0.02, d.send(False, doip(0x8001, bytes.fromhex("40760E80") + answer))))
    h = Tcp("10.0.0.9", "10.0.0.2", 6801)
    out.append((t + 7, h.send(True, struct.pack(">IH", 5, 1) + bytes.fromhex("F107") + bytes.fromhex("22DDBC"))))
    out.append((t + 7.01, h.send(False, struct.pack(">IH", 5, 2) + bytes.fromhex("F107") + bytes.fromhex("22DDBC"))))
    out.append((t + 7.02, h.send(False, struct.pack(">IH", 13, 1) + bytes.fromhex("07F1") + bytes.fromhex("62DDBC1F3E1F401F3C0102"))))
    offer = bytes([0x01, 0, 0, 0x10]) + struct.pack(">HHB", 0x1234, 1, 1) + (3).to_bytes(3, "big") + struct.pack(">I", 7)
    option = struct.pack(">HBB", 9, 0x04, 0) + socket.inet_aton("10.0.0.3") + bytes([0, 17]) + struct.pack(">H", 30501)
    sd = bytes([0xC0, 0, 0, 0]) + struct.pack(">I", len(offer)) + offer + struct.pack(">I", len(option)) + option
    out.append((t + 0.5, udp("10.0.0.3", 30490, "224.224.224.245", 30490, someip(0xFFFF, 0x8100, 0x02, sd), vlan=10)))
    for k in range(100):
        value = 2000 + int(1500 * math.sin(k / 15))
        body = struct.pack(">HBB", value, k & 0xFF, 7)
        out.append((t + 1 + k * 0.05, udp("10.0.0.3", 30501, "239.0.0.1", 30501, someip(0x1234, 0x8001, 0x02, body, k), vlan=10)))
    out.append((t + 2, eth(MAC_B, bytes.fromhex("0180c200000e"), 0x88F7, bytes(34))))
    return sorted(out, key=lambda x: x[0])


@pytest.mark.parametrize("pcapng", [False, True])
def test_ethernet_recording(tmp_path, pcapng):
    a = analyse.load(write_pcap(tmp_path / "netz.pcap", car_network(), pcapng), KnownIndex(load_all()))
    convs = {c.request.hex(): c for c in a.sniffer.conversations}
    d = convs["22028c"]                                            # DoIP, with logical addresses
    assert (d.tx, d.target, d.ecu, d.count) == (0x0E80, 0x4076, 0x4076, 5)
    assert [x.data.hex() for x in d.answers] == [f"{0xA0 + k:02x}11" for k in range(5)]
    h = convs["22ddbc"]                                            # HSFZ like on the BMW CAN, so profiles know it
    assert (h.tx, h.target, h.ecu) == (0x6F1, 0x07, 0x607) and h.known
    s = a.streams["SOME/IP 1234.8001 event"]
    info = analyse.analyse_stream(s)
    assert len(s.times) == 100 and info.pattern == "SSZ." and info.fields[0].order == "BE"
    assert a.offers[("10.0.0.3", 0x1234, 1)]["ends"] == {"10.0.0.3:30501/udp"}
    assert a.vlans[10][5] == 101
    text = analyse.report(a)
    assert "DoIP: vehicle 10.0.0.1 announces itself, VIN WVWZZZE1ZMP…, address 1010" in text and "012345" not in text
    assert "DoIP: gateway 1010 (10.0.0.1): routing accepted" in text
    assert "| 10.0.0.9:40000 ⇄ 10.0.0.1:13400 | TCP DoIP |" in text
    assert "| 1234 | 0001 | 1.7 | 10.0.0.3 | 10.0.0.3:30501/udp | 1 |" in text
    assert "### SOME/IP 1234.8001 event" in text and "A–B number 16 bit BE" in text
    assert "### response to E80[4076] → 4076  22 02 8C" in text
    assert "gPTP/PTP" in text and "VLANs: 10 (101 packets, priority 5)" in text


def test_can_recorded_with_tcpdump(tmp_path):
    path = tmp_path / "can.pcap"
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 227))
        for k, (can_id, data) in enumerate([(0x123, b"\x01\x02"), (0x98DAF110, b"\x02\x10\x03"), (0x123, b"\x01\x03")]):
            raw = struct.pack(">IB3x", can_id, len(data)) + data.ljust(8, b"\0")
            f.write(struct.pack("<IIII", int(T0) + k, 0, len(raw), len(raw)) + raw)
    a = analyse.load(str(path))
    assert a.can[(0x123, False)].payloads == [b"\x01\x02", b"\x01\x03"] and (0x18DAF110, True) in a.can


def test_tcp_stream_survives_reordering():
    streams = pcap.TcpStreams()

    def seg(seq, data):
        return pcap.Packet(0.0, 0, src="a", dst="b", proto="tcp", sport=1, dport=2, seq=seq, payload=data)

    got = streams.add(seg(100, b"ab")) + streams.add(seg(104, b"ef")) + streams.add(seg(102, b"cd")) + streams.add(seg(102, b"cd"))
    assert got == b"abcdef"


@pytest.mark.skipif(not hasattr(socket, "AF_PACKET"), reason="Linux only")
def test_recording_from_an_interface(tmp_path):
    path = tmp_path / "lo.pcap"
    try:
        source = pcap.EthSource("lo", str(path))
    except OSError:
        pytest.skip("needs root")

    def talk():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for k in range(20):
                s.sendto(someip(0x4321, 0x8002, 0x02, bytes([k, 0, 9])), ("127.0.0.1", 30555))
                time.sleep(0.01)
        time.sleep(0.3)
        source.close()

    threading.Thread(target=talk).start()
    for _ in source.frames():
        pass
    a = analyse.load(str(path))
    assert len(a.streams["SOME/IP 4321.8002 event"].times) >= 20


def test_frames_fed_directly():
    a = analyse.Analysis()
    for k in range(40):
        a.can_frame(Frame(T0 + k * 0.1, 0x200, False, bytes([k * 37 & 0xFF, 5])))
    a.finish()
    assert "| 200 | 40 | 100 ms | 2 | `Z.` |" in analyse.report(a)
