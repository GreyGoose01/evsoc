# Universal adapter (evsoc box)

An adapter for all cars needs three things. Only the first one is hardware:

| Level | Question | Solution |
|---|---|---|
| Electrical | On which pins and with which protocol does the car talk? | enough transceivers and a pin switch (evsoc box) |
| Access | Does the gateway let diagnostic requests through? | mostly; a Tesla needs a special cable, some gateways an unlock |
| Meaning | Which request returns the state of charge, and how is it converted? | the evsoc profiles |

Building: [box-build-guide.md](box-build-guide.md). Firmware commands: [box-protocol.md](box-protocol.md).

## How evsoc chooses the OBD type

1. **Determine the vehicle:** `--car`, VIN or automatic detection.
2. **Derive the bus per query step** (`evsoc/connection.py`) from the protocol commands of the profile (`ATSP6` = CAN 11 bit, `ATSP7` = 29 bit, `ATSPB` + `ATPB…` = special setting, `ATSP3`–`5` = K-line). Profiles can override this, e.g. `"connection": {"pins": [12, 13]}` on the Leaf or `{"fd": true}` for CAN FD.
3. **Check the adapter:** every adapter type knows its bus types, pins and whether it can listen. If it does not fit, evsoc says why before the first byte, and which ones would.
4. **Switch:** evsoc sets up the evsoc box before every step (`EVSBUS CAN 12,13 500000`, `EVSLISTEN 1`).

```bash
evsoc plan "Nissan Leaf"                     # which OBD type, which adapters fit
evsoc plan "Nissan Leaf" -a /dev/ttyUSB0     # does my adapter fit?
evsoc scan -a box:/dev/ttyACM0               # which buses are present? (box only)
```

| Vehicle | OBD type | Note |
|---|---|---|
| Peugeot e-208, Opel Corsa-e | CAN 500 kbit/s, 11 bit, pins 6/14 | any adapter |
| VW ID.3/ID.4, Renault Zoe Ph2 | CAN 500 kbit/s, 29 bit, pins 6/14 | any adapter |
| BMW i3, Mini SE | CAN 11 bit with extended addressing **or** Ethernet (ENET) | cheap clones fail at `ATCEA` |
| Nissan Leaf up to 2017 | passive: EV-CAN on pins 12/13 | evsoc box or CAN interface with its own cable |
| Tesla Model 3/Y | CAN, listen only, Tesla diagnostic cable | no data at the OBD socket |
| older hybrids | partly K-line on 7/15 | OBDLink or evsoc box |
| GM from about 2020 | partly CAN FD | ELM327 adapters cannot do that |

## What can be present at the OBD socket

| Pins | Bus | where |
|---|---|---|
| 6 / 14 | high-speed CAN 500 kbit/s, increasingly CAN FD | all EVs |
| 3 / 11 | mid-speed CAN (Ford), AV-CAN (Leaf) | maker specific |
| 12 / 13 | EV-CAN (Leaf up to 2017) | maker specific |
| 1 | single-wire CAN | GM |
| 3 / 11 / 12 / 13 + 8 | Automotive Ethernet, ISO 13400-4 option 1 | BMW (ENET), increasingly others |
| 1 / 9 / 12 / 13 + 8 | Automotive Ethernet, option 2 | newer cars |
| 7 / 15 | K-line (ISO 9141, KWP2000) | older cars and hybrids |
| 16 / 4 / 5 | 12 V, chassis ground, signal ground | always |

Pin 8 activates Ethernet. The options differ in the receive lines (3/11 or 1/9).

## What ready-made adapters cover

| Adapter | HS-CAN | CAN FD | other pins | K-line | Ethernet | in evsoc |
|---|---|---|---|---|---|---|
| ELM327 clone | yes (often shaky) | no | no | partly | no | `/dev/…`, `tcp://`, `ble://` |
| OBDLink MX+ / SX / EX | yes | no | MS/SW-CAN (not yet switched by evsoc) | yes | no | `/dev/…` |
| BMW ENET cable | no | no | – | no | yes (BMW) | `enet://` |
| CAN(-FD) interface + cable | yes | with an FD interface | through the cable (`?pins=12,13`) | no | no | `can://` |
| **evsoc box** (USB only) | yes | yes | all, switchable | yes | planned | `box:/dev/ttyACM0` |

