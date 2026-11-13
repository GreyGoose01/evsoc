import threading
import uuid

import pytest

can = pytest.importorskip("can")

from evsoc.canbus import CanAdapter  # noqa: E402
from evsoc.elm import isotp_segment  # noqa: E402
from evsoc.mock import BROADCAST, VEHICLES  # noqa: E402
from evsoc.profiles import load_all  # noqa: E402
from evsoc.reader import autodetect, read, run_init  # noqa: E402


class SimEcu(threading.Thread):
    """Answers diagnostic requests on a virtual CAN bus like the cars in evsoc.mock."""

    def __init__(self, channel: str, vehicle: str):
        super().__init__(daemon=True)
        self.bus = can.Bus(interface="virtual", channel=channel)
        self.table = VEHICLES.get(vehicle, {})
        self.broadcast = BROADCAST.get(vehicle, {})
        self.stop = threading.Event()

    def _lookup(self, msg):
        data = bytes(msg.data)
        for (header, cea, request), (resp_id, payload) in self.table.items():
            want = int(header, 16)
            match = (msg.arbitration_id & 0xFFFFFF) == want if len(header) == 6 else msg.arbitration_id == want
            if not match:
                continue
            body = data[1:] if cea is not None and data and data[0] == cea else data
            if cea is not None and data[:1] != bytes([cea]):
                continue
            if body and body[0] >> 4 == 0 and body[1 : 1 + body[0]] == bytes.fromhex(request):
                tester = int(header, 16) & 0xFF if cea is not None else None
                return resp_id, bytes.fromhex(payload), tester
        return None

    def _send(self, arb: str, data: bytes):
        self.bus.send(can.Message(arbitration_id=int(arb, 16), data=data, is_extended_id=len(arb) == 8))

    def run(self):
        while not self.stop.is_set():
            for can_id, payload in self.broadcast.items():
                self._send(can_id, bytes.fromhex(payload))
            msg = self.bus.recv(0.02)
            if msg is None:
                continue
            hit = self._lookup(msg)
            if hit is None:
                continue
            resp_id, payload, tester = hit
            frames = isotp_segment(payload, tester)
            self._send(resp_id, frames[0])
            if len(frames) > 1:
                fc = self.bus.recv(1.0)  # wait for the tester's flow control
                assert fc is not None and (bytes(fc.data)[1 if tester is not None else 0] >> 4) == 3
                for f in frames[1:]:
                    self._send(resp_id, f)

    def close(self):
        self.stop.set()
        self.join(1)
        self.bus.shutdown()


@pytest.fixture
def car(request):
    channel = f"evsoc-{uuid.uuid4().hex}"
    ecu = SimEcu(channel, request.param)
    ecu.start()
    adapter = CanAdapter("virtual", channel, timeout=0.5, bus=can.Bus(interface="virtual", channel=channel))
    yield adapter
    adapter.close()
    ecu.close()


@pytest.mark.parametrize("car", ["corsa-e"], indirect=True)
def test_single_frame(car):
    car.at("ATSP6")
    car.at("ATSH6B4")
    car.at("ATCRA694")
    r = car.request("22D410")
    assert r.ecu == "694" and r.payload == bytes.fromhex("62D4109FEB")


@pytest.mark.parametrize("car", ["ioniq5"], indirect=True)
def test_multi_frame_with_flow_control(car):
    p = load_all()["obdb_hyundai_ioniq_5"]
    run_init(car, p)
    r = read(car, p, ["soc_display"])
    assert r.values["soc_display"].value == 79.0


@pytest.mark.parametrize("car", ["bmw-i3"], indirect=True)
def test_bmw_extended_addressing(car):
    p = load_all()["evsoc_bmw_sme"]
    run_init(car, p)
    r = read(car, p, ["soc", "soc_display"])
    assert r.values["soc"].value == pytest.approx(58.8)


@pytest.mark.parametrize("car", ["id4"], indirect=True)
def test_29bit_autodetect(car):
    det = autodetect(car, load_all(), car="ID.4", log=lambda _m: None)
    assert det and det.profile.name == "evsoc_vw_meb"


@pytest.mark.parametrize("car", ["tesla-m3"], indirect=True)
def test_listen(car):
    p = load_all()["evsoc_tesla_model3y"]
    run_init(car, p)
    assert read(car, p, ["soc_display"]).values["soc_display"].value == pytest.approx(80.0)
