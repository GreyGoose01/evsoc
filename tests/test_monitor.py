import json
import sys
import types
from datetime import datetime, timedelta

import pytest

from evsoc.elm import ElmAdapter
from evsoc.mock import MockElmTransport
from evsoc.monitor import FileSink, Monitor, MqttSink, State, load_state, parse_times
from evsoc.profiles import load_all


class Collect:
    def __init__(self):
        self.states = []

    def publish(self, state):
        self.states.append(json.loads(state.to_json()))

    def close(self):
        pass


def make(transport, **kw):
    def connect():
        a = ElmAdapter(transport)
        a.reset()
        return a
    sink = Collect()
    m = Monitor(connect, load_all(), [sink], profile=load_all()["evsoc_stellantis_ecmp"], log=lambda _m: None, **kw)
    return m, sink


def requests_sent(transport):
    return [c for c in transport.sent if not c.startswith("AT")]


def test_reads_while_awake_and_keeps_quiet_while_asleep():
    car = MockElmTransport("corsa-e", voltage=14.1)
    m, sink = make(car)
    assert m.tick() == 60
    assert sink.states[-1]["status"] == "awake"
    assert sink.states[-1]["soc"] == pytest.approx(79.96, abs=0.01)
    stamp = sink.states[-1]["soc_updated"]

    car.voltage = 12.4  # car switched off, DC/DC converter stops
    before = len(requests_sent(car))
    assert m.tick() == 300
    state = sink.states[-1]
    assert state["status"] == "asleep"
    assert len(requests_sent(car)) == before          # not a single request on the bus
    assert state["soc"] == pytest.approx(79.96, abs=0.01)  # last value is kept ...
    assert state["soc_updated"] == stamp                 # ... with its original timestamp


class Clock:
    def __init__(self, start="2026-10-08T02:00:00+02:00"):
        self.now = datetime.fromisoformat(start)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def sleeping(wakeable=False, voltage=12.5, **kw):
    car = MockElmTransport("corsa-e", voltage=voltage, wakeable=wakeable)
    clock = Clock()
    m, sink = make(car, clock=clock, pause=lambda _s: None, **kw)
    return car, clock, m, sink


def test_wake_every_24h_only_when_value_is_old():
    car, clock, m, sink = sleeping(wakeable=True, wake_every=24)
    m.state.soc_updated = (clock.now - timedelta(hours=2)).isoformat()
    m.tick()
    assert not requests_sent(car)                       # value only 2 h old: let it sleep
    clock.advance(hours=23)
    m.tick()
    assert sink.states[-1]["status"] == "woken"       # now older than 24 h
    assert sink.states[-1]["last_wake_result"].startswith("ok after")  # first request woke the gateway
    before = len(requests_sent(car))
    clock.advance(minutes=5)
    car._woken = False
    m.tick()
    assert len(requests_sent(car)) == before             # fresh value again: no second wake


def test_failed_wake_is_not_retried_until_next_period():
    car, clock, m, sink = sleeping(wakeable=False, wake_every=24)
    m.tick()
    assert sink.states[-1]["last_wake_result"].startswith("no answer after 3 attempts")
    before = len(requests_sent(car))
    clock.advance(hours=6)
    m.tick()
    assert len(requests_sent(car)) == before
    clock.advance(hours=19)
    m.tick()
    assert len(requests_sent(car)) > before


def test_wake_at_fixed_time():
    car, clock, m, sink = sleeping(wakeable=True, wake_at=parse_times(["05:30"]))
    m.tick()                                            # 02:00, first tick only sets the reference
    clock.advance(hours=3)                              # 05:00
    m.tick()
    assert not requests_sent(car)
    clock.advance(minutes=35)                           # 05:35: slot 05:30 passed
    m.tick()
    assert sink.states[-1]["status"] == "woken"


def test_never_wake_with_weak_12v_battery():
    car, clock, m, sink = sleeping(wakeable=True, voltage=12.0, wake_every=24)
    m.tick()
    assert not requests_sent(car)
    assert "not woken" in sink.states[-1]["last_wake_result"]


def test_warns_if_car_stays_awake_after_wake():
    car, clock, m, sink = sleeping(wakeable=True, wake_every=24)
    m.tick()
    assert sink.states[-1]["status"] == "woken"
    car.voltage = 13.8                                   # car does not go back to sleep
    clock.advance(minutes=31)
    m.tick()
    assert "still awake" in sink.states[-1]["note"]


