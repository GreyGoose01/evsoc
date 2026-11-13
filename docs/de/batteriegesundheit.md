# Batteriegesundheit (SoH)

Der SoH (State of Health) sagt, wie viel Kapazität die Hochvoltbatterie im Vergleich zum Neuzustand noch hat. evsoc liest ihn wie Apps à la EVScanner oder Car Scanner über die OBD-Buchse aus, nur lesend.

```bash
evsoc read -a /dev/cu.OBDLinkMXPlus --all                    # BMW i3, Mini, Corsa-e, Ioniq 5 …
evsoc read -a /dev/cu.OBDLinkMXPlus --all --akku-kwh 77      # VW ID., Enyaq, Born, Q4, Explorer, Capri
```

Ohne `--all` zeigt `read` nur den Ladestand.

## Woher der SoH kommt

| Art | Woher | Beispiele |
|---|---|---|
| **direkt** | Das Batteriesteuergerät meldet einen fertigen Prozentwert. | BMW i3 / Mini Cooper SE (`226335`), Corsa-e und e-208, Hyundai/Kia, Taycan / e-tron GT, Renault Megane E-Tech (genormte PID `01B2`) |
| **aus der Kapazität in Ah** | Das Auto meldet die Vollladekapazität, die Nennkapazität ist bekannt. | Toyota bZ4X / Subaru Solterra 2022–2024 (`evsoc_toyota_etnga`, 201,1 Ah) |
| **aus dem Energieinhalt** | Das Auto meldet nur den maximalen Energieinhalt in kWh. SoH = Energieinhalt ÷ Nennkapazität netto. Die Nennkapazität steht nirgends im Auto, du gibst sie an. | VW-Konzern MEB (`evsoc_vw_meb`) |

## VW-Konzern MEB

Profil `evsoc_vw_meb`: VW ID.3, ID.4, ID.5, ID.7, ID.Buzz, Škoda Enyaq und Elroq, Cupra Born und Tavascan, Audi Q4 e-tron, Ford Explorer EV und Capri.

| Wert | Abfrage | Formel |
|---|---|---|
| maximaler Energieinhalt (`capacity`) | Gateway `710` → `77A`, `22 2AB2` | `INT16(A,B) × 0,05` kWh |
| aktueller Energieinhalt (`energy_available`) | Gateway, `22 2AB8` | `INT16(C,D) × 0,025` kWh |
| SoH (`soh`) | wie `capacity` | Energieinhalt × 100 ÷ `--akku-kwh` |
| Ladestand, Spannung, Temperatur | BMS `17FC007B` → `17FE007B` | wie OBDb/WiCAN |

Der Energieinhalt ist eine Schätzung des BMS. Er hängt nicht vom Ladestand ab, schwankt aber um ein bis zwei Prozent, etwa bei Kälte. Für einen belastbaren Wert mehrmals lesen, am besten nach einer Fahrt oder Ladung. Der Rohwert `19 94` (327,4 kWh) heißt „kein Wert“ und gilt als unplausibel.

**Nennkapazität netto** (Herstellerangaben, geprüft 10/2026):

| kWh netto (brutto) | Fahrzeuge |
|---|---|
| 45 (48) | ID.3 Pure bis Modellpflege 2024, Cupra Born 45 kWh (nicht in allen Ländern) |
| 52 (55) | ID.3 Pure ab 2024, ID.4 / ID.5 Pure, Enyaq 50 (iV 50), Elroq 50, Q4 35 e-tron, Explorer / Capri Standard Range |
| 58 (62) | ID.3 Pro / Pro Performance bis 2024, Enyaq 60 (iV 60) bis 2024, Cupra Born 58 kWh |
| 59 (63) | ID.3 Pro ab 2024, Enyaq 60 ab 2025, Elroq 60, Cupra Born mit 63-kWh-Akku (Cupra nennt 60 kWh) |
| 77 (82) | ID.3 Pro S, ID.4 / ID.5 Pro und GTX bis Mitte 2025, ID.7 Pro, ID.Buzz kurz bis 2024, Enyaq 80 / 80x / 85 / 85x, Elroq 85 / 85x, Q4 40 / 45 / 50, Cupra Born 77 kWh, Tavascan, Explorer / Capri Extended Range (Heckantrieb) |
| 79 (84) | ID.3 GTX, ID.4 GTX ab Mitte 2025, ID.Buzz kurz ab 2025, Cupra Born VZ, Explorer / Capri Allrad |
| 85 (91) | ID.Buzz lang (USA) |
| 86 (91) | ID.7 Pro S und GTX, ID.Buzz lang (Europa) |

Im Zweifel in der Bestellung, im Datenblatt oder in der Hersteller-App nachsehen. Gesucht ist die **nutzbare (Netto-)** Kapazität, nicht die Brutto-Angabe in Klammern. Eine falsche Angabe fällt meist auf: Über 110 % markiert evsoc den SoH als unplausibel.

Ohne Nennkapazität zeigt evsoc trotzdem den maximalen Energieinhalt und nennt beim SoH die üblichen Werte. evsoc rät die Batteriegröße bewusst nicht: Eine stark gealterte 77-kWh-Batterie sähe sonst aus wie eine gesunde 58-kWh-Batterie, also genau der Fall, den man beim Gebrauchtwagenkauf erkennen will.

## BMW und Mini

| Fahrzeuge | Profil | SoH | Zusätzlich |
|---|---|---|---|
| i3 / i3s, Mini Cooper SE (F56), PHEV der F-Serie | `evsoc_bmw_sme` | `22 6335` an SME `07`, Byte 4 in % | Zellkapazität min / max / Mittel in Ah (`22 DFA0`) |
| iX3, i4, iX, i5, i7 (Gen5 eDrive) | `evsoc_bmw_gen5` | noch keiner | Ladestand aus `22 E5CE` |

Bei Gen5 ordnet OBDb das Byte 4 von `22 E5C7` als SoH ein. Die eigenen OBDb-Mitschnitte zeigen dort aber 31 bis 52 % bei neuen Autos und Werte über 100 %. Der Import lässt diese Zuordnung deshalb weg. Wie man mit einem Gen5-Auto die richtige Kennung findet, steht in [test-bmw-i4.md](test-bmw-i4.md).

Die neuen Mini (Cooper E/SE ab 2024, Aceman, Countryman E) haben eine andere Elektronik und sind noch nicht abgedeckt.

## Oberflächen und Dauerbetrieb

- **Gerät (`evsoc run`):** Einrichtung → Fahrzeug → „Nennkapazität netto“. Der SoH geht dann auch per MQTT an Home Assistant (Sensor „Batteriegesundheit“).
- **Werkstatt (`evsoc gui`):** Feld „Akku“ neben „alle Werte“.
- **`evsoc monitor`:** `--akku-kwh 77`.

## Was evsoc nicht kann

- **Vergleich mit dem Flottendurchschnitt**, wie EVScanner ihn anbietet: Dafür braucht man die Werte vieler Autos, die die App-Anbieter auf ihren Servern sammeln. Über OBD gibt es das nicht.
- **Ein Batteriezertifikat:** Werte aus dem BMS sind Schätzungen des Steuergeräts. Hersteller-Zertifikate (z. B. VW „Battery Health Check“, TÜV, Aviloo) messen anders und können einige Prozentpunkte abweichen.
