# evsoc box: protocol 0.1

This describes what a universal adapter firmware must be able to do so that evsoc can use it through `box:…`. The other side is implemented in `evsoc/universal.py`, the simulation in `evsoc/mock.py` (`MockBoxTransport`).

## Basics

- **Transport:** USB CDC only (virtual serial port, `/dev/ttyACM0` on Linux). The box has no WiFi and no Bluetooth. The baud rate does not matter with USB CDC.
- **Format as with the ELM327:** command plus `CR`, reply lines separated by `CR`, at the end the prompt character `>`.
- **ELM327 command set:** the box must support at least what evsoc profiles use: `ATZ ATD ATI ATE0 ATL0 ATS0 ATH1 ATD0 ATRV ATSP ATSH ATCP ATCRA ATCEA ATCAF ATFCSH ATFCSD ATFCSM ATST ATAT ATAL ATPB ATMA`, plus diagnostic requests as hex text. That also lets other OBD programs that talk to an ELM327 over USB work with it.
- **Reply format for data** as with the ELM327 with `ATH1 ATS0 ATD0`: one line per CAN frame, `<CAN ID><data bytes>` in hex. With CAN FD, frames may have more than 8 data bytes.
- **`ATZ`/`ATD`** also reset the bus choice to CAN on 6/14 and switch listen mode off.

## Additional commands

### `EVSI`: identification and capabilities

```
>EVSI
EVSOC-BOX 0.1 KINDS=CAN,CANFD PINS=6/14,12/13,3/11 LISTEN=1
```

| Field | Meaning |
|---|---|
| `EVSOC-BOX <version>` | must be at the start of the line, otherwise evsoc rejects the adapter as a box |
| `KINDS=` | supported bus types: `CAN`, `CANFD`, `KLINE`, `J1850`, `SWCAN`, `DOIP` |
| `PINS=` | reachable pin pairs, e.g. `6/14,12/13`, or `ANY` |
| `LISTEN=1` | listen-only mode present |

### `EVSBUS`: choose the bus

```
EVSBUS <KIND> <PINS> [BITRATE] [DATA BITRATE]
```

| Example | Meaning |
|---|---|
| `EVSBUS CAN 6,14 500000` | high-speed CAN on the standard pins |
| `EVSBUS CAN 12,13 500000` | second bus on 12/13 (e.g. Nissan Leaf EV-CAN) |
| `EVSBUS CANFD 6,14 500000 2000000` | CAN FD, 500 kbit/s arbitration, 2 Mbit/s data |
| `EVSBUS KLINE 7,15 10400` | K-line |
| `EVSBUS SWCAN 1 33333` | GM single-wire CAN |
| `EVSBUS DOIP 1` | Ethernet per ISO 13400-4 option 1 (pins 3/11/12/13, activation pin 8); `2` = option 2 |

The reply is `OK` or `ERR <reason>`, e.g. `ERR PINS` (pin pair cannot be switched) or `ERR ETHERNET-ON-PINS` (Ethernet is on those pins, CAN is not switched on). The protocol details (11/29 bit, header, filter) still come through the normal ELM commands (`ATSP`, `ATSH`, `ATCRA` …). `EVSBUS` only chooses pins, transceiver and bitrate.

### `EVSLISTEN`: listen only

```
EVSLISTEN 1      # listen-only: no acknowledgements (ACK), no error frames, no sending
EVSLISTEN 0
```

With `EVSLISTEN 1` the box answers diagnostic requests with `ERR LISTEN-ONLY`. Listening is done with `ATCRA <ID>` and `ATMA`.

### `EVSSCAN`: search for active buses

```
>EVSSCAN
BUS CAN 6,14 500000 FRAMES=812 IDS=1A0,1A1,5C0,7BB
BUS CAN 12,13 500000 FRAMES=240 IDS=55B,5BC
BUS DOIP 1 100000000
OK
```

The box searches in listen-only mode only (procedure in [universal-adapter.md](universal-adapter.md#firmware)). Afterwards it sets CAN on 6/14 again. The duration is limited, evsoc waits up to 30 seconds.

## Safety requirements for the firmware

1. **Read-service filter in the firmware:** only the services `01`, `09`, `21`, `22`, `1A`, `10 01`, `10 03` and `3E` may be sent, reject everything else with `ERR BLOCKED`. This applies to requests from other apps as well.
2. **Raw sending** (`ATCAF0` with own frames) only if the content matches an allowed request.
3. **No termination resistor** on any bus.
4. **Detect Ethernet first:** before a CAN transceiver is switched onto 3/11, 1/9 or 12/13, check pin 8.
5. **Undervoltage:** below about 11.8 V send no more requests and go to sleep mode.
6. **No radio:** the hardware has no radio interface. The firmware may only be reachable over USB.

## Versioning

New commands are added with a new version number in `EVSI`. evsoc evaluates only the fields it knows.