Without building anything, OBDLink + ENET cable + CAN FD interface + Tesla cable cover practically every car, together roughly 150–200 €.

## Build of the box

**Requirements:** all buses of the table switchable by software; ELM327 compatible plus own commands; read only by default; listening without acknowledgements; USB only, **no WiFi and no Bluetooth** (less power, no attack surface, no radio approval); quiescent current below 1 mA.

```
 OBD 16 ─ 12 V ─► reverse polarity protection ─ TVS ─ step-down (quiescent < 50 µA) ─ voltage measurement
 OBD 6/14, 3/11, 12/13, 1/9, 1, 7/15, 8
        │
   pin matrix (relays/PhotoMOS): every pin pair switchable to a channel, default: only 6/14
        │
   3× CAN FD transceiver · SW-CAN · K-line · 100BASE-TX PHY + transformer
        │
   STM32H723 (3× FDCAN, Ethernet MAC, USB)
        │
   USB-C (virtual COM port) ── optional USB isolator ──► Raspberry Pi / computer
```

**Pin matrix:**

- A transceiver on pins that carry Ethernet can disturb it. Therefore initially only CAN channel 1 hangs on 6/14. Everything else is only switched in when the profile asks for it or the bus scan confirms it.
- The switches must withstand vehicle voltage (fault case) and have little capacitance (CAN FD). Analogue switches for 3.3 V are not enough.
- No termination resistor of its own.
- Before Ethernet, check pin 8 first and never switch a CAN transceiver onto the same pins at the same time.

### Parts for your own board

| Function | Example | Why |
|---|---|---|
| microcontroller | STM32H723 | 3× CAN FD, Ethernet MAC and USB on one chip (STM32G474: no Ethernet; STM32H563: only 2× CAN) |
| CAN FD transceiver | TI TCAN1462, NXP TJA1463 | up to 5 Mbit/s; the TJA1463 wakes the device on bus activity |
| K-line | ST L9637D | standard part for ISO 9141/KWP2000 |
| Ethernet | 100BASE-TX PHY (e.g. LAN8742A) + transformer | DoIP at the OBD socket is 100BASE-TX |
| USB | USB-C with ESD protection, optional isolation with ADuM3160 | the only connection to the Pi |
| power supply | step-down with very low quiescent current, reverse polarity protection, TVS | continuous operation without draining the 12 V battery |

### Firmware

```
 USB-CDC  →  command parser (ELM327 + EVS)  →  safety filter (read services only)
          →  ISO-TP (classic + FD), KWP, DoIP/HSFZ  →  bus driver + pin matrix
```

The safety filter sits in the firmware **in addition to** the guard in evsoc, so that the box stays read only even with other programs.

**Bus scan (`EVSSCAN`)**, in listen mode only:

1. Pin 8: Ethernet present, option 1 or 2?
2. Pin 7: K-line idle level (~12 V)?
3. Every CAN pin pair at 500, 250, 125 and 1000 kbit/s, ~200 ms each. The first bitrate with error-free frames wins.
4. Many errors despite traffic point to CAN FD: repeat with a 2 or 5 Mbit/s data phase.
5. Pin 1 at 33.3 kbit/s (single-wire CAN).

Result: buses with bitrate and the CAN IDs seen. The IDs are a fingerprint by which the vehicle can be recognised later.

## What evsoc already does for this

- connection model: bus per profile step, capabilities of all adapter types, check (`evsoc/connection.py`)
- box control: bus choice before every step, bus scan (`evsoc/universal.py`)
- simulated box with three buses: `box:mock://leaf`
- `evsoc plan`, `evsoc scan`, check at `evsoc read -p`, tests in `tests/test_connection.py`

## Limits

- **Gateways with an unlock** (e.g. Stellantis SGW, Mercedes): battery values can often be read anyway, otherwise an unlock or a tap before the gateway is needed.
- **DoIP addresses** are assigned differently by every maker. CAN profiles cannot be carried over automatically, except on BMW (ENET).
- **Sleeping control units** often answer only in "Ready" or while charging ([continuous-operation.md](continuous-operation.md)).
- **Tesla** always needs a cable to the diagnostic connector.
