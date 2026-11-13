import json
import threading
import urllib.request

import pytest

from evsoc import wired
from evsoc.cli import main, open_adapter
from evsoc.gui import serve


@pytest.fixture
def usb(monkeypatch):
    monkeypatch.setattr(wired, "usb_serial_ports", lambda: [{"device": "/dev/ttyUSB0", "description": "OBDLink SX", "vid": 0x0403, "pid": 0x6015}])


@pytest.mark.parametrize("url", ["mock://corsa-e", "can://socketcan/can0", "enet://auto", "/dev/ttyUSB0",
                                 "serial:///dev/ttyUSB0?baud=115200", "box:/dev/ttyUSB0", "box:mock://leaf"])
def test_wired_urls_allowed(usb, url):
    wired.check_url(url)


@pytest.mark.parametrize("url", ["ble://OBDLink CX", "tcp://192.168.0.10:35000", "box:tcp://192.168.4.1:35000",
                                 "/dev/rfcomm0", "/dev/cu.OBDLinkMXPlus"])
def test_radio_urls_refused(usb, url):
    with pytest.raises(wired.WiredOnlyError):
        wired.check_url(url)


def test_resolve_host(monkeypatch):
    assert wired.resolve_host("127.0.0.1") == "127.0.0.1"
    assert wired.resolve_host("pi.local") == "pi.local"
    monkeypatch.setattr(wired, "interface_ipv4", lambda name: "192.168.2.20" if name == "eth0" else None)
    assert wired.resolve_host("eth0") == "192.168.2.20"
    with pytest.raises(wired.WiredOnlyError, match="cable plugged in"):
        wired.resolve_host("eth9")


def test_cli_wired_flag(capsys, monkeypatch):
    monkeypatch.delenv("EVSOC_NUR_KABEL", raising=False)
    assert main(["--wired-only", "read", "-a", "ble://OBDLink", "-p", "evsoc_stellantis_ecmp"]) == 1
    assert "wireless connection" in capsys.readouterr().err
    assert main(["--wired-only", "read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--json"]) == 0


def test_gui_wired_mode(usb):
    server = serve(open_adapter, port=0, open_browser=False, token="t", wired_only=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Evsoc-Token": "t", "Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        assert call("/api/info")[1]["wired_only"] is True
        devs = call("/api/devices")[1]
        assert all(not e["url"].startswith(("tcp://", "ble://")) for e in devs["examples"])
        assert devs["serial"][0]["url"] == "/dev/ttyUSB0"
        status, err = call("/api/connect", {"url": "ble://OBDLink CX"})
        assert status == 400 and "wireless connection" in err["error"]
        assert call("/api/connect", {"url": "mock://corsa-e"})[0] == 200
        assert call("/api/devices/ble")[1]["ble_error"]
    finally:
        server.session.disconnect()
        server.shutdown()
        for extra in server.extra:
            extra.shutdown()
        server.server_close()
