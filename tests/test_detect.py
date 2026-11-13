import pytest

from evsoc import detect
from evsoc.elm import AdapterError


class FakeAdapter:
    version = "fake"


def test_enet_is_tried_last(monkeypatch):
    monkeypatch.setattr(detect, "usb_serial_ports", lambda: [{"device": "/dev/ttyUSB0"}, {"device": "/dev/ttyACM0"}])
    monkeypatch.setattr(detect, "socketcan_interfaces", lambda: ["can0"])
    assert detect.candidate_urls() == ["box:/dev/ttyACM0", "/dev/ttyACM0", "box:/dev/ttyUSB0", "/dev/ttyUSB0",
                                       "can://socketcan/can0", "enet://auto"]


def test_finds_bmw_over_enet_when_nothing_else_answers(monkeypatch):
    """Pi with only the UCSI-3000 (WLAN or LAN): no USB, no CAN, the car comes via ENET."""
    monkeypatch.setattr(detect, "usb_serial_ports", lambda: [])
    monkeypatch.setattr(detect, "socketcan_interfaces", lambda: [])
    opened = []

    def open_adapter(url, _log):
        opened.append(url)
        if url != "enet://auto":
            raise AdapterError("nichts")
        return FakeAdapter()

    url, adapter = detect.find_adapter(open_adapter, log=lambda _m: None)
    assert url == "enet://auto" and isinstance(adapter, FakeAdapter)


def test_error_names_enet(monkeypatch):
    monkeypatch.setattr(detect, "usb_serial_ports", lambda: [])
    monkeypatch.setattr(detect, "socketcan_interfaces", lambda: [])

    def open_adapter(url, _log):
        raise AdapterError("No BMW found over ENET")

    with pytest.raises(AdapterError, match="ENET"):
        detect.find_adapter(open_adapter, log=lambda _m: None)
