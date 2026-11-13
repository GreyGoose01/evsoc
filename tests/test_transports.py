"""The byte pipes to real adapters, each against a stand-in for the other end: a pseudo terminal
(USB/Bluetooth serial), a local TCP socket (WiFi adapters) and a replaced `bleak` module (BLE)."""

import os
import socket
import sys
import threading
import types

import pytest

from evsoc.transports import BleTransport, LoggingTransport, SerialTransport, TcpTransport, TransportError


def read_all(transport, want: bytes, tries: int = 20) -> bytes:
    got = b""
    for _ in range(tries):
        got += transport.read(0.2)
        if want in got:
            break
    return got


# -- serial ------------------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "posix", reason="braucht Pseudo-Terminals")
def test_serial_reads_and_writes_through_a_pseudo_terminal():
    master, slave = os.openpty()
    t = SerialTransport(os.ttyname(slave), 115200)
    try:
        t.write(b"ATZ\r")
        assert os.read(master, 16) == b"ATZ\r"
        os.write(master, b"ELM327 v1.5\r>")
        assert read_all(t, b">") == b"ELM327 v1.5\r>"
        assert t.read(0.05) == b""  # nothing waiting: empty, no exception
    finally:
        t.close()
        os.close(master)
        os.close(slave)


def test_serial_missing_port_gives_a_readable_error():
    with pytest.raises(TransportError, match="Cannot open /dev/does-not-exist"):
        SerialTransport("/dev/does-not-exist")


# -- tcp ---------------------------------------------------------------------------------------

@pytest.fixture
def tcp_adapter():
    """A WiFi adapter stand-in: answers every command with 'OK', closes on 'BYE'."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    seen = []

    def serve():
        conn, _ = srv.accept()
        with conn:
            while True:
                data = conn.recv(256)
                if not data:
                    return
                seen.append(data)
                if data.startswith(b"BYE"):
                    return
                conn.sendall(b"OK\r>")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield srv.getsockname()[1], seen
    srv.close()
    thread.join(2)


def test_tcp_round_trip_timeout_and_closed_connection(tcp_adapter):
    port, seen = tcp_adapter
    t = TcpTransport("127.0.0.1", port)
    try:
        t.write(b"ATI\r")
        assert read_all(t, b">") == b"OK\r>"
        assert t.read(0.05) == b""  # timeout is not an error
        t.write(b"BYE\r")
        with pytest.raises(TransportError, match="closed the connection"):
            for _ in range(20):
                t.read(0.2)
    finally:
        t.close()
    assert seen == [b"ATI\r", b"BYE\r"]


def test_tcp_refused_connection_gives_a_readable_error():
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    with pytest.raises(TransportError, match=f"No connection to 127.0.0.1:{port}"):
        TcpTransport("127.0.0.1", port, connect_timeout=1)


# -- bluetooth le ------------------------------------------------------------------------------

FFF0, FFF1, FFF2 = (f"0000fff{n}-0000-1000-8000-00805f9b34fb" for n in "012")


class FakeChar:
    def __init__(self, uuid, *properties):
        self.uuid, self.properties = uuid, list(properties)


class FakeService:
    def __init__(self, uuid, *characteristics):
        self.uuid, self.characteristics = uuid, list(characteristics)


class FakeServices(list):
    def get_service(self, uuid):
        return next((s for s in self if s.uuid == uuid), None)

    def get_characteristic(self, uuid):
        return next((c for s in self for c in s.characteristics if c.uuid == uuid), None)


def install_bleak(monkeypatch, services, devices=("AA:BB:CC:DD:EE:FF", "OBDLink CX")):
    """Replaces `bleak` by a dongle that echoes what is written, in 20-byte pieces."""
    state = types.SimpleNamespace(written=[], notify_uuid=None, disconnected=False)
    address, name = devices if devices else (None, None)
    device = types.SimpleNamespace(address=address, name=name)

    class BleakScanner:
        @staticmethod
        async def find_device_by_address(target, timeout):
            return device if target == address else None

        @staticmethod
        async def find_device_by_filter(match, timeout):
            return device if address and match(device, None) else None

    class BleakClient:
        def __init__(self, dev):
            self.services = services

        async def connect(self):
            pass

        async def start_notify(self, uuid, callback):
            state.notify_uuid, self._callback = uuid, callback

        async def write_gatt_char(self, uuid, data, response):
            state.written.append((uuid, bytes(data)))
            self._callback(None, bytearray(data))

        async def disconnect(self):
            state.disconnected = True

    monkeypatch.setitem(sys.modules, "bleak", types.SimpleNamespace(BleakScanner=BleakScanner, BleakClient=BleakClient))
    return state


def test_ble_known_dongle_found_by_name_and_long_writes_are_split(monkeypatch):
    services = FakeServices([FakeService(FFF0, FakeChar(FFF1, "notify"), FakeChar(FFF2, "write"))])
    state = install_bleak(monkeypatch, services)
    t = BleTransport("obdlink", scan_timeout=0.1)  # part of the name, any case
    try:
        assert state.notify_uuid == FFF1
        t.write(b"0123456789" * 5)
        assert [len(d) for _, d in state.written] == [20, 20, 10]
        assert {u for u, _ in state.written} == {FFF2}
        assert t.read(1) == b"0123456789" * 5
        assert t.read(0.05) == b""
    finally:
        t.close()
    assert state.disconnected


def test_ble_unknown_dongle_uses_first_service_with_notify_and_write(monkeypatch):
    services = FakeServices([
        FakeService("1800", FakeChar("2a00", "read")),
        FakeService("abcd", FakeChar("n1", "indicate"), FakeChar("w1", "write-without-response")),
    ])
    state = install_bleak(monkeypatch, services)
    t = BleTransport("AA:BB:CC:DD:EE:FF", scan_timeout=0.1)  # by address
    try:
        t.write(b"ATZ\r")
        assert state.notify_uuid == "n1" and state.written == [("w1", b"ATZ\r")]
    finally:
        t.close()


def test_ble_errors(monkeypatch):
    install_bleak(monkeypatch, FakeServices(), devices=None)
    with pytest.raises(TransportError, match="not found"):
        BleTransport("OBDLink", scan_timeout=0.1)
    install_bleak(monkeypatch, FakeServices([FakeService("1800", FakeChar("2a00", "read"))]))
    with pytest.raises(TransportError, match="No serial BLE interface"):
        BleTransport("OBDLink", scan_timeout=0.1)
    monkeypatch.setitem(sys.modules, "bleak", None)  # not installed
    with pytest.raises(TransportError, match="bleak missing"):
        BleTransport("OBDLink")


# -- logging -----------------------------------------------------------------------------------

def test_logging_transport_writes_both_directions(tmp_path):
    class Inner:
        closed = False
        answers = [b"41 5B 80\r\n>", b""]

        def write(self, data):
            self.sent = data

        def read(self, timeout):
            return self.answers.pop(0)

        def close(self):
            self.closed = True

    inner, path = Inner(), tmp_path / "verkehr.log"
    t = LoggingTransport(inner, str(path))
    t.write(b"015B\r")
    assert t.read(1) == b"41 5B 80\r\n>"
    assert t.read(1) == b""  # empty reads are not logged
    t.close()
    lines = [line.split(" ", 1)[1] for line in path.read_text().splitlines()]
    assert lines == ["> 015B\\r", "< 41 5B 80\\r\\n>"]
    assert inner.sent == b"015B\r" and inner.closed
