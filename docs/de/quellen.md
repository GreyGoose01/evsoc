# Quellen und Lizenzen

## Woher die Profile kommen

| Präfix | Quelle | Anzahl | Lizenz | Format |
|---|---|---|---|---|
| `evsoc_` | eigene Auswertung (`evsoc/profiles/own/`), u. a. aus OVMS, OBDb-Mitschnitten, opendbc und PSA-RE | 17 | – | v2 direkt |
| `obdb_` | [OBDb](https://github.com/OBDb), offene Signaldatenbank der App Pelican, ein Repository pro Modell bzw. Marke | 165 | CC-BY-SA-4.0 | Bitfelder |
| `abrp_` | [iternio/ev-obd-pids](https://github.com/iternio/ev-obd-pids), A Better Routeplanner | 18 | Apache-2.0 | Torque-Formeln |
| `wican_` | [meatpiHQ/wican-fw](https://github.com/meatpiHQ/wican-fw), Profile der WiCAN-Adapter | 70 | GPL-3.0 | WiCAN-Formeln |

Stand: Import vom 08.10.2026. `evsoc update` holt den aktuellen Stand (etwa 25 Sekunden, braucht Zugriff auf `api.github.com`).

Die importierten Dateien liegen in `evsoc/profiles/generated/<quelle>/` und werden bei jedem Update komplett ersetzt. Eigene Änderungen gehören nach `evsoc/profiles/own/`.

### Eigene Profile

| Profil | Grundlage |
|---|---|
| `evsoc_stellantis_ecmp` | Car-Scanner-Mitschnitt eines Opel Corsa-e ([wican-fw#279](https://github.com/meatpiHQ/wican-fw/issues/279)). Formeln selbst abgeleitet: SoC = `INT16/512` (54,81 % berechnet bei 54,79 % angezeigt), Spannung = `INT16/16` (passt zu 108 × Zellspannung), Zellspannungen in mV. Stimmt mit OBDb überein. SoH `(INT24−65536)/16`, Strom `INT24/64−1200` und Energie `INT16/64` nach [OVMS e-Doblò](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/tree/master/vehicle/OVMS.V3/components/vehicle_fiatedoblo) (MIT). Auf den Corsa-Mitschnitt angewandt ergibt das 93,8 % SoH und 0 A im Stand. OVMS (e-Doblò) und WiCAN (e-Ulysse) belegen, dass auch die Transporter auf K9- und EMP2-Basis dasselbe Steuergerät nutzen. |
| `evsoc_nissan_leaf_evcan` | OVMS `vehicle_nissanleaf` (MIT): Botschaft `0x55B` auf dem EV-CAN (Pins 12/13 laut [leaf-obd](https://leaf-obd.readthedocs.io/en/latest/diagnostic-connector.html)), 10-Bit-SoC in 0,1 %. Für Leafs ab 2018 widersprechen sich die Quellen, ob 12/13 belegt sind; deshalb gilt das Profil nur bis 2017. |
| `evsoc_smart_eq` | OVMS `vehicle_smarteq` (MIT): BMS `79B`→`7BB`, KWP `2108`. Noch an keinem Auto geprüft. |
| `evsoc_tesla_models` | OVMS `vehicle_teslamodels` (MIT): Botschaft `0x302`, passiv. |
| `evsoc_geely_becm` | Volvo/Polestar/Geely-Konzern: Polestar 2, Volvo XC40 (CMA) und XC60/XC90/S60 (SPA) laut OBDb, Zeekr 001 und Geely EX5 laut WiCAN. Alle fragen `224801` an `1DD01635` ab. Daraus abgeleitet und ungeprüft: EX30, EX90, Polestar 3/4, Lotus, Lynk & Co, smart #3. |
| `evsoc_mercedes_mfa2` | OBDb Mercedes EQA (`226050` an `7E5`). Für den EQB durch die OBDb-Mitschnitte 2024 bestätigt (`1B 83` = 70,43 %). |
| `evsoc_ford_hybrid_pt` | opendbc `ford_lincoln_base_pt.dbc`: Botschaft `0x24C`, passiv. Experimentell. |
| `evsoc_fiat_500e_2020` | OVMS `vehicle_fiat500` (MIT): Botschaft `0x0C10A040`, passiv. Experimentell, weil nicht sicher ist, ob sie an der OBD-Buchse anliegt. |
| `evsoc_bmw_sme` | ABRP-Profil Mini Cooper SE und [OVMS-Mailingliste](https://lists.openvehicles.com/archives/list/ovmsdev@lists.openvehicles.com/message/LSZLC2XDFKMWCVLXB3KUV6C5QU7D3X4R/) zu `22DDBC` beim i3; ergänzt um den angezeigten Ladestand aus den Grenzwerten. Zellkapazität `22DFA0` (min/max/Mittel, `INT16/100` Ah) nach [OBDb BMW](https://github.com/OBDb/BMW), geprüft gegen die i3-Mitschnitte dort (84,85 / 86,35 / 85,46 Ah bei SoH 84 %). |
| `evsoc_vw_meb` | Ladestand, Spannung und Temperatur am BMS wie OBDb/WiCAN/evDash. Maximaler Energieinhalt `22 2AB2` am Gateway `710` (`INT16 × 0,05` kWh) und aktueller Energieinhalt `22 2AB8` (`INT16(C,D) × 0,025` kWh) nach [OBDb Volkswagen-ID.4](https://github.com/OBDb/Volkswagen-ID.4) und [Audi-Q4-e-tron](https://github.com/OBDb/Audi-Q4-e-tron), geprüft gegen die Mitschnitte dort (ID.4 2021 bis 2026, z. B. `05 BC` = 73,4 kWh). SoH = Energieinhalt ÷ Netto-Nennkapazität, wie in den VW-Foren üblich. |
| `evsoc_generic_obd` | SAE J1979 (PIDs 5B, 9A, B2, D2) und das UDS-Schema von J1979-2/-3 (`F4` + PID, z. B. `F4B2` für SoH laut Vector/Kvaser). PIDs 5B, 9A, B2 zusätzlich über 29-Bit-Adressen (`18DB33F1`): Renault Megane E-Tech 2025 antwortet nur so (OBDb-Mitschnitte: `77` = 46,7 %, SoH `FC` = 98,8 %). |
| `evsoc_bmw_gen5` | OBDb BMW-iX3 und BMW-i5: Ladestand `22E5CE` (`INT16/100`), geprüft gegen die Mitschnitte (z. B. `21 EE` = 86,86 %). `22DDBC` antwortet bei Gen5 mit Nullen. i4, iX und i7 abgeleitet. |
| `evsoc_toyota_etnga` | [OVMS vehicle_toyota_etnga](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/tree/master/vehicle/OVMS.V3/components/vehicle_toyota_etnga) (MIT): Anzeige-Ladestand `221738` an `745`, BMS-Ladestand `221F5B` und Vollladekapazität `221D3E` an `747`. SoH = mittlere Kapazität ÷ 201,1 Ah, laut OVMS nur für den 96-Zellen-Akku 2022–2024 gesichert. |
| `evsoc_stellantis_smartcar` | Citroën ë-C3: `222002` an `7E0` und `224801` an `7E7` aus einem Nutzerbericht im ABRP-Forum (Car Scanner). Experimentell, Grande Panda und Frontera abgeleitet. |
| `evsoc_tesla_model3y` | [joshwardell/model3dbc](https://github.com/joshwardell/model3dbc) (MIT), Botschaft `ID292BMS_SOC`. |

## Bekannte Abweichungen

- **Hyundai Ioniq 5 (ABRP):** Beim Profil `abrp_ioniq5` liegen Ladestand und Spannung je ein Byte später als bei OBDb und WiCAN (`f`/`ag` statt `e`/`af`). OBDb und WiCAN stimmen überein, und die Formeln der Kona/Niro-Generation in ABRP passen ebenfalls dazu. evsoc bevorzugt deshalb OBDb. Der Test `test_sources_agree_on_same_car` prüft die Übereinstimmung.
- **VW MEB:** Verschiedene Skalierungen für den angezeigten Ladestand (`DID 028C`) je nach Quelle: ABRP `1.12*A/2.5-7.16`, WiCAN `A*0.4425-6.1947`, OBDb `A*20.4/46-6.4`. Die Unterschiede liegen unter 1 %-Punkt. Daneben liefert `223DEF` (OBDb) den BMS-Wert direkt in 0,01 %.
- **VW MEB, Energieinhalt (WiCAN):** WiCAN rechnet `22 2AB2` als `[B4:B5]*50` mit der Einheit kWh. Das ergibt Wh (73 400 statt 73,4). evsoc nutzt `evsoc_vw_meb` mit `× 0,05` kWh wie OBDb.
- **BMW Gen5 (OBDb):** OBDb ordnet Byte 4 von `22 E5C7` (iX3, i5, X5 50e) als SoH ein. Die eigenen OBDb-Mitschnitte zeigen dort 31 bis 52 % bei neuen Autos und Werte über 100 %. Der Import lässt diese Zuordnung weg (`_is_bmw_e5c7_soh`).
- **BMW `22DDBC` (OBDb):** Bei Gen5 (iX3, i5) antwortet `22DDBC` mit Nullen, die als Ladestand 0 % durchgingen. Der Import wertet eine exakte 0 dort als „kein Wert“.
- **WiCAN, 29-Bit-Adressen:** Einige WiCAN-Profile (Renault AmpR, GMC Sierra EV) setzen einen 29-Bit-Header unter `ATSP6`. Die WiCAN-Firmware schaltet dann selbst um, ein ELM327 nicht. Der Import ergänzt `ATSP7` und `ATCP`.
- **Subaru/Scion:** OBDb markiert „Remaining battery capacity“ (`221324` an `7A2`) als Ladestand. Das Signal gibt es auch beim BRZ und FR-S, die gar keine Hochvoltbatterie haben, also ist es der 12-V-Batteriesensor. Der Import lässt es weg.
- **12-V-Batterie:** Der OBDb-Import filtert Ladestände der 12-V-Batterie heraus (Namen mit 12V, AUX, LV …). Es landen also nur Hochvoltbatterien im Profil.

## Lizenzhinweis

- Der Code und die eigenen Profile stehen unter der MIT-Lizenz ([LICENSE](../../LICENSE)).
- Die importierten Daten in `evsoc/profiles/generated/` stehen unter den Lizenzen ihrer Quellen. CC-BY-SA (OBDb) verlangt Namensnennung und gleiche Lizenz für abgeleitete Datensätze, GPL-3.0 (WiCAN) dasselbe für abgeleitete Werke. Einzelheiten: [THIRD_PARTY.md](../../THIRD_PARTY.md).
- Wer evsoc ohne diese Auflagen weitergeben will, liefert `evsoc/profiles/generated/` nicht mit und lässt Nutzer `evsoc update` ausführen. Die `SOURCE.md` in jedem Quellordner nennt die Herkunft.

## Weitere Quellen

| Quelle | Ergebnis |
|---|---|
| OVMS (MIT, über 40 Fahrzeugmodule in C++) | Daten stecken im Code. Übernommen: Stellantis-Transporter, smart EQ, Tesla Model S, Fiat 500e, Leaf EV-CAN, Toyota/Subaru e-TNGA. Stand 11/2026 erneut geprüft: neu verwertbar ist nur der smart electric drive 451 (2012–2016, `vehicle_smarted`): passiv `0x518` Byte 8 `/2` (Anzeige) und `0x2D5` (10 Bit `/10`, BMS) auf Pins 6/14, übernommen als `evsoc_smart_ed451` (experimentell). Die Lesebefehle ans BMS `7E7` (Kapazität, Zellspannungen) sind noch nicht übernommen. Mercedes B 250 e liefert in OVMS keinen Ladestand. |
| evDash (MIT), EVNotify | alle Fahrzeuge schon über OBDb, WiCAN oder ABRP abgedeckt; evDash bestätigt die MEB-Formeln |
| comma.ai opendbc (MIT) | kaum Ladestand-Signale: Tesla Model 3/Y (übernommen), Ford-Hybride ab 2021 (`evsoc_ford_hybrid_pt`, experimentell); GM Volt/Bolt nur über Single-Wire-CAN. Stand 11/2026 erneut geprüft: keine neuen Ladestand-Signale, die an der OBD-Buchse anliegen (VW MEB `BMS_04` und Hyundai `BAT11` liegen hinter dem Gateway); übernommen nur die VW-Herstellerkennungen `1V2`, `3VV`, `XW8` |
| [PSA-RE](https://github.com/prototux/PSA-RE) (Apache-2.0), Netzwerke und Diagnosedaten der PSA-Fahrzeuge | Enthält das Batteriesteuergerät der e-CMP-Autos (`BMU_CTE1`, `6B4`→`694`) mit 81 Kennungen und bestätigt alle Formeln von `evsoc_stellantis_ecmp` (SoC `/512`, Spannung `/16`, Strom `/64−1200`, Energie `/64`, Zellspannung in mV, SoH aus Byte 2–3 `/16`). `22D410` heißt dort „Kalibrierung des Ladestand-Sensors“, `22D810` „Ladestand“. Übernommen (experimentell): Batterietemperatur (`22D817` max, `22D877` Mittel, `22D87D` min, je `A−40` °C). Noch nicht übernommen: Leistungsgrenzen (`22D871`–`22D874`), Isolationswiderstand, Zell-SoH (`22D4B5`). Außerdem das Batteriesteuergerät der Plug-in-Hybride (`TBMU_PHEV`: 3008 II, 508 II, C5 Aircross, DS 7, Grandland X) an derselben Adresse mit anderer Skalierung (`22D810` = `INT16/4` %, `22D860` SoH `INT16/4` %): übernommen als `evsoc_stellantis_phev` (experimentell). Die automatische Erkennung unterscheidet beide über die Länge der Antwort auf `22D860` (3 Bytes beim E-Auto, 2 beim Hybrid). NEA2020 (e-3008/e-5008) ist dort noch nicht dokumentiert. |
| [OpenVehicleDiag](https://github.com/rnd-ash/OpenVehicleDiag) (GPL-3.0) | Diagnoseprogramm in Rust (KWP2000/UDS über J2534 und SocketCAN) samt Umwandler für Mercedes-CBF-Dateien. Das Repository enthält keine Fahrzeugdaten; für evsoc nichts zu übernehmen. |
| [bmwGxx / G-Diag](https://github.com/unblonded/bmwGxx) (MIT) | Diagnoseprogramm für BMW F/G über ENET und J2534, ohne Batteriedaten. Übernommen: Es beantwortet die Lebenszeichen-Abfrage des Gateways (HSFZ `0x0012` mit `0x0013`), das macht `evsoc` über ENET jetzt auch. Seine Steuergeräteliste führt die SME unter `0x0E`; die OBDb-Mitschnitte und `evsoc` nutzen `0x07`. |
| [beemuu](https://github.com/ohgeeceee/beemuu) (GPL-3.0) | Diagnoseprogramm für BMW mit Schwerpunkt Verbrenner (Motorprofile N52 bis S58). Die Hochvolt-Kennungen in `research/bmw_diag_dim04_uds_dids.md` stammen aus OBDb (X5, 5er) und sind in `evsoc` schon enthalten, samt dem dort fehlerhaften SoH aus `22E5C7`. Keine neue SoH-Kennung für Gen5. |
| OBDb-Repositories ohne Signale | viele Modelle haben nur Mitschnitte (z. B. Megane E-Tech, Mercedes EQB). Daraus stammen die Bestätigungen oben. |
| Car Scanner, Torque Pro | geschlossene Datenbanken; ihre Logs eignen sich aber, um Profile abzuleiten ([eigene-profile.md](eigene-profile.md)) |

**Ohne offene OBD-Daten:** Mercedes EQE/EQS/EQC, Hyundai Inster (ABRP nutzt dort das Kona-Profil, ungeprüft), Peugeot e-3008/e-5008 (STLA Medium), Rivian, Lucid. Für diese Autos bleibt die Hersteller-Cloud ([dauerbetrieb.md](dauerbetrieb.md#alternativen-ohne-obd)). In den USA sollte ab Modelljahr 2026/27 das genormte ZEVonUDS greifen, das `evsoc_generic_obd` schon abfragt.