def test_lost_connection_reconnects():
    car = MockElmTransport("corsa-e", voltage=14.0)
    calls = {"n": 0}

    def connect():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("adapter asleep")
        a = ElmAdapter(car)
        a.reset()
        return a

    sink = Collect()
    m = Monitor(connect, load_all(), [sink], profile=load_all()["evsoc_stellantis_ecmp"], log=lambda _m: None)
    m.tick()
    assert sink.states[-1]["status"] == "no connection"
    m.tick()
    assert sink.states[-1]["status"] == "awake"


def test_state_file_remembers_profile(tmp_path):
    path = tmp_path / "state.json"
    car = MockElmTransport("corsa-e", voltage=14.0)
    m, _ = make(car)
    m.sinks.append(FileSink(str(path)))
    m.tick()
    state = load_state(str(path))
    assert state.profile == "evsoc_stellantis_ecmp" and state.soc > 79
    m2 = Monitor(lambda: None, load_all(), [], state=state, log=lambda _m: None)
    assert m2.profile.name == "evsoc_stellantis_ecmp"


def test_publishes_soh_from_nominal_capacity():
    m, sink = make(MockElmTransport("id4"), battery_kwh=77)
    m.profile = load_all()["evsoc_vw_meb"]
    m.run(once=True)
    assert sink.states[-1]["values"]["soh"] == pytest.approx(95.325)


def test_autodetect_on_first_wake():
    car = MockElmTransport("bmw-i3", voltage=13.8)
    sink = Collect()

    def connect():
        a = ElmAdapter(car)
        a.reset()
        return a

    m = Monitor(connect, load_all(), [sink], log=lambda _m: None)
    m.tick()
    assert sink.states[-1]["profile"] == "evsoc_bmw_sme"


def test_mqtt_home_assistant_discovery(monkeypatch):
    published = {}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def username_pw_set(self, u, p): published["auth"] = (u, p)
        def will_set(self, *a, **kw): pass
        def connect_async(self, host, port): published["broker"] = (host, port)
        def loop_start(self): self.on_connect(self, None, None, None, None)
        def loop_stop(self): pass
        def disconnect(self): pass
        def publish(self, topic, payload, retain=False): published[topic] = payload
        def subscribe(self, topic): published["subscribed"] = topic

    mqtt = types.SimpleNamespace(Client=FakeClient, CallbackAPIVersion=types.SimpleNamespace(VERSION2=2))
    monkeypatch.setitem(sys.modules, "paho", types.SimpleNamespace(mqtt=types.SimpleNamespace(client=mqtt)))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.SimpleNamespace(client=mqtt))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", mqtt)

    sink = MqttSink("mqtt://user:geheim@ha.local:1883/evsoc/corsa", log=lambda _m: None)
    sink.publish(State(status="awake", soc=80.0))
    config = json.loads(published["homeassistant/sensor/evsoc_evsoc_corsa/soc/config"])
    assert config["device_class"] == "battery" and config["state_topic"] == "evsoc/corsa/state"
    assert json.loads(published["evsoc/corsa/state"])["soc"] == 80.0

    # reading on demand from outside: a button for Home Assistant and the command topic behind it
    button = json.loads(published["homeassistant/button/evsoc_evsoc_corsa/wake/config"])
    assert button["command_topic"] == "evsoc/corsa/cmd" == published["subscribed"] and button["payload_press"] == "wake"
    asked = []
    sink.on_command = asked.append
    message = types.SimpleNamespace(payload=b" Wake\n")
    sink._on_message(None, None, message)
    sink._on_message(None, None, types.SimpleNamespace(payload=b"2E010001"))  # anything else is ignored
    assert asked == ["MQTT"]
    m = Monitor(lambda: None, load_all(), [sink], log=lambda _m: None)
    assert sink.on_command == m.request_wake  # the monitor wires itself to the sink
    assert published["broker"] == ("ha.local", 1883) and published["auth"] == ("user", "geheim")


# -- reading on demand (wakes a sleeping car) ---------------------------------------------------------

