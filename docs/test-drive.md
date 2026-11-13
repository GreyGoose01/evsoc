# Test drive at the car (`evsoc probe`)

`evsoc read` stops at the first profile that gives a plausible state of charge. `evsoc probe` does not judge: it asks everything the profiles that fit the car know, keeps every raw answer and shows what each profile makes of it. What is right we decide afterwards from the values you read off in the car.

Everything is read only. evsoc blocks writing, clearing and coding commands before sending.

Without a terminal the same works in the interface under "Test drive" ([gui.md](gui.md)).

A look into the control units is part of the test drive: for each one that answered, evsoc reads identification (part number, serial number, software version) and fault memory. Over ENET it asks the known BMW addresses for that, with `--all-profiles` all 256. The fault memory is only read (UDS `19 02`, OBD `03`/`07`/`0A`); clearing (`14`, OBD `04`) stays blocked. The codes appear as number and hex, plain-text descriptions are maker specific and not included. Switch off with `--no-diagnosis`.

## Procedure

1. Ignition on (BMW: start button without brake), plug in the adapter.
2. Read off in the car and note: state of charge in percent, range, odometer, outside temperature. If the maker's app shows an SoH or a battery temperature, that too.
3. Start the test drive and give the values read off:

```bash
evsoc probe -a enet://auto --car i4 --note soc=54 --note km=23150 --log i4-traffic.txt
evsoc probe -a /dev/cu.OBDLinkMXPlus --note soc=71           # car is recognised through the VIN
```

4. Best repeat later at a **different charge level** (after a drive or a charge). Values that move with the charge are state of charge, energy or voltage. Values that stay the same are candidates for capacity and SoH.

Output (shortened):

```
Vehicle: VR3ATTENTKY000001, model year 2019   Adapter: ELM327 adapter, 13.9 V
53 requests, 14 answers, 41 s
Noted: soc=51

evsoc_stellantis_phev   8/8 values plausible   <- this is what 'evsoc read' would choose
    soc                            50 %   fits soc=51
    voltage                       340 V
    current                       -12 A
    soh                            96 %
    ...

obdb_peugeot_208   1/4 values plausible
    soc                    -            (No answer: NO DATA)
    soc_bms                     0.391 %   DIFFERS from soc=51
    soh                    -            (Answer too short: 24 bits needed, 16 present)
    ...

evsoc_stellantis_ecmp   3/11 values plausible   different control unit (22D860: 2 instead of 3 data bytes)
    ...

Report: evsoc-probe-VR3ATTENTKY000001-20261112-101500.json
```

## Options

| Option | Effect |
|---|---|
| `--car "i4"` | give the model instead of looking it up through the VIN |
| `--note name=value` | value read off for comparison, repeatable. `soc` and `soh` are compared with all fields of the family (`soc_bms`, `soc_display` …, tolerance 3 percentage points), other names only with the field of the same name (5 %) |
| `--all-profiles` | test all 270 profiles, not only the fitting ones. For cars evsoc does not know; takes a few minutes |
| `--raw COMMAND …` | afterwards additional read commands as with `evsoc raw`, also ranges: `--raw ATSH6F1 ATCEA07 22E500-22E5FF` |
| `--no-diagnosis` | do not read identification and fault memory of the control units |
| `--battery-kwh 77` | nominal capacity, if a profile calculates the SoH from the energy content |
| `--log file` | also write the entire adapter traffic |
| `-o file.json` | name of the report |
| `-d report.json` | no car: re-evaluate a report with the current profiles |

## What I need for the evaluation

1. **The report file** `evsoc-probe-….json`. It contains every request with its raw answer, the VIN, the adapter and your notes. Everything can be recalculated from it.
2. **The values read off**, best given as `--note` right away, otherwise written alongside. Without a comparison value one can only say whether a value is plausible, not whether it is right.
3. **Two runs at different charge levels**, if it is about new values (SoH, capacity).
4. In case of problems the `--log` file.

The VIN is in the report. If you do not want to pass it on, replace the last six characters in the file.

Because the report contains the raw answers, a corrected formula can be checked without the car: change the profile, `evsoc probe -d report.json` shows the new result.

## Is a pure CAN capture enough (e.g. CL2000)?

Mostly not. On nearly all cars from about 2016 there is a gateway behind the OBD socket. Without a request the bus is silent there, the battery values come only as an answer to a read command. A logger that only listens then records nothing useful.

A capture helps in three cases:

| Case | What the logger sees | Evaluation |
|---|---|---|
| The logger hangs **in parallel** on a Y cable while evsoc or an app (Car Scanner, BimmerLink …) asks | requests and answers | `evsoc sniff -d file.txt`, see [listening-in.md](listening-in.md) |
| Cars **without a gateway** at the socket (smart electric drive 451, Tesla through a diagnostic cable, Leaf on pins 12/13) | the vehicle's messages | `evsoc sniff -d file.txt` |
| The logger sends a list of requests itself | only answers that fit into one message (up to 7 bytes). For longer ones it would have to send the flow control of the ISO-TP protocol | limited |

`evsoc sniff -d` reads the text files of the CL1000/CL2000 (`Timestamp;Type;ID;Data`). The format is implemented from the maker's description and not yet checked with a real file; a sample file helps.

For BMW over ENET there is no CAN capture, everything runs over the network cable there. The test drive with `--log` is the counterpart.

## Wake test

Whether the parked car can be woken and falls asleep again is checked by `evsoc wake` (report `evsoc-waketest-DATE.json`). Background and use: [continuous-operation.md](continuous-operation.md).
