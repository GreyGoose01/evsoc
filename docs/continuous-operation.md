# Monitoring the state of charge of a parked car continuously

## Principle

**Directly through the OBD socket, with the car off and not charging, this usually does not work.** The battery control unit and the gateway sleep, and requests stay unanswered. Or they wake control units up and draw current from the 12 V battery. Users of Car Scanner and OVMS report this consistently.

**That is less bad than it sounds:**

1. A parked car that is not charging hardly loses any charge. The **last value when it was parked** is practically the current one.
2. **While charging**, the battery control unit is awake. On many cars it can then be read, but not on all (see the test below).
3. Whether the car is awake is revealed by the **12 V voltage**. While the high-voltage system runs (driving, charging, preconditioning), the DC/DC converter holds the 12 V battery at about 13.2–14.7 V. While asleep it rests at about 12.2–12.9 V. The adapter measures this itself, **without sending a single frame on the bus**.

This is exactly how `evsoc monitor` works: check the voltage. If the car is awake it reads the state of charge. If it sleeps it sends nothing and reports the last value with its time stamp.

```
08:12:03  SoC 80.0 % (as of 08:12:03)  12V 14.10 V  awake
08:13:03  SoC 79.8 % (as of 08:13:03)  12V 14.05 V  awake
08:14:04  SoC 79.8 % (as of 08:13:03)  12V 12.61 V  asleep
...
22:30:11  SoC 81.2 % (as of 22:30:11)  12V 13.92 V  awake        ← charging started
```

## Setups

### Variant A: adapter in the car, evsoc at home (garage or parking spot with WiFi)

```
 car: WiCAN in the OBD socket ──WiFi──► home network ──► Raspberry Pi / Home Assistant server / computer
                                                       evsoc monitor ──MQTT──► Home Assistant
```

1. Connect the WiCAN to your home WiFi (station mode) and choose "ELM327" as protocol.
2. On the computer at home:

```bash
evsoc monitor -a tcp://wican.local:3333 --car "e-208" \
  --state ~/evsoc-state.json \
  --mqtt "mqtt://user:password@homeassistant.local:1883/evsoc/car"
```

The port is shown by the WiCAN web interface (default 3333, WiCAN Pro 35000). While the car is away, evsoc keeps the last value and reconnects as soon as it is back. Any ELM327 adapter that can join an existing WiFi works the same way; most cheap WiFi adapters, however, only open a network of their own.

### Variant B: wired only, no radio

A Pi in the car, the adapter by USB or a CAN board, an Ethernet cable to the home network. Runs as a device with `evsoc run`: [raspberry-pi.md](raspberry-pi.md).

### Variant C: on the road (mobile network)

A small computer plus adapter plus LTE stick, evsoc reports by MQTT to a server. The computer then needs a supply that is only powered while the car is awake. Ready-made devices like WiCAN or OVMS are usually simpler for this.

## Options of `evsoc monitor`

| Option | Default | Meaning |
|---|---|---|
| `--interval` | 60 s | interval while the car is awake |
| `--sleep-interval` | 300 s | interval of the voltage check while asleep (no bus traffic) |
| `--awake-voltage` | 13.0 V | awake/asleep threshold |
| `--wake-every HOURS` | off | wake a sleeping car when the last value is older than HOURS hours (e.g. 24) |
| `--wake-at HH:MM` | off | also wake daily at this time (repeatable) |
| `--min-voltage` | 12.2 V | never wake when the 12 V battery is below this |
| `--wake-gap MIN` | 10 | minimum gap between two wake-ups on request (MQTT, button) |
| `--battery-kwh` | – | net nominal capacity for the SoH on VW MEB (see [battery-health.md](battery-health.md)) |
| `--state FILE` | – | last state as JSON; loaded on restart, including the detected profile |
| `--mqtt URL` | – | MQTT with Home Assistant discovery (state of charge, time stamp, 12 V voltage, status, SoH) |
| `--webhook URL` | – | state as JSON by HTTP POST |
| `--json`, `--once` | – | JSON lines, or a single check only (for cron or a systemd timer) |