def test_request_wakes_a_sleeping_car_once_within_the_gap():
    car, clock, m, sink = sleeping(wakeable=True)
    m.tick()
    assert sink.states[-1]["status"] == "asleep" and not requests_sent(car)   # nothing scheduled: stays quiet
    m.request_wake("MQTT")
    m.tick()
    assert sink.states[-1]["status"] == "woken" and sink.states[-1]["soc"] > 79
    assert "request: MQTT" in sink.states[-1]["last_wake_result"]
    car._woken = False                      # asleep again
    before = len(requests_sent(car))
    clock.advance(minutes=3)
    m.request_wake("MQTT")
    m.tick()                                # too soon after the last wake-up: refused, nothing sent
    assert len(requests_sent(car)) == before and "refused (MQTT)" in sink.states[-1]["last_wake_result"]
    clock.advance(minutes=10)
    m.request_wake("interface")
    m.tick()
    assert len(requests_sent(car)) > before and sink.states[-1]["status"] == "woken"
    m.tick()                                # a request is used up by one check
    assert sink.states[-1]["status"] == "asleep"


def test_request_respects_the_minimum_voltage():
    car, _clock, m, sink = sleeping(wakeable=True, voltage=11.9)
    m.request_wake("MQTT")
    m.tick()
    assert not requests_sent(car) and "not woken: 12 V only 11.90 V" in sink.states[-1]["last_wake_result"]


def test_request_without_connection_is_reported():
    def no_car():
        raise OSError("network unreachable")
    sink = Collect()
    m = Monitor(no_car, load_all(), [sink], log=lambda _m: None)
    m.request_wake("MQTT")
    m.tick()
    assert sink.states[-1]["status"] == "no connection"
    assert sink.states[-1]["last_wake_result"] == "not possible (MQTT): no connection to the car"


def test_request_ends_the_pause_between_checks():
    import threading
    import time
    _car, _clock, m, _sink = sleeping()
    threading.Timer(0.2, m.request_wake, args=("Test",)).start()
    t0 = time.monotonic()
    m.wait(30)
    assert time.monotonic() - t0 < 5
    stop = threading.Event()
    stop.set()
    t0 = time.monotonic()
    m.wait(30, stop)
    assert time.monotonic() - t0 < 2


# -- wake test ----------------------------------------------------------------------------------------

def wake_test(car, **kw):
    from evsoc import waketest
    t = [0.0]

    def connect():
        a = ElmAdapter(car)
        a.reset()
        return a

    def pause(seconds):
        t[0] += seconds
        if t[0] > 200:
            car.voltage, car._woken = 12.6, False   # the car goes back to sleep after a few minutes

    return waketest.run(connect, load_all(), profile=load_all()["evsoc_stellantis_ecmp"], log=lambda _m: None,
                        now=lambda: t[0], pause=pause, **kw)


def test_wake_test_measures_waking_and_falling_asleep():
    from evsoc import waketest
    car = MockElmTransport("corsa-e", voltage=12.6, wakeable=True)
    real = car._handle

    def handle(cmd):                       # a woken car charges its 12 V battery
        out = real(cmd)
        if car._woken:
            car.voltage = 13.8
        return out

    car._handle = handle
    report = wake_test(car)
    assert report["before"] == {"reachable": True, "awake": False, "voltage": 12.6}
    assert report["wake"]["woke"] and report["wake"]["soc"] > 79 and len(report["wake"]["attempts"]) >= 1
    assert report["timeline"][0]["awake"] and not report["timeline"][-1]["awake"]
    assert 3 <= report["asleep_after_min"] <= 5
    text = waketest.summary(report)
    assert "Waking works" in text and "asleep again after about" in text


def test_wake_test_car_that_cannot_be_woken_and_weak_battery():
    report = wake_test(MockElmTransport("corsa-e", voltage=12.6), watch_minutes=1)
    assert report["wake"]["woke"] is False and len(report["wake"]["attempts"]) == 5
    assert any("cannot be woken" in v for v in report["verdict"])

    report = wake_test(MockElmTransport("corsa-e", voltage=11.8, wakeable=True))
    assert report["wake"]["woke"] is False and not report["wake"]["attempts"]
    assert "12 V battery only 11.80 V" in report["verdict"][-1]


def test_wake_test_without_connection():
    from evsoc import waketest

    def no_car():
        raise OSError("No ENET connection")
    report = waketest.run(no_car, load_all(), log=lambda _m: None, pause=lambda _s: None)
    assert report["before"]["reachable"] is False and report["wake"]["woke"] is False
    assert "No connection" in report["verdict"][0]


def test_wake_command(tmp_path, capsys):
    from evsoc.cli import main
    out = tmp_path / "w.json"
    assert main(["wake", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--dauer", "0.01", "--abstand", "0.2",
                 "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "already awake" in text and f"Report: {out}" in text
    assert json.loads(out.read_text())["kind"] == "waketest"
    assert main(["wake", "-a", "mock://corsa-e", "-p", "gibt_es_nicht"]) == 2
