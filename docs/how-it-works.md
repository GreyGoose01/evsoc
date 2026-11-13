# How it works

## The path of a request

```
evsoc ──"22D410"──► adapter ──CAN frame 6B4: 03 22 D4 10──► battery control unit
evsoc ◄─"6940562D4106D9D"── adapter ◄──CAN frame 694: 05 62 D4 10 6D 9D───┘
```

1. **Service 22 (ReadDataByIdentifier)** from the UDS diagnostic standard: "give me the value with identifier (DID) D410."
2. The adapter packs it into a CAN frame to the address of the control unit (`6B4`). The first data byte is the length (ISO-TP).
3. The control unit answers from `694` with `62` (= 22 + 40, i.e. positive), the identifier `D4 10` and the data `6D 9D`.
4. evsoc calculates: `0x6D9D = 28061`, `28061 / 512 = 54.8 %`.

Longer answers (e.g. Hyundai `220105` with over 40 bytes) arrive in several frames: a first frame with the total length, then consecutive frames. In between the tester sends flow control. Reassembling is called ISO-TP (ISO 15765-2).

Older methods evsoc also uses:

- **OBD service 01** with standardised PIDs, e.g. `015B` (hybrid battery remaining charge), `019A` (voltage/current), `01B2` (SoH)
- **KWP2000 service 21** on older Hyundai/Kia and Toyota
- **Passive listening** on Tesla and others: no request, just read the frame (such as `0x292`) the car sends all the time anyway

## Addressing

| Kind | Example | AT commands |
|---|---|---|
| 11 bit, normal | Hyundai: to `7E4`, answer `7EC` | `ATSP6 ATSH7E4 ATCRA7EC` |
| 11 bit, extended (BMW) | to `6F1` with target address `07` in the first data byte, answer `607` | `ATSH6F1 ATCEA07 ATCRA607` |
| 29 bit, normal fixed | Renault: `18DADBF1` → `18DAF1DB` | `ATSP7 ATCP18 ATSHDADBF1` |
| 29 bit, VW style | `17FC007B` → `17FE007B` | `ATSP7 ATCP17 ATSHFC007B ATCRA17FE007B` |

## Profiles

A profile (JSON, format v2) consists of **steps** and **fields**:

```json
{
  "name": "evsoc_stellantis_ecmp",
  "vehicles": [{"make": "Peugeot", "model": "e-208", "years": [2019, null]}],
  "init": [],
  "steps": [
    {"id": "soc", "at": ["ATSP6", "ATSH6B4", "ATCRA694", "ATCEA", "ATFCSH6B4", "ATFCSD300000", "ATFCSM1"],
     "request": "22D410"}
  ],
  "fields": {
    "soc": {"step": "soc", "decode": {"type": "equation", "expr": "INT16(A,B)/512"},
            "min": -5, "max": 105, "unit": "%"}
  }
}
```

- **Every step brings the complete adapter state with it** (`at`). Steps can therefore be mixed freely, and detection can merge requests of different profiles.
- Optional: `years` (only for these model years), `pre`/`post` (e.g. a session change `1003`), `listen` instead of `request` (passive listening).
- Optional `connection` (whole profile) or `bus` (one step) when it is not plain CAN on 6/14: `{"pins": [12, 13]}`, `{"fd": true, "data_bitrate": 2000000}`, `{"kind": "kline"}`, `{"cable": "Tesla diagnostic cable"}`. Without it evsoc derives the bus from `ATSP`/`ATPB` ([universal-adapter.md](universal-adapter.md)).
- `min`/`max` are plausibility limits. Detection uses them to tell whether a profile fits.
- Optional `confirm`: tells look-alike control units apart by the length of an answer (e.g. a plug-in hybrid and an EV that answer the same address with different scaling).

### Four formula types

