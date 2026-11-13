# evsoc

[English](README.md) · [Deutsch](README.de.md)

[![CI](https://github.com/GreyGoose01/evsoc/actions/workflows/ci.yml/badge.svg)](https://github.com/GreyGoose01/evsoc/actions/workflows/ci.yml)

Read the state of charge (SoC) and other battery values of electric cars and plug-in hybrids through the OBD socket, in Python, without an app. Read only.

- **270 profiles, 72 makes.** Own profiles (partly derived from the OVMS source code) plus collections imported automatically from OBDb, ABRP and WiCAN, grouped by shared platforms. List: [docs/vehicles.md](docs/vehicles.md)
- **Automatic detection.** evsoc reads the VIN, picks the fitting profiles and sends identical requests only once.
- **Any adapter.** ELM327/OBDLink over USB, Bluetooth, BLE and WiFi, the BMW ENET cable, raw CAN interfaces (CAN FD too) through python-can, and a do-it-yourself universal adapter (evsoc box, USB only, [build guide](docs/box-build-guide.md)).
- **The right OBD type per vehicle.** For every profile evsoc knows bus type, pins, bitrate and mode, checks whether your adapter can do it and switches a universal adapter by itself (`evsoc plan "Nissan Leaf"`).
- **An interface instead of a terminal.** `evsoc gui` covers everything: connect, find the vehicle, read, test drive with report, control units and fault memory, raw commands, listening in, continuous operation. On Linux, `evsoc desktop` adds it to the application menu.
- **Test drive.** `evsoc probe` tests all fitting profiles completely at the car, compares with the values you read off the dashboard, reads identification and fault memory of the control units and writes a report with every raw answer, which can be re-evaluated later without the car.
- **Listen in on other apps.** `evsoc sniff` listens through a Y cable (CAN) or as a man in the middle (BMW ENET) to what Car Scanner, BimmerLink & co. ask, shows what evsoc already knows, finds formulas for values you note and writes a profile from them. On buses with cyclic frames it searches the signal that matches reference values, which a second adapter can supply automatically (`--referenz`).
- **Analyse complete traffic.** `evsoc analyse` records all CAN traffic or Automotive Ethernet (DoIP, HSFZ, SOME/IP, pcap) and condenses it into a report you can hand to an assistant for decoding.
- **Continuous operation.** `evsoc monitor` stays with the car, asks only while it is awake (driving, charging) and sends the state to Home Assistant, MQTT or a webhook. A reading can be requested from outside by MQTT or a button, waking a sleeping car for it; `evsoc wake` tests first whether that works with your car.
- **As a device in the car.** `evsoc run` finds adapter and vehicle by itself, monitors continuously, passes the values on and shows a display without controls. Set up once in the browser (PIN protected). See [docs/raspberry-pi.md](docs/raspberry-pi.md)
- **Wired only, if you want.** `--nur-kabel` allows only USB, CAN and ENET adapters, no WiFi/Bluetooth; the interface can be bound to `eth0`.
- **Battery health (SoH).** Straight from the BMS (BMW i3/Mini, Corsa-e, Hyundai/Kia, Taycan …) or, for the VW group (ID., Enyaq, Born, Q4), from the energy content and the nominal capacity (`--akku-kwh`).
- **English and German.** Terminal and interfaces speak both, following the system language, `--lang en|de` or the switch in the interface.
- **Read only.** Writing, clearing and coding commands are blocked before they reach the adapter. The fault memory is read, never cleared.

> **At your own risk.** evsoc is a private research project, not affiliated with any car maker and without warranty. It only sends read commands, but it does work with the vehicle diagnostics: an adapter left plugged in can drain the 12 V battery, and work on the vehicle wiring can affect warranty and type approval. Nearly everything has only been tested against simulated vehicles. Do not operate it while driving.

## Quick start

```bash
git clone https://github.com/GreyGoose01/evsoc.git && cd evsoc
python3 -m venv .venv && .venv/bin/pip install -e ".[all]"
.venv/bin/evsoc gui                                 # interface in the browser
.venv/bin/evsoc desktop                             # Linux: add to the application menu
.venv/bin/evsoc read -a mock://corsa-e              # try it without a car
.venv/bin/evsoc models ioniq                        # find a vehicle
.venv/bin/evsoc devices --ble                       # find adapters
.venv/bin/evsoc read -a /dev/ttyUSB0                # a real car
```

```
Reading the vehicle identification number (VIN) ...
Trying 43 profiles ...
  Match: evsoc_stellantis_ecmp  (soc=79.959, soc_bms=79.959)

Profile: evsoc_stellantis_ecmp
  Vehicles: Peugeot e-208 (2019-), Peugeot e-2008 (2019-), Opel Corsa-e / Corsa Electric (2019-) ...
  State of charge (SoC)            80.0 %
  State of charge (BMS)            80.0 %
```

The language follows the system (`LANG`); set it with `--lang en` / `--lang de` or `EVSOC_LANG`.

## Documentation

The detailed documentation is in English; a German version is in [docs/de/](docs/de/schnellstart.md) (start with the German [README](README.de.md)):

| | |
|---|---|
| [Interfaces](docs/gui.md) | device (`evsoc run`) and workshop (`evsoc gui`) compared, operation, security |
| [Quick start](docs/quickstart.md) | installation, first reading, options, troubleshooting |
| [Vehicles](docs/vehicles.md) | all supported models, by make and platform |
| [Battery health](docs/battery-health.md) | SoH per make, VW MEB with nominal capacity, BMW, limits |
| [Test drive](docs/test-drive.md) | `evsoc probe`: test everything, write a report, what is needed for evaluation |
| [Adapters](docs/adapters.md) | which adapter for which car |
| [Continuous operation](docs/continuous-operation.md) | state of charge of a parked car, waking, Home Assistant |
| [Device in the car (Raspberry Pi)](docs/raspberry-pi.md) | wired only: setup, power, installation as a service |
| [Universal adapter](docs/universal-adapter.md) and [build guide](docs/box-build-guide.md) | OBD type per vehicle, pins, building the evsoc box |
| [Box firmware](firmware/README.md) | status, simulator without hardware |
| [How it works](docs/how-it-works.md) | OBD, UDS, ISO-TP, profiles, detection, code layout |
| [Own profiles](docs/own-profiles.md) | decoding a new car and adding it |
| [Listening in](docs/listening-in.md) and [analysing traffic](docs/analyse.md) | Y cable, ENET listener, formula search, broadcast frames |
| [Sources & licences](docs/sources.md) | origin of the data, known differences, `evsoc update` |

## Tests

```bash
.venv/bin/pip install -e ".[all,dev]" && .venv/bin/pytest && .venv/bin/ruff check .
```

The tests run without a car. They use a simulated ELM327, a virtual CAN bus with simulated control units, a mock BMW gateway and the evsoc box firmware as a simulator on the PC, partly with real captures (Corsa-e, BMW i3 and iX3, ID.4, Megane E-Tech).

## Contributing

Data from real cars helps most: [CONTRIBUTING.md](CONTRIBUTING.md). Please report security issues privately: [SECURITY.md](SECURITY.md).

## Licence

The code is under the [MIT licence](LICENSE). The imported profiles in `evsoc/profiles/generated/` keep the licence of their source (OBDb: CC-BY-SA-4.0, WiCAN: GPL-3.0, ABRP: Apache-2.0), see [THIRD_PARTY.md](THIRD_PARTY.md).
