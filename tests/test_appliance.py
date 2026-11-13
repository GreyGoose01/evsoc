import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest

from evsoc import config
from evsoc.appliance import Appliance, serve
from evsoc.cli import open_adapter


@pytest.fixture
def device(tmp_path):
    path = tmp_path / "config.json"
    config.save(config.merged(config.DEFAULTS, {"adapter": "auto", "state_file": str(tmp_path / "state.json"),
                                                "monitor": {"interval": 10}}), path)
    app = Appliance(path, open_adapter, log=lambda _m: None, adapter_urls=["box:mock://corsa-e"])
    server = serve(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    app.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield app, base, path
    app.stop()
    server.shutdown()
    for extra in server.extra:
        extra.shutdown()
    server.server_close()


class Client:
    def __init__(self, base):
        self.base, self.cookie = base, None

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers={"Cookie": self.cookie} if self.cookie else {})
        return self._open(req)

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json", "X-Evsoc": "1"}
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        return self._open(urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=h, method="POST"))

    def _open(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.headers.get("Set-Cookie"):
                    self.cookie = r.headers["Set-Cookie"].split(";")[0]
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


def wait_for(fn, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_runs_without_any_setup(device):
    app, base, _ = device
    c = Client(base)
    assert wait_for(lambda: (c.get("/api/state")[1]["soc"] or 0) > 79)
    state = c.get("/api/state")[1]
    assert state["adapter"]["ok"] and state["status"] == "awake"
    assert state["vehicle"].startswith("Peugeot")            # vehicle detected by itself
    assert c.get("/api/v1/state")[0] == 200                  # pull endpoint for other systems
    with urllib.request.urlopen(base + "/") as r:
        assert "State of charge" in r.read().decode()


def test_setup_needs_login_and_first_pin(device):
    app, base, path = device
    c = Client(base)
    assert c.get("/api/setup")[0] == 401
    assert c.post("/api/setup/save", {})[0] == 401
    assert c.post("/api/login", {"code": "falsch"})[0] == 400
    assert c.post("/api/login", {"code": app.setup_code})[0] == 200
    view = c.get("/api/setup")[1]
    assert view["needs_pin"] and "pin_hash" not in view["config"]
    assert c.post("/api/setup/pin", {"pin": "12"})[0] == 400
    assert c.post("/api/setup/pin", {"pin": "4711"})[0] == 200
    assert app.setup_code is None
    assert config.check_pin("4711", config.load(path)["pin_hash"])
    c2 = Client(base)
    assert c2.post("/api/login", {"code": "4711"})[0] == 200


def test_post_needs_custom_header_and_host(device):
    app, base, _ = device
    c = Client(base)
    assert c.post("/api/login", {"code": app.setup_code}, headers={"X-Evsoc": "0"})[0] == 403
    req = urllib.request.Request(base + "/api/state", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403


def test_test_vehicle_and_save(device):
    app, base, path = device
    c = Client(base)
    c.post("/api/login", {"code": app.setup_code})
    c.post("/api/setup/pin", {"pin": "4711"})
    status, result = c.post("/api/setup/test-vehicle", {"profile": "evsoc_stellantis_ecmp"})
    assert status == 200 and result["soc"] == pytest.approx(79.96, abs=0.01)
    status, _ = c.post("/api/setup/save", {
        "vehicle": {"profile": "evsoc_stellantis_ecmp", "label": "Opel Corsa-e"},
        "outputs": {"mqtt": {"enabled": True, "url": "mqtt://u:geheim@127.0.0.1:1/x"}, "webhook": {"enabled": False, "url": ""}},
        "monitor": {"interval": 30},
    })
    assert status == 200
    saved = config.load(path)
    assert saved["vehicle"]["label"] == "Opel Corsa-e" and saved["monitor"]["interval"] == 30
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    view = c.get("/api/setup")[1]
    assert view["config"]["outputs"]["mqtt"]["url"] == "mqtt://u:***@127.0.0.1:1/x"
    # saving the masked value again keeps the real password
    c.post("/api/setup/save", {"outputs": view["config"]["outputs"]})
    assert config.load(path)["outputs"]["mqtt"]["url"] == "mqtt://u:geheim@127.0.0.1:1/x"
    assert wait_for(lambda: c.get("/api/state")[1]["vehicle"] == "Opel Corsa-e")


def test_nominal_battery_capacity_for_soh(device):
    app, base, path = device
    c = Client(base)
    c.post("/api/login", {"code": app.setup_code})
    c.post("/api/setup/pin", {"pin": "4711"})
    status, result = c.post("/api/setup/save", {"vehicle": {"battery_kwh": "500"}})
    assert status == 400 and "implausible" in result["error"]
    status, _ = c.post("/api/setup/save", {"vehicle": {"profile": "evsoc_stellantis_ecmp", "battery_kwh": "46.3"}})
    assert status == 200 and config.load(path)["vehicle"]["battery_kwh"] == 46.3
    status, _ = c.post("/api/setup/save", {"vehicle": {"battery_kwh": ""}})
    assert status == 200 and config.load(path)["vehicle"]["battery_kwh"] is None


def test_webhook_test_reports_error(device):
    app, base, _ = device
    c = Client(base)
    c.post("/api/login", {"code": app.setup_code})
    status, r = c.post("/api/setup/test-output", {"kind": "webhook", "url": "http://127.0.0.1:9/x"})
    assert status == 200 and r["ok"] is False and "connection" in r["error"]


def test_login_rate_limit(device):
    app, base, _ = device
    app._fails.extend([time.monotonic()] * 10)
    status, err = Client(base).post("/api/login", {"code": app.setup_code})
    assert status == 400 and "failed attempts" in err["error"]


def test_config_masking_roundtrip():
    cfg = config.merged(config.DEFAULTS, {"outputs": {"mqtt": {"url": "mqtts://anna:p%40ss@broker:8883/a/b"}}})
    pub = config.public(cfg)
    assert pub["outputs"]["mqtt"]["url"] == "mqtts://anna:***@broker:8883/a/b"
    moved = config.apply_public(cfg, {"outputs": {"mqtt": {"url": "mqtts://anna:***@neu:8883/a/b"}}})
    assert moved["outputs"]["mqtt"]["url"] == "mqtts://anna:p%40ss@neu:8883/a/b"


def test_state_file_is_throttled(tmp_path):
    from evsoc.monitor import State, ThrottledFileSink
    path = tmp_path / "s.json"
    sink = ThrottledFileSink(str(path), every=900)
    sink.publish(State(status="awake", soc=50.0))
    first = path.stat().st_mtime_ns
    time.sleep(0.01)
    sink.publish(State(status="awake", soc=50.0, checked="x"))   # only the check time changed
    assert path.stat().st_mtime_ns == first
    sink.publish(State(status="asleep", soc=50.0))
    assert json.loads(path.read_text())["status"] == "asleep"
