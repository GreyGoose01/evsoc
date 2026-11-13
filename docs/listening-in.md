# Listening in on other apps (`evsoc sniff`)

Car Scanner, EV Scanner, BimmerLink, Leaf Spy and others know values for many cars that evsoc still lacks. `evsoc sniff` listens in while such an app runs and learns from it:

- which requests the app sends to which control unit (including flow control, 11/29 bit, BMW addressing),
- which of them evsoc already knows (with the values the profiles compute from them) and which are **new**,
- which formula gives a value read off the app,
- and, if you want, writes a finished evsoc profile from that.

If it is not about an app but about the **complete traffic** on the bus (including Automotive Ethernet), [`evsoc analyse`](analyse.md) is the right tool.

evsoc sends no diagnostic requests itself while doing this. When listening on CAN it only listens. When listening on ENET it passes the app's messages through unchanged.

**Wired-only does not apply here.** The wired-only principle is meant for evsoc in continuous operation and for the evsoc box. For listening in, phone, Bluetooth and WiFi are explicitly allowed, so `sniff` ignores the `--wired-only` setting.

---

## 1. Which way fits? (decision plan)

What matters is **how the app talks to the car**, not how the phone talks to the adapter (Bluetooth, BLE, WiFi do not matter).

| App adapter | how it talks to the car | how evsoc listens in | Section |
|---|---|---|---|
| OBDLink MX+, CX, LX, ELM327 (BT/BLE/WiFi/USB), vLinker, Veepeak, WiCAN | CAN on pins 6/14 | **Y cable + CAN interface** on the Pi/Mac | [2](#2-listening-to-can-with-a-y-cable) |
| ENET adapter with WiFi/LAN (UCSI-3000 and similar) | Ethernet (pins 3/11/12/13 + 8) | **put evsoc in between** (`enet-proxy://`) | [3](#3-listening-to-enet-bmwmini) |
| ENET cable on a laptop (ISTA, E-Sys, BimmerCode Windows/Mac) | Ethernet | **put evsoc in between** | [3](#3-listening-to-enet-bmwmini) |
| the app's own adapter (Carly, BimmerLink adapter …) | mostly CAN on 6/14 | Y cable + CAN interface, otherwise as above | [2](#2-listening-to-can-with-a-y-cable) |
| CAN FD cars (newer GM, some new models) | CAN FD on 6/14 | Y cable + **CAN FD** interface (`?fd=1`) | [2](#2-listening-to-can-with-a-y-cable) |
| Leaf Spy and others on special buses (Leaf EV-CAN 12/13) | CAN on other pins | Y cable that passes **all 16 pins** + interface/box on those pins | [2](#2-listening-to-can-with-a-y-cable) |
| older hybrids with K-line (7/15) | K-line | **not supported yet** | [6](#6-limits) |

**Can the OBDLink MX+ do ENET?** No. The MX+ can do all OBD protocols (CAN, K-line, J1850) and on GM/Ford also SW-CAN/MS-CAN, but no Ethernet/ENET. BMW apps (BimmerLink, BimmerCode) talk to the MX+ over the **CAN bus on pins 6/14 (D-CAN)**. BMW F/G/I cars have that in addition to ENET. It is slower, but can be listened to normally with a Y cable. Whether an app gets the battery values over CAN on a given car shows in the first try: if no requests appear while the app runs, it gets the values over ENET only.

For a BMW/Mini there are therefore two ways that complement each other:

1. **App + MX+ over CAN**, listened to with a Y cable. Works in parallel with a CAN interface on the Pi.
2. **App + UCSI-3000 over ENET**, listened to with `enet-proxy://`. Works without a Y cable.

---

## 2. Listening to CAN with a Y cable

```
 OBD socket ── Y cable ──┬── the app's adapter (e.g. OBDLink MX+) ⟷ Bluetooth ⟷ phone
                         └── CAN interface ⟷ USB ⟷ Raspberry Pi or Mac (evsoc sniff)
```

### Hardware for the second branch

| second adapter | address (`-a`) | Note |
|---|---|---|
| **CANable 2.0 with slcan firmware** (USB, about 20–35 €) | `"can://slcan//dev/ttyACM0?bitrate=500000"` (Pi), `…//dev/cu.usbmodemXXXX…` (Mac) | **Recommended:** true listen-only (no ACK), no driver needed |
| candleLight / gs_usb (CANable with candleLight firmware, FYSETC UCAN) | `can://gs_usb/0` | Pi/Mac: `pip install pyusb`, Mac also `brew install libusb`. Cannot do listen-only through python-can, so it acknowledges messages (ACK) like any control unit, but sends nothing itself |
| CAN add-on board on the Pi (Waveshare, PiCAN, MCP2515) | `can://socketcan/can0` | beforehand `sudo ip link set can0 down && sudo ip link set can0 type can bitrate 500000 listen-only on && sudo ip link set can0 up` |
| CAN FD interface | `"can://gs_usb/0?fd=1"`, `can://socketcan/can0` with FD | only needed on CAN FD cars |
| second ELM327/OBDLink over USB (e.g. OBDLink SX) | `/dev/ttyUSB0` or `/dev/cu.usbserial-X` | monitor mode `ATMA` without ACK. Give the protocol: `--protocol 6` (11 bit, default) or `7` (29 bit). Clones lose messages under heavy traffic |
| evsoc box | `box:/dev/ttyACM0` | listen-only, `--pins 12,13` for other buses |

A CAN interface sees 11 and 29 bit messages at the same time. With ELM/OBDLink/box the protocol must be right beforehand, because nothing is sent to detect it.

### Cable

- **Y cable:** for CAN, pins 4/5 (ground), 6/14 (CAN) and 16 (12 V) are enough. For special buses (Leaf 12/13, Ford 3/11) and for ENET on the same Y cable it must pass **all 16 pins**. Cheap Y cables often do not, so check with a multimeter.
- **From the Y cable to the CAN interface:** OBD plug to open wires or DB9. Pin 6 = CAN high, pin 14 = CAN low, pin 5 = ground. With DB9 check the interface's pinout, common is CAN-L 2, ground 3, CAN-H 7.
- **Termination off:** the 120 Ω jumper on the interface must be open, because the bus in the car is terminated already.

### Procedure

```bash
evsoc sniff -a "can://slcan//dev/ttyACM0?bitrate=500000"
```

1. Ignition on or car "ready". Then connect the app with the MX+ on the phone and open **only one** value (e.g. state of charge). That makes it clear which request belongs to it.
2. evsoc shows each new request once:
   ```
   21:03:10.295  6B4 → 694  22 D4 10   2 bytes  known: evsoc_stellantis_ecmp (soc 79.96 %)
   21:03:10.400  7E4 → 7EC  22 01 05  46 bytes  NEW to evsoc
   ```
3. Type the value the app shows right now into the terminal, e.g. `soc 80.5` + Enter. evsoc notes it with the time. **At least twice at different values**, for example before and after a drive, or while charging. Then usually exactly one formula is left.
4. Open the next value in the app, type it again, e.g. `voltage 398.4` or `batt_temp 21`.
5. `Ctrl+C`. evsoc summarises: all requests, frequency, last data, changing bytes (`A`, `B` … as in the formulas), warnings and the formula search.

`--show-all` shows every single answer, changed bytes are in `[ ]`. That is handy to see live which byte moves along while charging.

---

## 3. Listening to ENET (BMW/Mini)

ENET is Ethernet between exactly two devices. A Y cable does not work here, two devices on the same lines disturb the connection. Instead evsoc sits **in the middle**: to the app evsoc looks like an ENET adapter, and everything the app sends, evsoc passes on unchanged to the UCSI-3000 or the ENET cable. The answers go back the same way.

```
 App (phone/laptop) ──WiFi/LAN──► evsoc (Pi/Mac)  TCP 6801 + vehicle search UDP 6811 ──► UCSI-3000/ENET cable ──► car
```

```bash
evsoc sniff -a enet-proxy://auto                          # find car/adapter by itself
evsoc sniff -a enet-proxy://192.168.16.254                 # fixed address (e.g. UCSI gateway)
evsoc sniff -a "enet-proxy://auto?vin=WBY71AW0XXXXXXXXX"   # give the VIN for the search answer
evsoc sniff -a "enet-proxy://auto?discovery=0"             # do not answer the vehicle search (app with a fixed IP)
evsoc sniff -a "enet-proxy://auto?listen=192.168.1.50"     # listen on this address only
```

evsoc answers the app's vehicle search with the real car's answer. If the adapter gives none, evsoc builds its own with the car's VIN. Output, formula search, profile export and capture are the same as with CAN. The requests appear as BMW addressing (`6F1[07] → 607`), and profiles generated from them work over ENET **and** over CAN adapters.

### Setups on the Pi

**Variant A: Pi as WiFi hotspot (recommended)**

```
 phone ──WiFi "evsoc-sniff"──► Pi wlan0 (hotspot, 10.42.0.1)
                               Pi USB LAN (enx…) or eth0 ──LAN──► UCSI-3000 ──► car
```

The phone is connected only to the Pi. So the app's vehicle search sees only evsoc and not the UCSI or the car in addition, and evsoc passes everything on. Connect the UCSI by LAN as in [test-bmw-i4.md](test-bmw-i4.md). Its own WiFi is not needed.

Switch on the Pi's WiFi once. In device operation it is off via `dtoverlay=disable-wifi`, see [raspberry-pi.md](raspberry-pi.md):

```bash
sudo sed -i 's/^dtoverlay=disable-wifi/#dtoverlay=disable-wifi/' /boot/firmware/config.txt && sudo reboot
```

Then start the hotspot for every session (Raspberry Pi OS with NetworkManager):

```bash
sudo nmcli dev wifi hotspot ifname wlan0 ssid evsoc-sniff password evsoc-sniff-1
```

Connect the phone to `evsoc-sniff`, then press "Connect" in the app. End the hotspot with `sudo nmcli con down Hotspot`. If you want to run the Pi as a wired-only device again afterwards, re-enable the line in `config.txt` (remove the `#`) and reboot.

**Variant B: phone on the home WiFi**

```
 phone ──home WiFi──► router ──LAN──► Pi eth0
                                     Pi USB LAN (enx…) ──LAN──► UCSI-3000 ──► car
```

Without a hotspot, if the home WiFi reaches the car (garage, driveway). The app searches in the home network and finds evsoc on the Pi.

**Variant C: everything on the laptop/Mac**

Laptop by LAN cable on the UCSI-3000 or the ENET cable, app on the phone in the same network as the laptop. If the app runs on the same laptop (E-Sys, ISTA, BimmerCode for Windows/Mac), enter `127.0.0.1` as the address in the app and set `?discovery=0`.

**Variant D: ENET cable instead of UCSI**

An ENET cable (OBD to RJ45) on the Pi's USB LAN adapter works just like the UCSI by LAN. The car then has a 169.254 address, `enet-proxy://auto` finds it by searching.

### If the app does not find evsoc

I have only tested evsoc against rebuilt gateways, not yet with real apps. Apps find ENET adapters in different ways. Try in this order:

1. **Enter the address yourself:** many apps allow a fixed IP under "Adapter/ENET/WiFi". Enter the Pi's address there (variant A: `10.42.0.1`, variant B: its home network IP).
2. **See what the app tries:** run `sudo tcpdump -ni any port 6801 or port 6811` on the Pi and press "Connect" in the app. If no packets appear, the app searches at a fixed address.
3. **The app expects the fixed UCSI address** (e.g. `192.168.16.254`): in variant A give the hotspot exactly this address (`nmcli con modify Hotspot ipv4.addresses 192.168.16.254/24`, then reconnect). Since the UCSI itself has this address, that works only with an ENET cable as the connection to the car (variant D), otherwise two devices would have the same address.
4. **evsoc reports "port 6801 is in use":** stop the service, see [section 4](#4-on-the-raspberry-pi).

Once it is clear what a particular app needs, it goes into this list.

---

## 4. On the Raspberry Pi

```bash
ssh pi@evsoc.local
sudo systemctl stop evsoc                # evsoc run frees the adapter, CAN and port 6801
cd ~ && evsoc sniff -a … -o ~/capture-$(date +%F).log
# … type values from the app straight into the SSH session, e.g. "soc 80.5", end with Ctrl+C
sudo systemctl start evsoc               # continuous operation back on
```

- Fetch the capture with `scp pi@evsoc.local:~/capture-*.log .` to the Mac and evaluate it there as often as you like with `evsoc sniff -d …`.
- If the SSH connection drops, the capture ends too. For long sessions start in `tmux` (`sudo apt install tmux`, then `tmux`, reconnect with `tmux attach`).
- 12 V battery: for longer sessions put the car in "ready" or charge it. See [continuous-operation.md](continuous-operation.md).

---

## 5. Evaluating and building a profile

The capture ends up as `capture-DATE.log` (candump format, readable with can-utils, SavvyCAN, python-can). Typed values are in it with the time. Evaluate again later:

```bash
evsoc sniff -d capture.log
evsoc sniff -d capture.log --value soc=54.8@21:03:10 --value soc=79.9@21:40:00   # values added afterwards, with time
evsoc sniff -d capture.log --json                                                  # for further processing
```

`-d` also reads foreign captures: candump (`-L`, default, `-ta`), raw `ATMA` output, `.asc`, `.blf`, `.trc`, `.csv`. Also the text files of the CL1000/CL2000 loggers (`Timestamp;Type;ID;Data`, not yet checked with a real file). When a pure capture is enough: [test-drive.md](test-drive.md#is-a-pure-can-capture-enough-eg-cl2000).

### Formula search

For every answered read request evsoc tries every byte and byte pair as 8/16/24 bit (signed and unsigned, also little-endian), with the usual scalings (`/2`, `/10`, `/16`, `/512`, `*100/255` …) and temperature offsets (`-40`, `-50`). Hits must explain all the values read off. The tolerance follows the decimal places typed ("79.96" means ±0.01, "80" means ±1), but at least 0.25 %, because apps do not always round exactly (Corsa-e: app 54.79 %, formula 54.81 %). Your own tolerance: `--tolerance 0.5`.

```
  soc = 54.79, 79.96
    6B4 → 694  22 D4 10   INT16(A,B)/512   gives 54.81, 79.96
```

Common names: `soc`, `soc_display`, `soc_bms`, `soh`, `voltage`, `current`, `batt_temp`, `cell_min_voltage`, `cell_max_voltage`, `energy_available`. evsoc takes unit and plausibility limits from them.

### Creating a profile

```bash
evsoc sniff -d capture.log --value soc=54.79@21:03:10 --value soc=79.96@21:40:00 --value voltage=426.2 \
            --write-profile evsoc_my_car.json --car "Opel Corsa-e"
```

For every value evsoc takes the best formula and builds the AT commands so that an adapter repeats exactly the app's request (`ATSP`, `ATSH`/`ATCP`, `ATCRA`, `ATCEA`, with differing flow control `ATFCSH`/`ATFCSD`/`ATFCSM1`). If the app changed the diagnostic session beforehand (e.g. `10 03`, extended session), evsoc takes that into the step as `"pre": ["1003"]`. The profile is checked before writing and needs at least one state-of-charge value (`soc…`). Then check it, copy it to `evsoc/profiles/own/` and test it on the car: [own-profiles.md](own-profiles.md).

---

## Broadcast messages: finding values without a request

Behind a gateway (tap on an internal bus), and on cars without a gateway at the socket, the control units send their values by themselves at a fixed rate. Nobody asks there, so there are no request/answer pairs. evsoc instead searches every message for a bit field and a scaling that fit reference values with a time.

The reference values come in two ways:

```bash
# 1. automatic: a second adapter reads the car by diagnostics, the first only listens
evsoc sniff -a "can://slcan//dev/ttyACM0?bitrate=500000" --reference enet://auto --car i4 --duration 1800

# 2. by hand: type values while listening ("soc 54.3" + Enter) or give them afterwards
evsoc sniff -d capture.log --value soc=54.3@12:01:10 --value soc=57.0@12:20:40
```

With `--reference` evsoc reads all the profile's values every 10 seconds (`--reference-interval`) and notes them with the time in the capture. In the interface: Tools → Listen in on other apps → Reference adapter.

Output:

```
Broadcast messages: 6 IDs. Searching for the noted values:

  soc: 6 reference values, 6 different (54.3 … 60.1)
    3A5  byte 3–4 (16 bit, most significant first) × 0.01   deviation at most 0, 6 different values hit
    1F0  byte 2 × 0.5   deviation at most 0.2, 6 different values hit
    For a profile: step {'id': 'b3A5', …, 'listen': '3A5'}  field decoder {'type': 'dbc', 'start': 23, 'len': 16, …}
```

What the search can and cannot do:

- It checks single bytes, 16 bit fields in both byte orders (also signed) and 10 or 12 bit fields on byte boundaries, each with the usual scalings and offsets. If no usual one fits, evsoc shows a fitted one and marks it as an "odd scaling".
- **The significance depends on the number of different reference values.** With a single value many bytes fit by chance. From three different values on it becomes reliable. So record long enough that the value moves: a drive or a charge.
- Counters and constants are sorted out. Fast changing values such as current and power fit badly in time with reference values at a 10 second rate.
- So far it is only checked with an artificial capture, on no car. The signal search works on CAN and CAN FD only. Ethernet recordings (pcap) are evaluated by `evsoc analyse` ([analyse.md](analyse.md)), FlexRay evsoc does not read.
- Taking it into a profile is manual work: copy step and decoder from the output into a profile file ([own-profiles.md](own-profiles.md)).

## 6. Limits

| Case | Status | Way out |
|---|---|---|
| K-line (older hybrids, pin 7/15) | evsoc does not listen to K-line | capture from the app itself (Car Scanner: export log) |
| App reads broadcast messages only (e.g. Tesla apps, no request/answer) | evsoc shows these IDs and their changing bytes, and the broadcast search above finds formulas in them | DBC data from OBDb/opendbc |
| Values in bit fields (e.g. 10 bit across byte boundaries) | the request/answer formula search works byte by byte | look at the changing bytes, write the bit field by hand as a `bits` decoder |
| App uses security access (`27`) before reading | evsoc sees this and warns. The profile alone is then not enough | such values stay out (evsoc sends no `27`) |
| Very busy bus, ELM clone as listener | `BUFFER FULL`, gaps | use a CAN interface |
| ENET: app does not find evsoc | see [section 3](#if-the-app-does-not-find-evsoc) | |

## 7. Safety

- **CAN:** evsoc sends no messages. ELM adapters run in "silent monitoring" (`ATCSM1`), the evsoc box with `EVSLISTEN 1`, CAN interfaces in listen-only mode, if they can do it. An interface without listen-only acknowledges messages (ACK) like any control unit, but sends nothing itself. evsoc points this out.
- **ENET:** evsoc passes the app's messages through unchanged and creates no diagnostic requests itself. Only exception: if the adapter does not answer the vehicle search, evsoc reads the VIN once at the start (`22F190`, read only). With `?vin=…` or `?discovery=0` even that is skipped.
- **What the app does is the app's responsibility.** If it sends writing, clearing or coding services (`2E`, `14`, `31`, `27` …), evsoc marks that clearly. Coding apps (BimmerCode, E-Sys) through `enet-proxy://` can change the car. For searching values, diagnostic apps in read mode are enough.
- `ATMA` stays blocked for `read`/`raw`. Only `sniff` and listening to single IDs use it internally.
