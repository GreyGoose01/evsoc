"""Long-running SoC monitor for an adapter that stays in the car.

Rule of thumb for EVs and PHEVs: while the high-voltage system is active
(driving, charging, preconditioning) the DC/DC converter holds the 12 V
battery at ~13.2-14.7 V; when the car sleeps it rests at ~12.2-12.9 V.
The adapter measures that voltage itself (ATRV) without any bus traffic,
so evsoc only sends requests while the car is awake and never keeps it
from sleeping. A parked, unplugged car's SoC barely changes, so the last
reading (with its timestamp) stays valid until the car wakes up again.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from datetime import time as dtime
from typing import Protocol
from urllib.parse import unquote, urlparse

from .elm import AdapterError
from .profiles import Profile
from .reader import Adapter, autodetect, read, run_init
from .safety import SafetyError
from .transports import TransportError

Log = Callable[[str], None]


@dataclass
class State:
    status: str = "unknown"           # awake, woken, asleep, no answer, no connection (German values, see app.html)
    soc: float | None = None
    values: dict[str, float] = field(default_factory=dict)
    soc_updated: str | None = None      # time of the last successful SoC reading
    voltage_12v: float | None = None
    checked: str | None = None          # time of the last check
    profile: str | None = None
    vin: str | None = None
    last_wake: str | None = None        # time of the last deliberate wake-up attempt
    last_wake_result: str | None = None
    note: str | None = None             # warnings, e.g. car did not go back to sleep

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class Sink(Protocol):
    def publish(self, state: State) -> None: ...
    def close(self) -> None: ...


class StdoutSink:
    def __init__(self, as_json: bool):
        self.as_json = as_json

    def publish(self, state: State) -> None:
        if self.as_json:
            print(state.to_json(), flush=True)
            return
        soc = f"{state.soc:.1f} %" if state.soc is not None else "-"
        volt = f"{state.voltage_12v:.2f} V" if state.voltage_12v is not None else "?"
        since = f" (as of {state.soc_updated[11:19]})" if state.soc_updated else ""
        from .i18n import tr
        print(f"{state.checked[11:19]}  SoC {soc}{tr(since)}  12V {volt}  {tr(state.status)}", flush=True)

    def close(self) -> None:
        pass


class FileSink:
    """Writes the latest state atomically, e.g. for a web page or another program."""

    def __init__(self, path: str):
        self.path = path

    def publish(self, state: State) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".evsoc-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(state.to_json() + "\n")
        os.replace(tmp, self.path)

    def close(self) -> None:
        pass


class ThrottledFileSink(FileSink):
    """Writes only when something relevant changed (or every `every` seconds) to spare SD cards."""

    def __init__(self, path: str, every: float = 900):
        super().__init__(path)
        self.every = every
        self._last_key: tuple | None = None
        self._last_write = 0.0

    def publish(self, state: State) -> None:
        key = (state.status, state.soc, state.soc_updated, state.profile, state.last_wake, state.note)
        if key == self._last_key and time.monotonic() - self._last_write < self.every:
            return
        super().publish(state)
        self._last_key, self._last_write = key, time.monotonic()


def _http_error(e: OSError) -> str:
    """Short German text for a failed HTTP delivery."""
    import socket as _socket
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return f"target answers with HTTP {e.code}"
    reason = getattr(e, "reason", e)
    if isinstance(reason, ConnectionRefusedError):
        return "target refuses the connection (check address/port)"
    if isinstance(reason, (TimeoutError, _socket.timeout)):
        return "no answer (timeout)"
    if isinstance(reason, _socket.gaierror):
        return "name cannot be resolved (check address)"
    return str(reason)


class WebhookSink:
    """POSTs the state as JSON (own server, Node-RED, n8n, Home Assistant webhook ...)."""

    def __init__(self, url: str, log: Log):
        self.url, self.log = url, log
        self.ok: bool | None = None       # result of the last delivery (None = not tried yet)
        self.error: str | None = None
        self.last_ok: str | None = None

    def publish(self, state: State) -> None:
        req = urllib.request.Request(self.url, data=state.to_json().encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).close()
            self.ok, self.error, self.last_ok = True, None, datetime.now().astimezone().isoformat(timespec="seconds")
        except OSError as e:
            self.ok, self.error = False, _http_error(e)
            self.log(f"Webhook failed: {self.error}")

    def close(self) -> None:
        pass


class MqttSink:
    """Publishes to MQTT, incl. Home Assistant auto-discovery. URL: mqtt://user:pass@host:1883/evsoc/auto"""

    SENSORS = [
        ("soc", "State of charge", {"device_class": "battery", "unit_of_measurement": "%", "state_class": "measurement"}),
        ("soc_updated", "State of charge time", {"device_class": "timestamp"}),
        ("voltage_12v", "12 V battery", {"device_class": "voltage", "unit_of_measurement": "V", "state_class": "measurement"}),
        ("status", "Status", {}),
        ("soh", "Battery health", {"unit_of_measurement": "%", "state_class": "measurement"}),
    ]

    def __init__(self, url: str, log: Log, discovery_prefix: str = "homeassistant"):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as e:
            raise AdapterError("paho-mqtt missing: pip install paho-mqtt") from e
        u = urlparse(url)
        self.topic = (u.path.strip("/") or "evsoc/auto")
        self.node = self.topic.replace("/", "_")
        self.log = log
        self.discovery_prefix = discovery_prefix
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"evsoc-{self.node}")
        except AttributeError:  # paho-mqtt < 2
            self.client = mqtt.Client(client_id=f"evsoc-{self.node}")
        if u.username:
            self.client.username_pw_set(unquote(u.username), unquote(u.password or ""))
        if u.scheme == "mqtts":
            self.client.tls_set()
        self.connected = threading.Event()
        self.error: str | None = None
        self.on_command: Callable[[str], None] | None = None  # set by the monitor: "read now, wake if needed"
        self.client.on_message = self._on_message
        self.client.will_set(f"{self.topic}/availability", "offline", retain=True)
        self.client.on_disconnect = lambda *_a: self.connected.clear()
        self.client.on_connect = self._on_connect
        self.client.connect_async(u.hostname or "localhost", u.port or (8883 if u.scheme == "mqtts" else 1883))
        self.client.loop_start()

    def _on_connect(self, client, *args) -> None:
        rc = args[2] if len(args) >= 3 else 0
        failed = getattr(rc, "is_failure", None)
        if (failed if failed is not None else rc not in (0, None)):
            self.error = f"broker refuses: {rc}"
            return
        self.error = None
        self.connected.set()
        device = {"identifiers": [f"evsoc_{self.node}"], "name": f"evsoc {self.node}", "manufacturer": "evsoc"}
        for key, name, extra in self.SENSORS:
            config = {
                "name": name,
                "unique_id": f"evsoc_{self.node}_{key}",
                "state_topic": f"{self.topic}/state",
                "value_template": f"{{{{ value_json.{key} if value_json.{key} is defined else value_json['values'].get('{key}') }}}}",
                "availability_topic": f"{self.topic}/availability",
                "device": device,
                **extra,
            }
            client.publish(f"{self.discovery_prefix}/sensor/evsoc_{self.node}/{key}/config", json.dumps(config), retain=True)
        button = {"name": "Read now (wakes the car)", "unique_id": f"evsoc_{self.node}_wake",
                  "command_topic": f"{self.topic}/cmd", "payload_press": "wake",
                  "availability_topic": f"{self.topic}/availability", "device": device}
        client.publish(f"{self.discovery_prefix}/button/evsoc_{self.node}/wake/config", json.dumps(button), retain=True)
        client.subscribe(f"{self.topic}/cmd")
        client.publish(f"{self.topic}/availability", "online", retain=True)

    def _on_message(self, _client, _userdata, message) -> None:
        """'<topic>/cmd' with 'wake' or 'read': read now, wake a sleeping car for it."""
        text = bytes(message.payload).decode("utf-8", "replace").strip().lower()
        if text in WAKE_COMMANDS and self.on_command:
            self.log("MQTT: reading requested")
            self.on_command("MQTT")
        else:
            self.log(f"MQTT: unknown command {text[:40]!r} (possible: wake, read)")

    def publish(self, state: State) -> None:
        self.client.publish(f"{self.topic}/state", state.to_json(), retain=True)

    def close(self) -> None:
        self.client.publish(f"{self.topic}/availability", "offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()


def parse_times(values: list[str] | None) -> list[dtime]:
    """'06:00' -> time(6, 0) for --wake-at."""
    out = []
    for v in values or []:
        h, _, m = v.partition(":")
        out.append(dtime(int(h), int(m or 0)))
    return out


def car_awake(adapter, awake_voltage: float) -> tuple[bool, float | None, str]:
    """(awake, 12 V voltage, how we know) without sending anything on the bus."""
    volt = adapter.voltage()
    if volt is not None:
        return volt >= awake_voltage, volt, "12 V voltage"
    if hasattr(adapter, "bus_active"):
        return bool(adapter.bus_active()), None, "traffic on the bus"  # raw CAN: traffic means the car is awake
    return True, None, "gateway reachable"  # ENET: the gateway is only reachable while the car is awake


WAKE_COMMANDS = {"wake", "read", "wecken", "lesen", "press", "1", "on"}


class Monitor:
    """Checks the car periodically; see the module docstring for the idea.

    Waking a sleeping car (``wake_every`` hours since the last reading and/or
    at fixed ``wake_at`` times) is opt-in and guarded: never below
    ``min_voltage``, at most one attempt per slot, a few retries because a
    gateway needs a moment to boot, and a check 30 minutes later whether the
    car really went back to sleep.

    ``request_wake`` asks for a reading right now, from outside (MQTT command, web page): the
    next check happens at once and wakes a sleeping car, with the same guards plus a minimum
    gap of ``wake_gap`` minutes between two wake-ups.
    """

    WAKE_CHECK = timedelta(minutes=30)

    def __init__(
        self,
        connect: Callable[[], Adapter],
        profiles: dict[str, Profile],
        sinks: list[Sink],
        profile: Profile | None = None,
        car: str | None = None,
        year: int | None = None,
        battery_kwh: float | None = None,
        interval: float = 60,
        sleep_interval: float = 300,
        awake_voltage: float = 13.0,
        wake_every: float | None = None,
        wake_at: list[dtime] | None = None,
        min_voltage: float = 12.2,
        wake_tries: int = 3,
        wake_gap: float = 10,
        fields: list[str] | None = None,
        state: State | None = None,
        log: Log = print,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        pause: Callable[[float], None] = time.sleep,
    ):
        self.connect, self.profiles, self.sinks = connect, profiles, sinks
        self.profile, self.car, self.year = profile, car, year
        self.battery_kwh = battery_kwh
        self.interval, self.sleep_interval = interval, sleep_interval
        self.awake_voltage = awake_voltage
        self.wake_every, self.wake_at = wake_every, wake_at or []
        self.min_voltage, self.wake_tries = min_voltage, wake_tries
        self.fields = fields
        self.state = state or State()
        self.log, self.clock, self.pause = log, clock, pause
        self.adapter: Adapter | None = None
        self._initialised = False
        self._last_tick: datetime | None = None
        self._wake_check: datetime | None = None
        self.wake_gap = wake_gap
        self._requested: str | None = None     # who asked for a reading right now
        self._kick = threading.Event()         # ends the pause between two checks
        if self.profile is None and self.state.profile in profiles:
            self.profile = profiles[self.state.profile]
        for sink in sinks:
            if hasattr(sink, "on_command"):
                sink.on_command = self.request_wake

    def request_wake(self, source: str = "request") -> None:
        """Read now; wake the car for it if it sleeps (called from other threads)."""
        self._requested = source
        self._kick.set()

    def wait(self, delay: float, stop: threading.Event | None = None) -> None:
        """Pause until the next check; a wake request or `stop` ends it early."""
        end = time.monotonic() + delay
        while not self._kick.is_set() and not (stop and stop.is_set()):
            left = end - time.monotonic()
            if left <= 0:
                break
            self._kick.wait(min(left, 0.5))
        self._kick.clear()

    def _wanted(self, profile: Profile) -> list[str]:
        names = [f.name for f in profile.soc_fields]
        extra = self.fields if self.fields is not None else ["soh", "voltage", "current"]
        return names + [n for n in extra if n in profile.fields and n not in names]

    def _disconnect(self) -> None:
        if self.adapter is not None:
            try:
                self.adapter.close()
            except Exception:  # noqa: BLE001 - closing a dead link may fail any way
                pass
        self.adapter, self._initialised = None, False

    @staticmethod
    def _parse(ts: str | None) -> datetime | None:
        return datetime.fromisoformat(ts) if ts else None

    def _wake_due(self, now: datetime) -> str | None:
        """Reason for waking the sleeping car now, or None."""
        last_wake = self._parse(self.state.last_wake)
        if self.wake_every:
            period = timedelta(hours=self.wake_every)
            fresh = self._parse(self.state.soc_updated)
            if (fresh is None or now - fresh >= period) and (last_wake is None or now - last_wake >= period):
                return f"last value older than {self.wake_every:g} h"
        if self.wake_at and self._last_tick is not None:
            for t in self.wake_at:
                slot = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                if self._last_tick < slot <= now and (last_wake is None or last_wake < slot):
                    return f"wake-up time {t:%H:%M}"
        return None

    def tick(self) -> float:
        """One check. Returns the number of seconds until the next one."""
        now = self.clock()
        self.state.checked = now.isoformat(timespec="seconds")
        requested, self._requested = self._requested, None
        try:
            if self.adapter is None:
                self.adapter = self.connect()
            awake, volt, _how = car_awake(self.adapter, self.awake_voltage)
            self.state.voltage_12v = volt
            self._check_after_wake(now, awake, volt)
            if awake:
                self._read(woken=False)
            else:
                reason = self._wake_due(now)
                if requested:
                    last = self._parse(self.state.last_wake)
                    if last is not None and now - last < timedelta(minutes=self.wake_gap):
                        self.state.last_wake_result = (f"refused ({requested}): last wake-up {(now - last).total_seconds() / 60:.0f} min ago, minimum gap {self.wake_gap:g} min")
                        self.log(self.state.last_wake_result)
                    else:
                        reason = f"request: {requested}"
                if reason and volt is not None and volt < self.min_voltage:
                    self.state.status = "asleep"
                    self.state.last_wake_result = f"not woken: 12 V only {volt:.2f} V (< {self.min_voltage:g} V)"
                elif reason:
                    self._wake(now, reason)
                else:
                    self.state.status = "asleep"
        except (AdapterError, TransportError, OSError) as e:
            self.log(f"Connection: {e}")
            self.state.status = "no connection"
            if requested:
                self.state.last_wake_result = f"not possible ({requested}): no connection to the car"
            self._disconnect()
        self._last_tick = now
        self._publish()
        return self.interval if self.state.status == "awake" else self.sleep_interval

    def _wake(self, now: datetime, reason: str) -> None:
        self.log(f"Waking the car ({reason}) ...")
        self.state.last_wake = now.isoformat(timespec="seconds")
        for attempt in range(1, self.wake_tries + 1):
            self._read(woken=True)
            if self.state.status == "woken":
                self.state.last_wake_result = f"ok after attempt {attempt} ({reason})"
                self._wake_check = now + self.WAKE_CHECK
                return
            if attempt < self.wake_tries:
                self.pause(3.0)  # gateways and battery controllers need a moment to boot
        self.state.last_wake_result = f"no answer after {self.wake_tries} attempts ({reason})"

    def _check_after_wake(self, now: datetime, awake: bool, volt: float | None) -> None:
        if self._wake_check is None or now < self._wake_check:
            return
        self._wake_check = None
        if awake:
            self.state.note = (f"Car still awake 30 min after waking (12 V {volt:.2f} V). If this happens often without driving or charging: turn waking off.")
            self.log(self.state.note)
        else:
            self.state.note = None

    def _read(self, woken: bool) -> None:
        assert self.adapter is not None
        if self.profile is None:
            det = autodetect(self.adapter, self.profiles, car=self.car, year=self.year, log=self.log)
            if det is None:
                self.state.status = "no answer"
                return
            self.profile, self.year = det.profile, det.year
            self.state.profile, self.state.vin = det.profile.name, det.vin
            self._initialised = False
        if not self._initialised:
            run_init(self.adapter, self.profile, self.log)
            self._initialised = True
        try:
            reading = read(self.adapter, self.profile, self._wanted(self.profile), self.year, self.battery_kwh)
        except SafetyError as e:
            self.log(str(e))
            reading = None
        if reading is None or reading.soc is None:
            self.state.status = "no answer"
            return
        self.state.soc = reading.soc
        self.state.values = {k: v.value for k, v in reading.values.items() if v.plausible}
        self.state.soc_updated = self.clock().isoformat(timespec="seconds")
        self.state.profile = self.profile.name
        self.state.status = "woken" if woken else "awake"

    def _publish(self) -> None:
        for sink in self.sinks:
            try:
                sink.publish(self.state)
            except Exception as e:  # noqa: BLE001 - one broken sink must not stop the monitor
                self.log(f"Output {type(sink).__name__} failed: {e}")

    def run(self, once: bool = False) -> None:
        try:
            while True:
                delay = self.tick()
                if once:
                    return
                self.wait(delay)
        finally:
            self._disconnect()
            for sink in self.sinks:
                sink.close()


def load_state(path: str | None) -> State:
    if not path or not os.path.exists(path):
        return State()
    try:
        with open(path, encoding="utf-8") as f:
            return State(**json.load(f))
    except (OSError, ValueError, TypeError):
        return State()