With raw CAN interfaces (`can://`) there is no voltage measurement. There the car counts as awake when there is traffic on the bus. That also works without sending.

## Reading and waking from outside

For a view from outside, the values go out by MQTT or webhook (above). In the other direction a request can now come in: "read now". If the car is awake, evsoc reads at once. If it sleeps, evsoc wakes it for that.

| Way | How |
|---|---|
| MQTT | send `wake` (or `read`) to `<topic>/cmd`, e.g. `mosquitto_pub -t evsoc/car/cmd -m wake`. Runs automatically as soon as `--mqtt` is set. |
| Home Assistant | gets a button "Read now (wakes the car)" through discovery |
| Interface | button "Read now (wakes the car)" under Continuous operation (`evsoc gui`) or on the setup page of the device (`evsoc run`, with PIN) |

Protection so that an automation cannot drain the 12 V battery:

- never below `--min-voltage` (12.2 V),
- at most one wake-up every `--wake-gap` minutes (10). Earlier requests are refused, which shows in `last_wake_result`,
- 30 minutes after waking, evsoc checks whether the car sleeps again and warns otherwise.

The MQTT way needs no open port on the device: it connects to the broker itself. The broker controls who may send commands. The device in the car needs a network connection for this (WiFi at the parking spot, LTE router or stick). In wired-only operation without a network there is no way in from outside.

## Wake test: does it work with my car?

Whether a parked car wakes up on a request at the OBD socket depends on car, adapter and bus. `evsoc wake` measures it:

```bash
evsoc wake -a /dev/ttyUSB0 --car "e-208"          # lock the car first, wait 15–30 min
evsoc wake -a enet://auto --car i4 --duration 30
```

1. State before: reachable, 12 V voltage, awake or not.
2. Waking: read the state of charge, up to five attempts, time to the first answer.
3. Watching until the car sleeps again (`--duration`, default 20 minutes), without further requests.

The result is shown as text and saved as `evsoc-waketest-DATE.json` with a timeline. In the interface: Continuous operation → Wake test.

Depending on the adapter, evsoc sees different amounts:

| Adapter | Awake detection | Waking |
|---|---|---|
| ELM327/OBDLink | 12 V voltage, without bus traffic | read request on the CAN |
| CAN interface (`can://`) | traffic on the bus | read request on the CAN |
| ENET (BMW/Mini) | only "gateway reachable" | unclear, see below |

**BMW over ENET:** a sleeping car cannot be reached over ENET, and evsoc cannot measure the 12 V voltage there. Whether connection attempts wake the gateway is not established; the wake test shows it. Conversely, a permanently plugged ENET cable can keep the car awake and drain the 12 V battery. Before continuous operation over ENET, run the wake test and check the 12 V voltage overnight. For permanent reading, an adapter on the CAN pins (OBDLink, CAN interface, evsoc box) is the better checkable choice because it measures the voltage.

## Waking once a day?

**Yes, that is a good compromise.** You then have a fresh value even after days of standing, e.g. to notice a creeping loss from watchdog functions, preconditioning or a faulty consumer.

```bash
evsoc monitor -a tcp://wican.local:3333 -p evsoc_stellantis_ecmp \
  --wake-every 24 --wake-at 06:30 --state ~/evsoc-state.json --mqtt "mqtt://…"
```

**What happens when waking:**

1. evsoc sends a read request. The CAN frame wakes the gateway, which in turn wakes the battery control unit.
2. Booting often takes a moment. evsoc therefore tries up to 3 times at 3 second intervals.
3. After that evsoc asks nothing more, and the car falls asleep after its own run-on time (usually seconds to a few minutes).
4. **After 30 minutes** evsoc checks the 12 V voltage to see whether the car really sleeps again. If not, a note appears in the status (`note`).

**Protection rules:**

- It only wakes if the last value is older than `--wake-every`. If you just came back from a drive, nothing happens.
- At most one wake attempt per period. If the car does not answer, evsoc tries again only in the next period. The result is in `last_wake_result`.
- Below `--min-voltage` (default 12.2 V) it never wakes, so that an already weak 12 V battery is not strained further.

