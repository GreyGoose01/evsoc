# Evaluating the complete traffic (`evsoc analyse`)

`evsoc sniff` searches specifically for the requests of another app. `evsoc analyse`, by contrast, takes **everything** on the bus or the line and condenses it into a report that you can give to Claude. A raw capture of a few minutes has hundreds of thousands of lines and is too big to paste. The report has a few hundred lines and contains what you need for decoding.

evsoc sends nothing while doing this.

```bash
evsoc analyse -a "can://slcan//dev/ttyACM0?bitrate=500000"    # record CAN on a Y cable, end with Ctrl+C
evsoc analyse -a eth://eth0 --duration 60                     # record Ethernet (Linux, root)
evsoc analyse -d capture.log                                  # evaluate an existing capture
evsoc analyse -d drive.pcapng                                 # evaluate a Wireshark/tcpdump recording
evsoc analyse -a mock://tesla-m3 --duration 5                 # try it without a car
```

At the end it says `Report: capture-….analyse.md`. You give this file to Claude (upload or paste the content) and write what you want to know, e.g. "Which message contains the state of charge?" or "What changes when the door is opened?".

## Taking notes during the recording

Type into the terminal what you are doing or reading off, each with Enter:

```
door open
charging started
soc 80.5
```

Every line ends up in the capture and in the report with its time. This is the most important part: it is the only way to tell which bit belongs to the door and which number to the state of charge. Best change only **one** thing at a time and wait a few seconds. Lines of the form `name value` count as a value read off, as with `sniff`.

## What is in the report

- **Overview:** duration, number of messages and IDs, estimated bus load.
- **Notes** with their time.
- **Diagnostics:** every request of a tester (app, workshop device) with its answer, whether evsoc knows it already, and how the answer changes over time. Applies to CAN (ISO-TP, 11/29 bit, BMW addressing), HSFZ and DoIP.
- **Every CAN ID:** interval between messages, length and what each byte does: constant, counter, checksum (sum/XOR is recognised), state with few values, signal with a value range. Neighbouring bytes that overflow into each other are recognised as a 16/24/32 bit number, including byte order.
- **History:** a dozen lines per message spread over the whole recording.
- **Changes:** if a message changes only rarely, every change is listed with its time (`+12.00 s  B 00→01`). That then fits the notes.
- **Ethernet additionally:** participants (IP, MAC, VLAN), connections with recognised type, DoIP vehicle announcement and routing activation, offered SOME/IP services and subscriptions from service discovery, SOME/IP messages per service and method with the same byte evaluation as with CAN, plus unknown UDP and layer 2 traffic (gPTP, AVTP …).

The serial part of the VIN and the answers to VIN requests are hidden by the report. Other answers can still contain personal data, so take a short look before passing it on. The raw data (`*.log`, `*.pcap`) stays with you and is in `.gitignore`.

### Follow-up questions

If Claude asks for details on a message, `--id` delivers it in full length (more history lines, every change):

```bash
evsoc analyse -d capture.log --id 3D2 -o -                  # one CAN ID
evsoc analyse -d capture.log --id 3D2 --id 22D410 -o -      # several, also diagnostic requests
evsoc analyse -d drive.pcapng --id "1234.8001" -o -         # SOME/IP service.method
```

More options: `--points 30` (more history lines), `--max-ids 200` (more messages individually), `--bitrate 250000` (for the bus load), `-o FILE`.

## CAN on a Y cable

Setup, adapters and cables are the same as in [listening-in.md](listening-in.md#2-listening-to-can-with-a-y-cable), the same addresses (`-a`) apply. A CAN interface (CANable with slcan, gs_usb, SocketCAN) is clearly better than an ELM327 here: it sees 11 and 29 bit at the same time and loses nothing on a busy bus.

At the OBD socket of many newer cars only the diagnostic CAN behind the gateway is present. It is silent there as long as no tester asks. Then the report shows only the diagnostics. The full traffic is on a bus inside the vehicle.

It reads candump (`-L`, default, `-ta`), `.asc`, `.blf`, `.trc`, `.csv`, ATMA text and pcap recordings of a CAN interface (`tcpdump -i can0 -w can.pcap`).

## Automotive Ethernet

A Y cable does not work with Ethernet, because every line connects exactly two devices. To listen in you need one of the following solutions:

| Line | how you get at the data |
|---|---|
| 100BASE-T1 / 1000BASE-T1 between control units (one wire pair) | active TAP for Automotive Ethernet, or two media converters (T1 ↔ RJ45) with a switch with a mirror port in between. That is an intervention in the line, so only while parked and with matching connectors |
| ENET at the OBD socket (BMW/Mini, 100BASE-TX) | `evsoc analyse -a enet-proxy://auto` (evsoc between app and car, see [listening-in.md](listening-in.md#3-listening-to-enet-bmwmini)), or a switch with a mirror port between laptop and car |
| DoIP at the OBD socket (VW group, Mercedes, Volvo …) | switch with a mirror port between tester and car, or record on the tester laptop itself with Wireshark |

Recording on the Pi or Linux computer connected to the TAP or mirror port:

```bash
sudo evsoc analyse -a eth://eth0            # writes capture-….pcap and the report
```

On a Mac or with Wireshark: record there (`sudo tcpdump -i en5 -w drive.pcap`) and then `evsoc analyse -d drive.pcap`. Notes for a pcap file are in `FILE.pcap.notes`.

It recognises DoIP (port 13400), HSFZ (6801/6811), SOME/IP and SOME/IP-SD (also over TCP), VLAN tags, plus gPTP, AVTP, DLT, TLS and the usual network services by name. HSFZ diagnostics appear in BMW CAN notation (`6F1[07] → 607`), so evsoc recognises known requests.

## Limits

- I have tested `analyse` with rebuilt traffic, not yet on a real car. The classification of bytes is an estimate: a steadily rising value looks like a counter, and signals that do not sit on byte boundaries (e.g. 10 bit) appear as several single bytes. For that the report shows the bits that change for each byte.
- Encrypted traffic (TLS, MACsec, SecOC protected content) can be counted but not read.
- SOME/IP content is evaluated as bytes, not broken down by the interface description (FIBEX/ARXML). Segmented messages (SOME/IP-TP) are not reassembled.
- For messages over 64 bytes the first 64 are evaluated.
- `eth://` exists on Linux only. evsoc does not read K-line, LIN and FlexRay.
