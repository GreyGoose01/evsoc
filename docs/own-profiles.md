# Decoding a new car

This is how I went about the Corsa-e, and how it works for any car evsoc does not know yet.

## 1. Is there something already?

```bash
evsoc models <model>
evsoc update                   # fetches the latest profiles from OBDb, ABRP, WiCAN
evsoc read -a … --car "<model>"
```

Often a sister model of another brand helps, which `--car` tries automatically through the platform. It is also worth a look at the model's OBDb repository (`github.com/OBDb/<Make>-<Model>`): under `tests/test_cases` there are often real captures, even when no signals are entered yet.

## 2. Get a capture

**Option A: an app that already knows the car.** Car Scanner (iOS/Android) can show state of charge and voltage for many cars and, under *Settings → Adapter → Export log*, saves the complete adapter traffic.

1. Open only the state-of-charge sensor and let it run for a few seconds.
2. Note the displayed value, ideally at two different charge levels.
3. Export the log.

**Option A2: listen in with a Y cable.** Plug in a second adapter with a Y cable and run `evsoc sniff` while the app shows the value. Type in the values, evsoc searches the formula and writes the profile (`--write-profile`). See [listening-in.md](listening-in.md).

**Option B: search yourself.** Probe identifiers with `evsoc raw` (read only):

```bash
evsoc raw -a /dev/cu.X ATSP6 ATSH7E4 ATCRA7EC 220101 220105
```

## 3. Find the answer and derive the formula

Look in the log for lines like this:

```
>22D410
6940562D4106D9D
```

| Part | Meaning |
|---|---|
| `694` | sender (control unit) → `ATCRA694`, the request went to `6B4` (line `ATSH6B4` before it) |
| `05` | ISO-TP length: 5 bytes follow |
| `62 D4 10` | positive answer to `22 D4 10` |
| `6D 9D` | data: `A = 0x6D`, `B = 0x9D` |

Then try which calculation gives the noted value:

| Calculation | Result | Display 54.79 % |
|---|---|---|
| `A` | 109 | no |
| `INT16(A,B)` | 28061 | no |
| `INT16(A,B)/512` | **54.81** | yes |

Check against a second value. In the Corsa log, `9F EB` gave 79.96 %, and the cell voltage matched.

Typical scalings: `/2`, `/10`, `/100`, `/512`, `*100/255`, `/2.5`, `-40` (temperatures), `Signed()` for currents.

## 4. Write the profile

File `evsoc/profiles/own/evsoc_<name>.json` (the name must start with `evsoc_`):

```json
{
  "name": "evsoc_my_car",
  "description": "Make Model, BMS 6B4 -> 694, derived from a Car Scanner log",
  "source": "own capture 2026-10",
  "verified": "Model year, SoC checked at 2 values",
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

Notes:

- Put everything the step needs in `at`. `ATCEA` (without a value) and `ATFCSM0` reset the settings of other profiles.
- `ATFCSH…`, `ATFCSD300000`, `ATFCSM1` are only needed if the control unit expects its own flow control address (it then appears like this in the log).
- More fields as needed: `soc_display`, `soc_bms`, `soh`, `voltage`, `current`, `batt_temp`, `cell_min_voltage`, `cell_max_voltage`, `capacity`.
- If the car reports no SoH but only the maximum energy content in kWh: field `soh` with the same formula and `"percent_of": "battery_kwh"`. evsoc then calculates with the nominal capacity you give (`--battery-kwh`). Under `"battery_kwh": [58, 77]` give the usual values, they appear in the hint when the value is missing. Example: `evsoc_vw_meb`.
- If look-alike control units answer the same request (a different car with the same address), add a `confirm` entry. It tells them apart by the length of the answer.

## 5. Testing

```bash
evsoc profiles -v | grep -A3 evsoc_my_car     # loads the profile (syntax errors show up here)
evsoc read -a /dev/cu.X -p evsoc_my_car --all
```

For a test without a car, enter the answer in `evsoc/mock.py` under `VEHICLES` and add a test case in `tests/test_end_to_end.py`.

## 6. Sharing (optional)

Working profiles please others too: as a pull request to [OBDb](https://github.com/OBDb), [ABRP ev-obd-pids](https://github.com/iternio/ev-obd-pids) or [WiCAN](https://github.com/meatpiHQ/wican-fw). After the next `evsoc update` they come back automatically.
