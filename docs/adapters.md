# Adapters

evsoc talks to three kinds of hardware:

1. **ELM327 compatible adapters** (ELM327 clones, OBDLink, Vgate, Veepeak, vLinker, WiCAN). The adapter handles CAN and ISO-TP, evsoc sends text commands.
2. **BMW/Mini ENET cable.** Ethernet straight to the vehicle gateway (HSFZ, TCP 6801).
3. **Raw CAN interfaces** through python-can (CANable, candleLight, PCAN, Kvaser, Vector, SocketCAN, comma panda). evsoc does ISO-TP and addressing itself, can do CAN FD and listens passively.

All three run the same profiles. evsoc translates the ELM commands in the profiles (`ATSH`, `ATCRA`, `ATCEA` …) for ENET and CAN automatically.

## Which adapter for which car?

The software answers this per vehicle:

```bash
evsoc plan "Peugeot e-208"
evsoc plan "Nissan Leaf" -a /dev/ttyUSB0     # does my adapter fit?
```

With a fixed profile (`read -p …`) evsoc checks before the first byte whether the adapter can do the bus, pins and mode of the profile. Detection leaves out profiles that do not fit. The overview:

| Vehicle | recommended | Note |
|---|---|---|
| almost all EVs and hybrids | OBDLink MX+ (Bluetooth), OBDLink CX (BLE), OBDLink SX/EX (USB) | reliable AT commands, fast |
| BMW i3, Mini SE, BMW PHEV | OBDLink or vLinker (`ATCEA` needed) **or** ENET cable | cheap clones mostly fail here |
| BMW/Mini F/G series in general | ENET cable (`enet://auto`) | uses Ethernet instead of CAN, very fast |
| Tesla Model 3/Y | CAN adapter cable from the diagnostic connector plus any CAN adapter | the OBD socket has no data on a Tesla, evsoc listens passively |
| cars with CAN FD (increasingly on new models) | CAN FD interface through `can://…?fd=1` | ELM327 chips cannot do CAN FD |
| older hybrids with K-line | OBDLink MX+/SX (they can do K-line) | |

## Connecting

**Bluetooth Classic** (OBDLink MX+, most ELM327 BT): pair in the system settings, PIN usually `1234` or `0000`. Afterwards there is a serial port:

```bash
evsoc devices                  # shows /dev/rfcomm0, /dev/cu.OBDLinkMXPlus or similar
evsoc read -a /dev/cu.OBDLinkMXPlus
```

**Bluetooth LE** (OBDLink CX, Veepeak BLE, vLinker MC+/FS, adapters "for iPhone"): do not pair. evsoc connects directly. On macOS the terminal needs Bluetooth permission the first time.

```bash
evsoc devices --ble
evsoc read -a "ble://OBDLink CX"
```

**WiFi** (ELM327 WiFi, WiCAN): join the adapter's WiFi with your computer (the internet then usually drops).

```bash
evsoc read -a tcp://192.168.0.10:35000     # WiCAN Pro: 192.168.0.10:35000, WiCAN: 192.168.80.1:3333
```

**USB:** usually the driver is in the system already, port `/dev/ttyUSB0`, `/dev/ttyACM0` or on macOS `/dev/cu.usbserial-…`. OBDLink SX/EX run at 115200 baud: `serial:///dev/ttyUSB0?baud=115200`.

**ENET (BMW/Mini):** cable to the OBD socket and to a USB Ethernet adapter. Set the network to "DHCP"/automatic, then the computer gives itself a 169.254.x.x address. Ignition on.

```bash
evsoc devices --enet           # finds the car by broadcast and shows the VIN
evsoc read -a enet://auto
```

**ENET with WiFi** (e.g. UniCarScan UCSI-3000): join the adapter's WiFi with the laptop, then also `enet://auto`. If the car does not answer the search, evsoc tries the gateway address of the adapter. Step by step with a BMW i4: [test-bmw-i4.md](test-bmw-i4.md).

**evsoc box (universal adapter):** put `box:` before the USB port, e.g. `box:/dev/ttyACM0` (Pi) or `box:/dev/cu.usbmodem1` (Mac). The box deliberately has USB only, no WiFi and no Bluetooth. evsoc then switches pins and bus type per vehicle by itself. To try it there is `box:mock://leaf`. Details in [universal-adapter.md](universal-adapter.md), building in [box-build-guide.md](box-build-guide.md).

**Raw CAN** (python-can):

```bash
evsoc read -a "can://slcan//dev/ttyACM0?bitrate=500000"   # CANable with slcan firmware
evsoc read -a "can://gs_usb/0"                             # candleLight
evsoc read -a "can://pcan/PCAN_USBBUS1"                    # PEAK
evsoc read -a "can://socketcan/can0"                       # Linux / Raspberry Pi
evsoc read -a "can://gs_usb/0?fd=1"                        # CAN FD
```

This needs a cable from the OBD socket to the interface (pin 6 = CAN high, pin 14 = CAN low, pin 5 = ground). If the cable taps other pins, e.g. 12/13 on the Nissan Leaf, tell evsoc with `?pins=12,13`. It then assigns the matching profiles correctly.

## Cheap clones

Many cheap "ELM327 v1.5" or "v2.1" adapters have a rebuilt chip that supports only some of the commands. evsoc then reports `The adapter does not know 'ATxx'`. For most Hyundai, Kia, VW and Stellantis profiles a clone is often enough. For BMW (`ATCEA`), long answers and fast queries an OBDLink is worth it.

## Safety

- evsoc only sends read services: `01`, `09` (OBD), `22` (ReadDataByIdentifier), `21`/`1A` (older read services), `10 01`/`10 03` (session change, needed on some cars) and `3E` (TesterPresent), plus reading the fault memory (`19 01`/`19 02`, OBD `03`/`07`/`0A`). Clearing (`14`, OBD `04`) is blocked. Everything else is refused before sending.
- Passive listening (Tesla) sends nothing through ELM adapters, since they use "silent monitoring" by default. A raw CAN interface, however, normally acknowledges received frames (ACK). For purely passive listening use `can://…?listen_only=1`, provided python-can supports it for the interface (e.g. PCAN, Kvaser). With SocketCAN you set it on the interface itself (`ip link set can0 type can bitrate 500000 listen-only on`). evsoc reports an error if the mode does not work instead of carrying on silently. In listen-only mode requests are switched off.
- Do not leave an adapter plugged in permanently: many draw current from the 12 V battery and keep control units awake.
