# Building the universal adapter yourself

This guide describes two ways to build it. What the box should do and why is in [universal-adapter.md](universal-adapter.md). The commands its firmware has to understand are in [box-protocol.md](box-protocol.md).

| | **A: Raspberry Pi + CAN board** | **B: evsoc box with STM32** |
|---|---|---|
| works with evsoc today | yes (`can://socketcan/…`) | firmware 0.1 exists, tested in the simulator, **not yet tested on hardware** |
| Buses | CAN and CAN FD on 6/14, second channel on 3/11 or 12/13 | stages 1–2: two CAN channels; later K-line, Ethernet |
| Switching pins | by hand (switch) | by software (relays) |
| 12 V measurement (wake detection) | no, evsoc recognises "awake" from bus traffic | yes (`ATRV`) |
| Parts without a Pi | about 60–80 € | about 70–100 € |

**Recommendation:** start with way A. It works immediately, and the OBD cable and wiring can be reused for B later.

## Safety rules

1. **No termination resistor.** The vehicle bus is already terminated with 120 Ω at both ends. Switch the termination off on every CAN board and transceiver module (jumper or switch).
2. **Never 12 V on logic pins.** Pin 16 carries on-board voltage with spikes far above that. It goes only through a fuse (1 A) to the voltage divider or an automotive converter.
3. **Ground is pin 5** (signal ground). Pin 4 is chassis ground and is not needed in a clean build.
4. **Keep it short.** At most 30 cm from the connector to the transceiver. A long stub disturbs the vehicle bus.
5. **Listen first.** Do the first test on the car in listen-only mode. Then the build sends nothing, even in a fault case.
6. **Read only.** evsoc sends read services only. Other programs on the same build are not protected by that.
7. **Avoid different grounds.** If the Pi runs on the house network and only the adapter is in the car, put a USB isolator in between (see [raspberry-pi.md](raspberry-pi.md)).

## OBD socket

The pins are stamped small on socket and plug.

| Pin | Assignment |
|---|---|
| 6 / 14 | CAN high / CAN low (diagnostic CAN, all EVs) |
| 3 / 11 | maker specific, e.g. Ford MS-CAN, Leaf AV-CAN, Ethernet receive |
| 12 / 13 | maker specific, e.g. Leaf EV-CAN (up to 2017), Ethernet transmit |
| 7 / 15 | K-line / L-line (older hybrids) |
| 1 | GM single-wire CAN, Ethernet option 2 |
| 8 | Ethernet activation (DoIP) |
| 4 / 5 | chassis ground / signal ground |
| 16 | +12 V permanent |

**OBD cable:** buy an OBD plug with an open cable end where **all 16 pins** are wired. Many cheap cables have only 4 to 6 wires. Before connecting, ring out every wire with a multimeter and note the colours.

## Way A: Raspberry Pi with CAN board

### Parts

| Part | Example | approx. price |
|---|---|---|
| Raspberry Pi | Pi 4 or 5 (already have one?) | – |
| CAN board, 2 channels | Waveshare **2-CH CAN FD HAT** (MCP2518FD, galvanically isolated) | 40–50 € |
| OBD cable | plug with open end, 16 wires | 10–15 € |
| Changeover switch for channel 2 | toggle switch 2-pole, ON-ON (2× changeover) | 3 € |
| Wire, heat shrink, small case | – | 5–10 € |

Single-channel boards (MCP2515 or MCP2518FD) are enough if only pins 6/14 are needed. The MCP2515 cannot do CAN FD.

### Wiring

```
 OBD 6  (CAN-H) ───────────── CAN0 H
 OBD 14 (CAN-L) ───────────── CAN0 L
 OBD 5  (ground) ──────────── CAN0 GND and CAN1 GND

                       ┌─ position 1 ── OBD 3  / OBD 11
 CAN1 H / CAN1 L ── switch
                       └─ position 2 ── OBD 12 / OBD 13
```

