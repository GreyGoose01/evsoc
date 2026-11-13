# Battery health (SoH)

The SoH (state of health) says how much capacity the high-voltage battery still has compared with new. evsoc reads it like apps such as EVScanner or Car Scanner through the OBD socket, read only.

```bash
evsoc read -a /dev/cu.OBDLinkMXPlus --all                    # BMW i3, Mini, Corsa-e, Ioniq 5 …
evsoc read -a /dev/cu.OBDLinkMXPlus --all --battery-kwh 77   # VW ID., Enyaq, Born, Q4, Explorer, Capri
```

Without `--all`, `read` shows only the state of charge.

## Where the SoH comes from

| Kind | Source | Examples |
|---|---|---|
| **direct** | The battery control unit reports a finished percentage. | BMW i3 / Mini Cooper SE (`226335`), Corsa-e and e-208, Hyundai/Kia, Taycan / e-tron GT, Renault Megane E-Tech (standard PID `01B2`) |
| **from the capacity in Ah** | The car reports the full-charge capacity, the nominal capacity is known. | Toyota bZ4X / Subaru Solterra 2022–2024 (`evsoc_toyota_etnga`, 201.1 Ah) |
| **from the energy content** | The car reports only the maximum energy content in kWh. SoH = energy content ÷ net nominal capacity. The nominal capacity is stored nowhere in the car, you give it. | VW group MEB (`evsoc_vw_meb`) |

## VW group MEB

Profile `evsoc_vw_meb`: VW ID.3, ID.4, ID.5, ID.7, ID.Buzz, Škoda Enyaq and Elroq, Cupra Born and Tavascan, Audi Q4 e-tron, Ford Explorer EV and Capri.

| Value | Request | Formula |
|---|---|---|
| maximum energy content (`capacity`) | gateway `710` → `77A`, `22 2AB2` | `INT16(A,B) × 0.05` kWh |
| current energy content (`energy_available`) | gateway, `22 2AB8` | `INT16(C,D) × 0.025` kWh |
| SoH (`soh`) | as `capacity` | energy content × 100 ÷ `--battery-kwh` |
| state of charge, voltage, temperature | BMS `17FC007B` → `17FE007B` | as OBDb/WiCAN |

The energy content is an estimate by the BMS. It does not depend on the state of charge, but fluctuates by one to two percent, for instance in the cold. For a reliable value read it several times, best after a drive or a charge. The raw value `19 94` (327.4 kWh) means "no value" and counts as implausible.

**Net nominal capacity** (maker figures, checked 10/2026):

| kWh net (gross) | Vehicles |
|---|---|
| 45 (48) | ID.3 Pure up to the 2024 update, Cupra Born 45 kWh (not in all countries) |
| 52 (55) | ID.3 Pure from 2024, ID.4 / ID.5 Pure, Enyaq 50 (iV 50), Elroq 50, Q4 35 e-tron, Explorer / Capri Standard Range |
| 58 (62) | ID.3 Pro / Pro Performance up to 2024, Enyaq 60 (iV 60) up to 2024, Cupra Born 58 kWh |
| 59 (63) | ID.3 Pro from 2024, Enyaq 60 from 2025, Elroq 60, Cupra Born with the 63 kWh battery (Cupra says 60 kWh) |
| 77 (82) | ID.3 Pro S, ID.4 / ID.5 Pro and GTX up to mid 2025, ID.7 Pro, ID.Buzz short up to 2024, Enyaq 80 / 80x / 85 / 85x, Elroq 85 / 85x, Q4 40 / 45 / 50, Cupra Born 77 kWh, Tavascan, Explorer / Capri Extended Range (rear drive) |
| 79 (84) | ID.3 GTX, ID.4 GTX from mid 2025, ID.Buzz short from 2025, Cupra Born VZ, Explorer / Capri all-wheel drive |
| 85 (91) | ID.Buzz long (USA) |
| 86 (91) | ID.7 Pro S and GTX, ID.Buzz long (Europe) |

If in doubt, look in the order, the data sheet or the maker's app. What is wanted is the **usable (net)** capacity, not the gross figure in brackets. A wrong figure usually shows: above 110 % evsoc marks the SoH as implausible.

Without a nominal capacity evsoc still shows the maximum energy content and names the usual values with the SoH. evsoc deliberately does not guess the battery size: a heavily aged 77 kWh battery would otherwise look like a healthy 58 kWh battery, which is exactly the case you want to recognise when buying a used car.

## BMW and Mini

| Vehicles | Profile | SoH | Additionally |
|---|---|---|---|
| i3 / i3s, Mini Cooper SE (F56), F-series PHEV | `evsoc_bmw_sme` | `22 6335` at SME `07`, byte 4 in % | cell capacity min / max / mean in Ah (`22 DFA0`) |
| iX3, i4, iX, i5, i7 (Gen5 eDrive) | `evsoc_bmw_gen5` | none yet | state of charge from `22 E5CE` |

On Gen5 OBDb classifies byte 4 of `22 E5C7` as SoH. OBDb's own captures show 31 to 52 % there on new cars, and values over 100 %. The import therefore leaves this assignment out. How to find the right identifier on a Gen5 car is in [test-bmw-i4.md](test-bmw-i4.md).

The new Mini (Cooper E/SE from 2024, Aceman, Countryman E) have different electronics and are not covered yet.

## Interfaces and continuous operation

- **Device (`evsoc run`):** Setup → Vehicle → "Net nominal capacity". The SoH then also goes to Home Assistant by MQTT (sensor "Battery health").
- **Workshop (`evsoc gui`):** field "Battery" next to "all values".
- **`evsoc monitor`:** `--battery-kwh 77`.

## What evsoc cannot do

- **Comparison with the fleet average**, as EVScanner offers it: that needs the values of many cars, which the app vendors collect on their servers. Over OBD there is no such thing.
- **A battery certificate:** values from the BMS are estimates of the control unit. Maker certificates (e.g. VW "Battery Health Check", TÜV, Aviloo) measure differently and can differ by a few percentage points.
