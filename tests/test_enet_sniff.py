import socket
import struct
import threading

import pytest

from evsoc import enet
from evsoc.cli import main
from evsoc.enet_sniff import EnetProxySource, hsfz_frames
from evsoc.profiles import load_all
from evsoc.sniff import KnownIndex, Sniffer

LONG = bytes.fromhex("62DFA0" "212521BB2162959E95E295BD07CE0896081BFFFFFFFF2A33153015CC1560FFFFFFFFFFFF2A33")


class Gateway(threading.Thread):
    """HSFZ server like a BMW gateway behind an ENET adapter: ack, then the answer."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]

    def run(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        with conn:
            while True:
                hdr = conn.recv(6)
                if len(hdr) < 6:
                    return
                length, _ctrl = struct.unpack(">IH", hdr)
                body = conn.recv(length)
                src, dst, uds = body[0], body[1], body[2:]
                conn.sendall(struct.pack(">IH", len(body), 0x0002) + body)
                answers = {bytes.fromhex("22DDBC"): bytes.fromhex("62DDBC024C03A60069"), bytes.fromhex("22DFA0"): LONG}
                resp = answers.get(uds, bytes([0x7F, uds[0], 0x31])) if dst == 0x07 else bytes([0x7F, uds[0], 0x11])
                conn.sendall(struct.pack(">IH", len(resp) + 2, 1) + bytes([dst, src]) + resp)


def ask(sock, dst, uds):
    sock.sendall(struct.pack(">IH", len(uds) + 2, 1) + bytes([0xF4, dst]) + uds)
    while True:
        length, ctrl = struct.unpack(">IH", sock.recv(6))
        body = b""
        while len(body) < length:
            body += sock.recv(length - len(body))
        if ctrl == 1:
            return body[2:]


@pytest.fixture
def proxy(monkeypatch):
    gw = Gateway()
    gw.start()
    monkeypatch.setattr(enet, "HSFZ_PORT", gw.port)
    src = EnetProxySource("127.0.0.1", listen="127.0.0.1", port=0, discovery=False, log=lambda _m: None)
    yield src
    src.close()
    gw.srv.close()


def test_hsfz_frames_roundtrip_through_sniffer():
    s = Sniffer()
    for f in hsfz_frames(0.0, 0xF4, 0x07, bytes.fromhex("22DFA0"), True) + hsfz_frames(0.1, 0x07, 0xF4, LONG, False):
        s.feed(f)
    (c,) = s.conversations
    assert (c.tx, c.target, c.ecu) == (0x6F1, 0x07, 0x607)
    assert c.answers[-1].payload == LONG


def test_proxy_forwards_and_reads_along(proxy):
    with socket.create_connection(("127.0.0.1", proxy.port)) as app:
        assert ask(app, 0x07, bytes.fromhex("22DDBC")) == bytes.fromhex("62DDBC024C03A60069")
        assert ask(app, 0x07, bytes.fromhex("22DFA0")) == LONG
        assert ask(app, 0x07, bytes.fromhex("22DD68"))[:1] == b"\x7f"
    s = Sniffer(KnownIndex(load_all()))
    for f in proxy.frames():
        if f is None:
            break
        s.feed(f)
    s.tick(float("inf"))
    c = next(c for c in s.conversations if c.request == bytes.fromhex("22DDBC"))
    assert c.ecu == 0x607 and c.target == 0x07
    soc = [v for v in c.known_values() if v.profile == "evsoc_bmw_sme" and v.field == "soc"]
    assert soc and soc[0].value == pytest.approx(58.8)
    assert next(c for c in s.conversations if c.request == bytes.fromhex("22DFA0")).answers[-1].payload == LONG
    assert next(c for c in s.conversations if c.request == bytes.fromhex("22DD68")).nrc[0x31] == 1


def test_proxy_answers_vehicle_search(monkeypatch):
    gw = Gateway()
    gw.start()
    monkeypatch.setattr(enet, "HSFZ_PORT", gw.port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    monkeypatch.setattr(enet, "DISCOVERY_PORT", free)
    monkeypatch.setattr(EnetProxySource, "_upstream_ident", lambda self: None)
    monkeypatch.setattr(EnetProxySource, "_read_vin", lambda self: "WBY71AW000F000001")
    src = EnetProxySource("localhost", listen="127.0.0.1", port=0, log=lambda _m: None)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as app:
            app.settimeout(2)
            app.sendto(struct.pack(">IH", 0, 0x11), ("127.0.0.1", free))
            data, _ = app.recvfrom(1024)
        assert b"BMWVINWBY71AW000F000001" in data and struct.unpack(">IH", data[:6])[1] == 0x11
        assert enet.discover(1.0, ["127.0.0.1"]) == [("127.0.0.1", "WBY71AW000F000001")]
    finally:
        src.close()
        gw.srv.close()


def test_cli_points_enet_users_to_the_proxy(capsys):
    assert main(["sniff", "-a", "enet://auto"]) == 1
    assert "enet-proxy://" in capsys.readouterr().err