**What does it cost?** Order of magnitude, not measured: awake, gateway and control units draw roughly 1–5 A for a few minutes, i.e. about 0.05–0.3 Ah per wake-up. An adapter without sleep mode drawing 50 mA, on the other hand, takes 1.2 Ah **per day**. **The adapter's quiescent current therefore matters much more than a daily wake-up.**

**Limits:** not every car can be woken through the OBD socket. Some gateways ignore diagnostic requests with the ignition off entirely, or the battery control unit only answers in "Ready". evsoc then reports `no answer after 3 attempts` and leaves the car alone. Try it the first time while you are nearby: if a car shows lights or warnings when woken, waking is not for this model.

## Sparing the 12 V battery

- **Adapter quiescent current:** an adapter without sleep mode drawing, say, 50 mA costs about 8 Ah in a week. On the small 12 V batteries of EVs that is a noticeable share. Adapters with sleep mode (WiCAN, OBDLink) are better. For long standing, unplug the adapter.
- **Wake sparingly.** Once every 12–24 hours is reasonable (see above), every few minutes is not.
- **Check the threshold:** run `evsoc monitor -a … --once` once with the car asleep and once awake and compare the voltages shown. Cars with a 12 V lithium battery rest higher (sometimes above 13 V). Then raise `--awake-voltage` accordingly, to about 13.6.
- **Some cars recharge the 12 V battery themselves while parked.** Hyundai and Kia do this, for example. The voltage then rises briefly, evsoc asks, and that is fine, since the car is awake at that moment anyway.

## Test: does my car answer while charging?

1. Lock the car, wait 10 minutes, plug in the charging cable and start charging.
2. `evsoc read -a … -p <your profile>`
3. If a state of charge comes back, continuous operation works including the charging curve. If you get `NO DATA`, the gateway of your model is closed while charging. Then only the manufacturer cloud remains for the charging curve, and evsoc delivers the value on every drive.

## Home Assistant

With `--mqtt`, Home Assistant creates a device "evsoc …" automatically with the sensors *State of charge*, *State of charge time* (time stamp), *12 V battery*, *Status* and *Battery health*. Example automation:

```yaml
automation:
  - alias: "Car reached 80 %"
    trigger:
      - platform: numeric_state
        entity_id: sensor.evsoc_evsoc_car_state_of_charge
        above: 79.5
    action:
      - service: notify.mobile_app_phone
        data:
          message: "The car reached {{ states('sensor.evsoc_evsoc_car_state_of_charge') }} %."
```

The entity names depend on your topic and language; check them in Home Assistant under Devices.

## Alternatives without OBD

For a parked car the **manufacturer cloud** is the most reliable source: the car reports its state through the built-in modem when it falls asleep and while charging. It needs an account, and values can be a few minutes old. Integrations for Home Assistant:

| Manufacturer | Integration |
|---|---|
| Peugeot, Opel, Citroën, DS, Fiat, Jeep | [homeassistant-stellantis-vehicles](https://github.com/andreadegiovine/homeassistant-stellantis-vehicles) |
| Hyundai, Kia, Genesis | [kia_uvo](https://github.com/Hyundai-Kia-Connect/kia_uvo) |
| VW, Skoda, Cupra | [volkswagencarnet](https://github.com/robinostlund/homeassistant-volkswagencarnet), [myskoda](https://github.com/skodaconnect/myskoda) |
| BMW, Mini | BMW CarData, e.g. [bmw-cardata-ha](https://github.com/kvanbiesen/bmw-cardata-ha) |
| Mercedes | [mbapi2020](https://github.com/ReneNulschDE/mbapi2020) |
| Ford | [ha-fordpass](https://github.com/marq24/ha-fordpass) |
| MG | [saic-python-mqtt-gateway](https://github.com/SAIC-iSmart-API/saic-python-mqtt-gateway) |
| Tesla | Tesla Fleet API, [TeslaMate](https://github.com/teslamate-org/teslamate) |
| Renault, Volvo, Polestar, Toyota | Home Assistant or HACS |