| `type` | Origin | counts bytes … | Example |
|---|---|---|---|
| `equation` | ABRP/Torque, own | from the first data byte after `62 xx xx`: `A`, `B`, …, `Z`, `AA` … | `INT16(A,B)/512`, `Signed(K)*256+L`, `{A:3}` |
| `wican` | WiCAN | in the raw CAN bytes **including** length and frame bytes: `B0`, `B1` … | `[B4:B5]/512`, `S21`, `B15:0` |
| `bits` | OBDb | bit exact from the first data byte | `{"bix": 248, "len": 8, "div": 2}` |
| `dbc` | DBC files | in a broadcast frame | `{"start": 10, "len": 10, "factor": 0.1}` |

An example of why this matters: Hyundai `220105`, state of charge in data byte 31.

- OBDb: `bix` 248 (31 × 8)
- WiCAN: `B41`, because 5 frame bytes and 5 header bytes come before it
- ABRP: would have to be `af`

All three describe the same byte. The tests check this with a simulated answer.

## Automatic detection

1. **Read the VIN** (`0902`, else `22F190`). The first three characters give the make, the tenth the model year.
2. **Build candidates.** First profiles of the make, then of group siblings (e.g. Peugeot → Opel, Citroën, DS, Fiat, Jeep) and of the same platform. Last come the standard profile and passive listening. With `--car` the model and platform are used instead.
3. **Try, with a cache.** Only the state of charge steps of each profile. Identical requests (same adapter state plus same command) go to the car only once. The adapter is only reset if settings of another profile would otherwise be left over.
4. **Judge.** A profile fits if a state of charge is plausible. With several hits the winner is: model exact before "all models", more plausible values, known EV platform, then the source (own, OBDb, ABRP, WiCAN). The other hits are listed as "also plausible".

## Code layout

```
evsoc/
  cli.py          command line
  i18n.py         English/German: catalogue lang/de.txt, translation of terminal and web pages
  appliance.py    evsoc run: device service (continuous operation, outputs, display, PIN protected setup)
  config.py       stored device configuration, PIN hash
  detect.py       find the adapter by itself (evsoc box, USB, CAN)
  gui.py          workshop interface (evsoc gui), page in web/index.html
  web/app.html    display of the device, web/setup.html setup, web/i18n.js translator
  reader.py       run profiles, decode, automatic detection
  probe.py        test drive: all candidate profiles completely, report with raw answers
  diag.py         control unit identification and fault memory (read only)
  waketest.py     wake test: can the parked car be woken, does it fall asleep again
  monitor.py      continuous operation: 12 V voltage as wake detection, MQTT/HA, webhook, state file, reading on request
  profiles.py     profile format v2, loading, candidate selection
  vehicles.py     VIN → make/model year, groups, platforms
  decoders.py     equation / wican / bits / dbc
  equation.py     Torque/ABRP formulas (own parser, no eval)
  connection.py   OBD type per profile step (bus, pins, bitrate, passive), adapter capabilities, check
  universal.py    evsoc box: bus choice (EVSBUS), listen mode, bus scan
  wired.py        wired-only mode: USB detection, SocketCAN, binding to a network interface
  elm.py          ELM327/STN: AT commands, state cache, ISO-TP, listening
  canbus.py       raw CAN over python-can: own ISO-TP, CAN FD
  enet.py         BMW ENET (HSFZ over TCP 6801)
  enet_sniff.py   ENET listener (man in the middle between app and car)
  sniff.py        listening in on other apps: conversations, formula search, profile writer
  broadcast.py    signals in cyclic broadcast frames, reference values from a second adapter
  analyse.py, pcap.py   condense a complete CAN/Ethernet recording into a report
  transports.py   serial/Bluetooth, WiFi, BLE, logging
  safety.py       read-only guard
  importers.py    OBDb, ABRP, WiCAN → profiles (evsoc update)
  mock.py         simulated ELM327 with test vehicles
  profiles/own/        own profiles
  profiles/generated/  imported profiles (do not edit by hand)
  lang/de.txt          German texts (the source texts are English)
```
