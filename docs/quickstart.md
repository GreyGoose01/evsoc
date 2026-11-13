# Quick start

## Installation

```bash
git clone https://github.com/GreyGoose01/evsoc.git && cd evsoc
python3 -m venv .venv
.venv/bin/pip install -e ".[all]"     # all = Bluetooth LE (bleak) + raw CAN (python-can) + MQTT
```

Without extras (`pip install -e .`) only USB, Bluetooth Classic and WiFi adapters and ENET work.

## Interface or command line

If you prefer clicking: `.venv/bin/evsoc gui` opens everything in the browser ([interfaces.md](interfaces.md)). The steps below use the command line.

## 1. Try it without a car

```bash
.venv/bin/evsoc read -a mock://corsa-e
.venv/bin/evsoc read -a mock://tesla-m3 --all
```

Test vehicles: `corsa-e`, `bmw-i3`, `bmw-ix3`, `ioniq5`, `id4`, `megane`, `bz4x`, `e-c3`, `tesla-m3`, `hybrid`, `psa-phev`, `smart-ed`.

## 2. Connect an adapter

1. Plug the adapter into the OBD socket (usually left below the steering wheel, sometimes behind a flap).
2. Switch the ignition on, or "Ready". Many EVs only answer then; otherwise the battery control unit sleeps.
3. Find the adapter:

```bash
.venv/bin/evsoc devices --ble --enet
```

| Adapter | Address for `-a` |
|---|---|
| Bluetooth Classic (OBDLink MX+, ELM327 BT) | pair it in the system settings first, then `/dev/rfcomm0` or `/dev/cu.<name>` |
| USB | `/dev/ttyUSB0`, `/dev/ttyACM0` (macOS: `/dev/cu.usbserial-…`), or `serial:///dev/…?baud=115200` |
| WiFi | join the adapter's WiFi, then `tcp://192.168.0.10:35000` |
| Bluetooth LE (OBDLink CX, Veepeak BLE, vLinker) | `ble://<name>` |
| BMW/Mini ENET | `enet://auto` |
| CAN interface (CANable, PCAN …) | `can://slcan//dev/ttyACM0?bitrate=500000` or `can://socketcan/can0` |

More in [adapters.md](adapters.md). On Linux, USB adapters need your user in the `dialout` group: `sudo usermod -aG dialout $USER`, then log out and in.

## 3. Read the state of charge

```bash
.venv/bin/evsoc read -a /dev/ttyUSB0
```

What happens: evsoc reads the VIN, looks for the profiles of the make and its group and tries them one by one. Requests that several profiles share go to the car only once. At the end the detected profile is shown. Next time `-p <profile>` is instant.

It is faster and safer to give the model:

```bash
.venv/bin/evsoc read -a /dev/ttyUSB0 --car "e-208"
.venv/bin/evsoc read -a /dev/ttyUSB0 --car "Ioniq 5" --year 2022
```

## Options

| Option | Effect |
|---|---|
| `-p NAME` | fixed profile instead of detection (`evsoc profiles`, `evsoc models`) |
| `--car TEXT` | give the model; also tries identical models of other makes |
| `--vin`, `--year` | give the VIN or model year (some commands only apply to certain years) |
| `--all` | all values of the profile (voltage, current, SoH, temperature …) including errors |
| `--battery-kwh 77` | net nominal capacity; needed for the SoH on cars that only report energy content (VW MEB), see [battery-health.md](battery-health.md) |
| `--watch 10` | read again every 10 seconds |
| `--json` | one JSON line per measurement, for scripts, Home Assistant, databases |
| `--log file.txt` | write all adapter traffic to a file |

More commands:

```bash
evsoc models corsa                 # find a vehicle, also shows identical profiles
evsoc models --markdown            # the complete list (generates docs/vehicles.md)
evsoc profiles -v --source obdb    # profiles with details
evsoc raw -a … -p evsoc_stellantis_ecmp 22D410 22D815    # single read commands
evsoc raw -a … --hits ATSH6F1 ATCEA07 22DD00-22DDFF      # query a range, show answers only
evsoc update                       # re-import profiles from OBDb, ABRP, WiCAN
evsoc monitor -a … --mqtt mqtt://…  # monitor continuously, see continuous-operation.md
evsoc plan "Nissan Leaf"           # which OBD type (bus, pins) and which adapter fits
evsoc scan -a box:/dev/ttyACM0     # find active buses (evsoc box)
evsoc probe -a …                   # test drive: test everything, write a report (test-drive.md)
```

German output: `--lang de`, or set `EVSOC_LANG=de`. Without either, evsoc follows the system language. The older German option names (`--akku-kwh`, `--treffer`, `--nur-kabel` …) still work.

## Troubleshooting

| Message | Cause and remedy |
|---|---|
| `The adapter does not answer …` | wrong port, adapter not paired, WiFi not connected. With BT clones, unplugging and replugging often helps. |
| `The adapter does not know 'ATCEA07'` | cheap clone. BMW/Mini and some profiles need an OBDLink, vLinker or ENET. |
| `NO DATA` for all profiles | ignition off, car asleep, or the gateway blocks. Open and close a door, switch on "Ready", try again. |
| `NRC 0x31 requestOutOfRange` | the control unit does not know this data identifier: wrong profile or model year. |
| `NRC 0x22 conditionsNotCorrect` | the car wants "Ready" or another state for this. |
| `No profile returned a plausible state of charge` | unknown car. Record with `--log` and follow [own-profiles.md](own-profiles.md), or run a test drive ([test-drive.md](test-drive.md)). |
| Values "(implausible)" | the formula does not fit this model. Try another profile (`also plausible: …`). |
