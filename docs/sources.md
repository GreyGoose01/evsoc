# Sources and licences

## Where the profiles come from

| Prefix | Source | Count | Licence | Format |
|---|---|---|---|---|
| `evsoc_` | own evaluation (`evsoc/profiles/own/`), among others from OVMS, OBDb captures, opendbc and PSA-RE | 17 | – | v2 directly |
| `obdb_` | [OBDb](https://github.com/OBDb), open signal database of the Pelican app, one repository per model or make | 165 | CC-BY-SA-4.0 | bit fields |
| `abrp_` | [iternio/ev-obd-pids](https://github.com/iternio/ev-obd-pids), A Better Routeplanner | 18 | Apache-2.0 | Torque formulas |
| `wican_` | [meatpiHQ/wican-fw](https://github.com/meatpiHQ/wican-fw), profiles of the WiCAN adapters | 70 | GPL-3.0 | WiCAN formulas |

Status: import of 2026-10-08. `evsoc update` fetches the current state (about 25 seconds, needs access to `api.github.com`).

The imported files are in `evsoc/profiles/generated/<source>/` and are replaced completely on every update. Your own changes belong in `evsoc/profiles/own/`.

### Own profiles

| Profile | Basis |
|---|---|
| `evsoc_stellantis_ecmp` | Car Scanner capture of an Opel Corsa-e ([wican-fw#279](https://github.com/meatpiHQ/wican-fw/issues/279)). Formulas derived myself: SoC = `INT16/512` (54.81 % calculated at 54.79 % displayed), voltage = `INT16/16` (matches 108 × cell voltage), cell voltages in mV. Agrees with OBDb. SoH `(INT24−65536)/16`, current `INT24/64−1200` and energy `INT16/64` after [OVMS e-Doblò](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/tree/master/vehicle/OVMS.V3/components/vehicle_fiatedoblo) (MIT). Applied to the Corsa capture this gives 93.8 % SoH and 0 A at standstill. OVMS (e-Doblò) and WiCAN (e-Ulysse) show that the vans on K9 and EMP2 base use the same control unit as well. |
| `evsoc_nissan_leaf_evcan` | OVMS `vehicle_nissanleaf` (MIT): message `0x55B` on the EV-CAN (pins 12/13 according to [leaf-obd](https://leaf-obd.readthedocs.io/en/latest/diagnostic-connector.html)), 10 bit SoC in 0.1 %. For Leafs from 2018 the sources contradict each other on whether 12/13 are wired; so the profile applies only up to 2017. |
| `evsoc_smart_eq` | OVMS `vehicle_smarteq` (MIT): BMS `79B`→`7BB`, KWP `2108`. Not yet checked on any car. |
| `evsoc_tesla_models` | OVMS `vehicle_teslamodels` (MIT): message `0x302`, passive. |
| `evsoc_geely_becm` | Volvo/Polestar/Geely group: Polestar 2, Volvo XC40 (CMA) and XC60/XC90/S60 (SPA) according to OBDb, Zeekr 001 and Geely EX5 according to WiCAN. All ask `224801` at `1DD01635`. Derived from that and unchecked: EX30, EX90, Polestar 3/4, Lotus, Lynk & Co, smart #3. |
| `evsoc_mercedes_mfa2` | OBDb Mercedes EQA (`226050` at `7E5`). Confirmed for the EQB by the OBDb captures from 2024 (`1B 83` = 70.43 %). |
| `evsoc_ford_hybrid_pt` | opendbc `ford_lincoln_base_pt.dbc`: message `0x24C`, passive. Experimental. |
| `evsoc_fiat_500e_2020` | OVMS `vehicle_fiat500` (MIT): message `0x0C10A040`, passive. Experimental, because it is not certain that it is present at the OBD socket. |
| `evsoc_bmw_sme` | ABRP profile Mini Cooper SE and the [OVMS mailing list](https://lists.openvehicles.com/archives/list/ovmsdev@lists.openvehicles.com/message/LSZLC2XDFKMWCVLXB3KUV6C5QU7D3X4R/) on `22DDBC` for the i3; supplemented by the displayed state of charge from the limits. Cell capacity `22DFA0` (min/max/mean, `INT16/100` Ah) after [OBDb BMW](https://github.com/OBDb/BMW), checked against the i3 captures there (84.85 / 86.35 / 85.46 Ah at SoH 84 %). |
| `evsoc_vw_meb` | State of charge, voltage and temperature at the BMS as in OBDb/WiCAN/evDash. Maximum energy content `22 2AB2` at gateway `710` (`INT16 × 0.05` kWh) and current energy content `22 2AB8` (`INT16(C,D) × 0.025` kWh) after [OBDb Volkswagen-ID.4](https://github.com/OBDb/Volkswagen-ID.4) and [Audi-Q4-e-tron](https://github.com/OBDb/Audi-Q4-e-tron), checked against the captures there (ID.4 2021 to 2026, e.g. `05 BC` = 73.4 kWh). SoH = energy content ÷ net nominal capacity, as usual in the VW forums. |
| `evsoc_generic_obd` | SAE J1979 (PIDs 5B, 9A, B2, D2) and the UDS scheme of J1979-2/-3 (`F4` + PID, e.g. `F4B2` for SoH according to Vector/Kvaser). PIDs 5B, 9A, B2 additionally over 29 bit addresses (`18DB33F1`): the Renault Megane E-Tech 2025 answers only this way (OBDb captures: `77` = 46.7 %, SoH `FC` = 98.8 %). |
| `evsoc_bmw_gen5` | OBDb BMW-iX3 and BMW-i5: state of charge `22E5CE` (`INT16/100`), checked against the captures (e.g. `21 EE` = 86.86 %). `22DDBC` answers with zeros on Gen5. i4, iX and i7 derived. |
| `evsoc_toyota_etnga` | [OVMS vehicle_toyota_etnga](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/tree/master/vehicle/OVMS.V3/components/vehicle_toyota_etnga) (MIT): displayed state of charge `221738` at `745`, BMS state of charge `221F5B` and full-charge capacity `221D3E` at `747`. SoH = mean capacity ÷ 201.1 Ah, according to OVMS secure only for the 96 cell battery 2022–2024. |
| `evsoc_stellantis_smartcar` | Citroën ë-C3: `222002` at `7E0` and `224801` at `7E7` from a user report in the ABRP forum (Car Scanner). Experimental, Grande Panda and Frontera derived. |
| `evsoc_tesla_model3y` | [joshwardell/model3dbc](https://github.com/joshwardell/model3dbc) (MIT), message `ID292BMS_SOC`. |

## Known discrepancies

- **Hyundai Ioniq 5 (ABRP):** in the profile `abrp_ioniq5` state of charge and voltage sit one byte later than in OBDb and WiCAN (`f`/`ag` instead of `e`/`af`). OBDb and WiCAN agree, and the formulas of the Kona/Niro generation in ABRP fit them as well. evsoc therefore prefers OBDb. The test `test_sources_agree_on_same_car` checks the agreement.
- **VW MEB:** different scalings for the displayed state of charge (`DID 028C`) depending on the source: ABRP `1.12*A/2.5-7.16`, WiCAN `A*0.4425-6.1947`, OBDb `A*20.4/46-6.4`. The differences are under 1 percentage point. In addition `223DEF` (OBDb) delivers the BMS value directly in 0.01 %.
- **VW MEB, energy content (WiCAN):** WiCAN calculates `22 2AB2` as `[B4:B5]*50` with the unit kWh. That gives Wh (73 400 instead of 73.4). evsoc uses `evsoc_vw_meb` with `× 0.05` kWh like OBDb.
- **BMW Gen5 (OBDb):** OBDb classifies byte 4 of `22 E5C7` (iX3, i5, X5 50e) as SoH. OBDb's own captures show 31 to 52 % there on new cars and values over 100 %. The import leaves this assignment out (`_is_bmw_e5c7_soh`).
- **BMW `22DDBC` (OBDb):** on Gen5 (iX3, i5) `22DDBC` answers with zeros, which would pass as 0 % state of charge. The import treats an exact 0 there as "no value".
- **WiCAN, 29 bit addresses:** some WiCAN profiles (Renault AmpR, GMC Sierra EV) set a 29 bit header under `ATSP6`. The WiCAN firmware then switches by itself, an ELM327 does not. The import adds `ATSP7` and `ATCP`.
- **Subaru/Scion:** OBDb marks "Remaining battery capacity" (`221324` at `7A2`) as state of charge. The signal also exists on the BRZ and FR-S, which have no high-voltage battery at all, so it is the 12 V battery sensor. The import leaves it out.
- **12 V battery:** the OBDb import filters out states of charge of the 12 V battery (names with 12V, AUX, LV …). So only high-voltage batteries end up in the profile.

## Licence notice

- The code and the own profiles are under the MIT licence ([LICENSE](../LICENSE)).
- The imported data in `evsoc/profiles/generated/` is under the licences of its sources. CC-BY-SA (OBDb) demands attribution and the same licence for derived datasets, GPL-3.0 (WiCAN) the same for derived works. Details: [THIRD_PARTY.md](../THIRD_PARTY.md).
- Anyone who wants to pass evsoc on without these obligations does not ship `evsoc/profiles/generated/` and lets users run `evsoc update`. The `SOURCE.md` in each source folder names the origin.

## Further sources

| Source | Result |
|---|---|
| OVMS (MIT, over 40 vehicle modules in C++) | the data is in the code. Taken over: Stellantis vans, smart EQ, Tesla Model S, Fiat 500e, Leaf EV-CAN, Toyota/Subaru e-TNGA. Checked again 11/2026: the only new usable one is the smart electric drive 451 (2012–2016, `vehicle_smarted`): passive `0x518` byte 8 `/2` (display) and `0x2D5` (10 bit `/10`, BMS) on pins 6/14, taken over as `evsoc_smart_ed451` (experimental). The read commands to the BMS `7E7` (capacity, cell voltages) are not taken over yet. The Mercedes B 250 e gives no state of charge in OVMS. |
| evDash (MIT), EVNotify | all vehicles already covered through OBDb, WiCAN or ABRP; evDash confirms the MEB formulas |
| comma.ai opendbc (MIT) | hardly any state-of-charge signals: Tesla Model 3/Y (taken over), Ford hybrids from 2021 (`evsoc_ford_hybrid_pt`, experimental); GM Volt/Bolt only over single-wire CAN. Checked again 11/2026: no new state-of-charge signals that are present at the OBD socket (VW MEB `BMS_04` and Hyundai `BAT11` are behind the gateway); taken over only the VW maker codes `1V2`, `3VV`, `XW8` |
| [PSA-RE](https://github.com/prototux/PSA-RE) (Apache-2.0), networks and diagnostic data of the PSA vehicles | Contains the battery control unit of the e-CMP cars (`BMU_CTE1`, `6B4`→`694`) with 81 identifiers and confirms all formulas of `evsoc_stellantis_ecmp` (SoC `/512`, voltage `/16`, current `/64−1200`, energy `/64`, cell voltage in mV, SoH from bytes 2–3 `/16`). `22D410` is called "state-of-charge sensor calibration" there, `22D810` "state of charge". Taken over (experimental): battery temperature (`22D817` max, `22D877` mean, `22D87D` min, each `A−40` °C). Not taken over yet: power limits (`22D871`–`22D874`), insulation resistance, cell SoH (`22D4B5`). Also the battery control unit of the plug-in hybrids (`TBMU_PHEV`: 3008 II, 508 II, C5 Aircross, DS 7, Grandland X) at the same address with a different scaling (`22D810` = `INT16/4` %, `22D860` SoH `INT16/4` %): taken over as `evsoc_stellantis_phev` (experimental). Automatic detection tells the two apart by the length of the answer to `22D860` (3 bytes on the EV, 2 on the hybrid). NEA2020 (e-3008/e-5008) is not documented there yet. |
| [OpenVehicleDiag](https://github.com/rnd-ash/OpenVehicleDiag) (GPL-3.0) | Diagnostic program in Rust (KWP2000/UDS over J2534 and SocketCAN) with a converter for Mercedes CBF files. The repository contains no vehicle data; nothing to take over for evsoc. |
| [bmwGxx / G-Diag](https://github.com/unblonded/bmwGxx) (MIT) | Diagnostic program for BMW F/G over ENET and J2534, without battery data. Taken over: it answers the gateway's alive check (HSFZ `0x0012` with `0x0013`), which `evsoc` now also does over ENET. Its control unit list has the SME at `0x0E`; the OBDb captures and `evsoc` use `0x07`. |
| [beemuu](https://github.com/ohgeeceee/beemuu) (GPL-3.0) | Diagnostic program for BMW with a focus on combustion engines (engine profiles N52 to S58). The high-voltage identifiers in `research/bmw_diag_dim04_uds_dids.md` come from OBDb (X5, 5 series) and are already in `evsoc`, including the faulty SoH from `22E5C7` there. No new SoH identifier for Gen5. |
| OBDb repositories without signals | many models have captures only (e.g. Megane E-Tech, Mercedes EQB). The confirmations above come from these. |
| Car Scanner, Torque Pro | closed databases; but their logs are suitable for deriving profiles ([own-profiles.md](own-profiles.md)) |

**Without open OBD data:** Mercedes EQE/EQS/EQC, Hyundai Inster (ABRP uses the Kona profile there, unchecked), Peugeot e-3008/e-5008 (STLA Medium), Rivian, Lucid. For these cars the maker cloud remains ([continuous-operation.md](continuous-operation.md#alternatives-without-obd)). In the USA the standardised ZEVonUDS should apply from model year 2026/27, which `evsoc_generic_obd` already asks.