- Switch the termination resistors off on **both** channels (jumper on the board).
- Pin 16 stays free, the Pi gets its power separately (see [raspberry-pi.md](raspberry-pi.md#power-supply)).

### Setting up

1. Take the `dtoverlay` lines for both channels from the [Waveshare wiki](https://www.waveshare.com/wiki/2-CH_CAN_FD_HAT). They depend on the board version and the position of the solder bridges.
2. Reboot and check: `ip link` shows `can0` and `can1`.
3. Switch both channels on. For the first test on the car, listen only:

```bash
sudo ip link set can0 up type can bitrate 500000 listen-only on
sudo ip link set can1 up type can bitrate 500000 listen-only on
candump can0          # from can-utils: is there traffic when the car is awake?
```

4. Set up permanently with [deploy/80-can0.network](../deploy/80-can0.network), and a copy with the name changed for `can1`.

### Using it with evsoc

```bash
evsoc read -a can://socketcan/can0                            # diagnostics on 6/14 (most cars)
evsoc read -a "can://socketcan/can0?fd=1"                     # cars with CAN FD (board with MCP2518FD)
evsoc read -a "can://socketcan/can1?pins=12,13" --car "Leaf"  # Leaf up to 2017: EV-CAN, switch in position 2
```

`?pins=` tells evsoc which pins the channel is on. It then picks the matching profiles.

For the device (`evsoc run`) put the channel in the configuration, otherwise the automatic search takes the first one it finds. In `/var/lib/evsoc/config.json`:

```json
"adapter": "can://socketcan/can1?pins=12,13"
```

## Way B: evsoc box with STM32

The box is built up in stages. Every stage is usable on its own.

| Stage | Content | Result |
|---|---|---|
| 1 | Nucleo board, 1 CAN channel on 6/14, 12 V measurement | works with evsoc like an OBDLink |
| 2 | 2nd CAN channel, relay pin matrix for 3/11 and 12/13, listen-only | Leaf EV-CAN, bus search (`EVSSCAN`) |
| 3 | CAN FD, K-line, single-wire CAN | all classic buses |
| 4 | Ethernet: BMW HSFZ, then DoIP (ISO 13400) | BMW without an ENET cable |
| 5 | own board, quiescent current below 1 mA, case | stays in the car permanently |

### Parts for stages 1 and 2

| Part | Example | Qty | approx. price |
|---|---|---|---|
| Microcontroller board | ST **NUCLEO-H723ZG** (3× CAN FD, Ethernet, USB) | 1 | 30 € |
| CAN transceiver module | Adafruit **CAN Pal** (TJA1051T/3, CAN FD up to 5 Mbit/s, 3.3 V logic, termination by switch, silent pin) | 2 | 8–10 € each |
| OBD cable | plug with open end, 16 wires | 1 | 10–15 € |
| Signal relay, 2× changeover, 5 V | e.g. Omron G6K-2F-Y 5V or Panasonic TQ2-5V | 2 | 3–5 € each |
| Relay driver | ULN2003A (contains the flyback diodes) | 1 | 1 € |
| Voltage divider | resistors 47 kΩ and 10 kΩ, capacitor 100 nF, Schottky dual diode BAT54S | 1 each | 1 € |
| Fuse | holder with 1 A fine fuse | 1 | 3 € |
| Perfboard, pin headers, stranded wire | – | – | 10 € |

### Stage 1: one CAN channel on 6/14

```
 NUCLEO-H723ZG                    CAN Pal 1                 OBD plug
 PD1 (FDCAN1_TX) ───────────────► TX
 PD0 (FDCAN1_RX) ◄─────────────── RX
 GPIO "SILENT1"  ───────────────► SLNT     CANH ──────────► 6
 3V3             ───────────────► VIN      CANL ──────────► 14
 GND             ───────────────► GND ─────────────────────► 5
                                  termination switch: OFF

 12 V measurement:
 OBD 16 ── fuse 1 A ── 47 kΩ ──┬── ADC input (e.g. A0)
                               ├── 10 kΩ ── GND
                               ├── 100 nF ── GND
                               └── BAT54S (to GND and 3V3)
```

- **FDCAN1 on PD0/PD1** is the usual assignment on the Nucleo-H7 boards. Check the position on the Zio connector CN9 in the [schematic MB1364](https://www.st.com/resource/en/schematic_pack/mb1364-h723zg-e01_schematic.pdf) before soldering.
- **TX to TX, RX to RX:** on the transceiver, `TX` is the input for the controller's transmit signal.
- **SLNT** high switches the TJA1051 transmitter off in hardware. The firmware sets the pin in listen-only mode and after power-up, until evsoc asks for something else. So "listen only" is guaranteed in hardware too.
- **Voltage divider:** 47 kΩ / 10 kΩ divides by 5.7. 3.3 V at the ADC then equals 18.8 V. The diode protects the input against voltage spikes, the capacitor smooths.
- **Power:** in stages 1 and 2 the Pi or computer supplies the box through the microcontroller's USB socket (USB OTG, not the ST-LINK socket). Pin 16 is only used for measuring.

### Stage 2: second channel and pin matrix

```
 FDCAN2 TX/RX ── CAN Pal 2 (TX, RX, SLNT on "SILENT2", termination OFF)
                        CANH ─┬─ K1 contact 1 (normally open) ── OBD 12
                              └─ K2 contact 1 (normally open) ── OBD 3
                        CANL ─┬─ K1 contact 2 (normally open) ── OBD 13
                              └─ K2 contact 2 (normally open) ── OBD 11

 GPIO "REL_12_13" ── ULN2003A ── coil K1 (5 V)
 GPIO "REL_3_11"  ── ULN2003A ── coil K2 (5 V)
```

- **Without power all relays are open.** So channel 2 is on no pin until the firmware switches a relay on `EVSBUS CAN 12,13 …`. The firmware never switches both at once.
- **FDCAN2 pins:** assign them in STM32CubeMX and check against the schematic for conflicts. Some pins on the Nucleo are already used by Ethernet and the Arduino SPI.
- **Relay coils** on 5 V from the Nucleo (from USB). Two small signal relays together draw under 100 mA.

### Firmware

**Status:** firmware 0.1 in [firmware/](../firmware/README.md) for stages 1 and 2. The core runs as a simulator on the PC and is tested there with evsoc (BMW addressing, 29 bit, flow control, read filter, listening). The STM32 port compiles against the ST drivers but has not yet run on real hardware. Setup in STM32CubeIDE and installation: [firmware/README.md](../firmware/README.md).

The most important settings:

| Block | Setting |
|---|---|
| FDCAN1 | kernel clock 80 MHz; nominal: prescaler 10, seg1 13, seg2 2, SJW 2 → **500 kbit/s**, sample point 87.5 % |
| FDCAN1, CAN FD data phase | prescaler 2, seg1 15, seg2 4, SJW 4 → 2 Mbit/s, sample point 80 %, transceiver delay compensation on |
| FDCAN, listening | mode "bus monitoring", plus SLNT high |
| USB | USB_OTG_HS as device with internal full-speed PHY, middleware "CDC" (virtual COM port) |
| ADC1 | one channel on the voltage divider, average over a few measurements |

Try it without hardware: `make -C firmware`, then `firmware/evsoc-box-sim bmw-i3` and `evsoc read -a box:<port printed>`.

### Testing

1. **Without a car:** `evsoc read -a box:/dev/ttyACM0 --log box.txt` must recognise `EVSI`. If the identification is missing, evsoc rejects the box.
2. **On the bench:** connect CAN Pal 1 and 2 directly (H to H, L to L) and switch the termination on at both, **only here**. Channel 2 then sees in listen mode what channel 1 sends.
3. **On the car:** first `evsoc scan -a box:/dev/ttyACM0` (sends nothing), then `evsoc read -a box:/dev/ttyACM0`.

## Later: own board (stage 5)

The lab build is not enough for continuous operation in the car. You then need a step-down converter with a very small quiescent current, reverse polarity protection, a TVS diode against load dump, PhotoMOS instead of mechanical relays and a sleep mode that bus activity ends (e.g. with the TJA1463). The choice of parts is in [universal-adapter.md](universal-adapter.md#parts-for-your-own-board).
