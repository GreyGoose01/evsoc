# Universal-Adapter selbst bauen

Die Anleitung beschreibt zwei Bauwege. Was die Box können soll und warum, steht in [universal-adapter.md](universal-adapter.md). Die Befehle, die ihre Firmware verstehen muss, stehen in [box-protokoll.md](box-protokoll.md).

| | **A: Raspberry Pi + CAN-Platine** | **B: evsoc-Box mit STM32** |
|---|---|---|
| funktioniert heute mit evsoc | ja (`can://socketcan/…`) | Firmware 0.1 vorhanden, im Simulator getestet, **auf Hardware noch ungetestet** |
| Busse | CAN und CAN-FD an 6/14, zweiter Kanal an 3/11 oder 12/13 | Stufe 1–2: zwei CAN-Kanäle; später K-Line, Ethernet |
| Pins umschalten | von Hand (Schalter) | per Software (Relais) |
| 12-V-Messung (Wach-Erkennung) | nein, evsoc erkennt „wach“ am Busverkehr | ja (`ATRV`) |
| Teile ohne Pi | ca. 60–80 € | ca. 70–100 € |

**Empfehlung:** Mit Bauweg A anfangen. Er läuft sofort, und das OBD-Kabel samt Verdrahtung lässt sich später für B weiterverwenden.

## Sicherheitsregeln

1. **Kein Abschlusswiderstand.** Der Fahrzeugbus ist schon an beiden Enden mit 120 Ω abgeschlossen. Den Abschluss auf jeder CAN-Platine und jedem Transceiver-Modul abschalten (Jumper oder Schalter).
2. **12 V nie an Logikpins.** Pin 16 führt Bordspannung mit Spitzen weit darüber. Er geht nur über eine Sicherung (1 A) an den Spannungsteiler bzw. einen kfz-tauglichen Wandler.
3. **Masse ist Pin 5** (Signalmasse). Pin 4 ist die Karosseriemasse, bei sauberem Aufbau nicht nötig.
4. **Kurz bleiben.** Vom Stecker zum Transceiver höchstens 30 cm. Eine lange Stichleitung stört den Fahrzeugbus.
5. **Erst mithören.** Den ersten Test am Auto im Listen-only-Modus machen. Dann sendet der Aufbau nichts, auch nicht im Fehlerfall.
6. **Nur lesen.** evsoc sendet nur Lesedienste. Andere Programme auf demselben Aufbau sind dadurch nicht geschützt.
7. **Unterschiedliche Masse vermeiden.** Läuft der Pi am Hausnetz und steckt nur der Adapter im Auto, gehört ein USB-Isolator dazwischen (siehe [raspberry-pi.md](raspberry-pi.md)).

## OBD-Buchse

Die Pins sind auf Buchse und Stecker klein eingeprägt.

| Pin | Belegung |
|---|---|
| 6 / 14 | CAN-High / CAN-Low (Diagnose-CAN, alle E-Autos) |
| 3 / 11 | herstellerspezifisch, z. B. Ford MS-CAN, Leaf AV-CAN, Ethernet-Empfang |
| 12 / 13 | herstellerspezifisch, z. B. Leaf EV-CAN (bis 2017), Ethernet-Senden |
| 7 / 15 | K-Line / L-Line (ältere Hybride) |
| 1 | GM Single-Wire-CAN, Ethernet-Option 2 |
| 8 | Aktivierung Ethernet (DoIP) |
| 4 / 5 | Karosseriemasse / Signalmasse |
| 16 | +12 V Dauerplus |

**OBD-Kabel:** einen OBD-Stecker mit offenem Kabelende kaufen, bei dem **alle 16 Pins** belegt sind. Viele billige Kabel haben nur 4 bis 6 Adern. Vor dem Anschließen jede Ader mit dem Multimeter durchklingeln und die Farben notieren.

## Bauweg A: Raspberry Pi mit CAN-Platine

### Teile

| Teil | Beispiel | ca. Preis |
|---|---|---|
| Raspberry Pi | Pi 4 oder 5 (vorhanden?) | – |
| CAN-Platine, 2 Kanäle | Waveshare **2-CH CAN FD HAT** (MCP2518FD, galvanisch getrennt) | 40–50 € |
| OBD-Kabel | Stecker mit offenem Ende, 16 Adern | 10–15 € |
| Umschalter für Kanal 2 | Kippschalter 2-polig, EIN-EIN (2× UM) | 3 € |
| Kabel, Schrumpfschlauch, kleines Gehäuse | – | 5–10 € |

Ein-Kanal-Platinen (MCP2515 oder MCP2518FD) reichen, wenn nur Pins 6/14 gebraucht werden. Der MCP2515 kann kein CAN-FD.

### Verdrahtung

```
 OBD 6  (CAN-H) ───────────── CAN0 H
 OBD 14 (CAN-L) ───────────── CAN0 L
 OBD 5  (Masse) ───────────── CAN0 GND und CAN1 GND

                       ┌─ Stellung 1 ── OBD 3  / OBD 11
 CAN1 H / CAN1 L ── Schalter
                       └─ Stellung 2 ── OBD 12 / OBD 13
```

- Abschlusswiderstände auf **beiden** Kanälen abschalten (Jumper auf der Platine).
- Pin 16 bleibt frei, der Pi bekommt seinen Strom getrennt (siehe [raspberry-pi.md](raspberry-pi.md#stromversorgung)).

### Einrichten

1. Die `dtoverlay`-Zeilen für beide Kanäle aus dem [Waveshare-Wiki](https://www.waveshare.com/wiki/2-CH_CAN_FD_HAT) übernehmen. Sie hängen von der Platinenversion und der Stellung der Lötbrücken ab.
2. Neu starten und prüfen: `ip link` zeigt `can0` und `can1`.
3. Beide Kanäle einschalten. Für den ersten Test am Auto nur mithören:

```bash
sudo ip link set can0 up type can bitrate 500000 listen-only on
sudo ip link set can1 up type can bitrate 500000 listen-only on
candump can0          # aus can-utils: läuft Verkehr, wenn das Auto wach ist?
```

4. Dauerhaft einrichten mit [deploy/80-can0.network](../../deploy/80-can0.network), für `can1` eine Kopie mit angepasstem Namen.

### Mit evsoc nutzen

```bash
evsoc read -a can://socketcan/can0                            # Diagnose an 6/14 (die meisten Autos)
evsoc read -a "can://socketcan/can0?fd=1"                     # Autos mit CAN-FD (Platine mit MCP2518FD)
evsoc read -a "can://socketcan/can1?pins=12,13" --car "Leaf"  # Leaf bis 2017: EV-CAN, Schalter auf Stellung 2
```

`?pins=` sagt evsoc, an welchen Pins der Kanal hängt. Dann wählt es die passenden Profile.

Für das Gerät (`evsoc run`) den Kanal fest eintragen, sonst nimmt die automatische Suche den ersten gefundenen. In `/var/lib/evsoc/config.json`:

```json
"adapter": "can://socketcan/can1?pins=12,13"
```

## Bauweg B: evsoc-Box mit STM32

Die Box wird schrittweise ausgebaut. Jede Stufe ist für sich nutzbar.

| Stufe | Inhalt | Ergebnis |
|---|---|---|
| 1 | Nucleo-Board, 1 CAN-Kanal an 6/14, 12-V-Messung | arbeitet mit evsoc wie ein OBDLink |
| 2 | 2. CAN-Kanal, Relais-Pin-Matrix für 3/11 und 12/13, Listen-only | Leaf-EV-CAN, Bus-Suche (`EVSSCAN`) |
| 3 | CAN-FD, K-Line, Single-Wire-CAN | alle klassischen Busse |
| 4 | Ethernet: BMW HSFZ, dann DoIP (ISO 13400) | BMW ohne ENET-Kabel |
| 5 | eigene Platine, Ruhestrom unter 1 mA, Gehäuse | bleibt dauerhaft im Auto |

### Teile für Stufe 1 und 2

| Teil | Beispiel | Anzahl | ca. Preis |
|---|---|---|---|
| Mikrocontroller-Board | ST **NUCLEO-H723ZG** (3× CAN-FD, Ethernet, USB) | 1 | 30 € |
| CAN-Transceiver-Modul | Adafruit **CAN Pal** (TJA1051T/3, CAN-FD bis 5 Mbit/s, 3,3-V-Logik, Abschluss per Schalter, Silent-Pin) | 2 | je 8–10 € |
| OBD-Kabel | Stecker mit offenem Ende, 16 Adern | 1 | 10–15 € |
| Signalrelais, 2× UM, 5 V | z. B. Omron G6K-2F-Y 5V oder Panasonic TQ2-5V | 2 | je 3–5 € |
| Relaistreiber | ULN2003A (enthält die Freilaufdioden) | 1 | 1 € |
| Spannungsteiler | Widerstände 47 kΩ und 10 kΩ, Kondensator 100 nF, Schottky-Doppeldiode BAT54S | je 1 | 1 € |
| Sicherung | Halter mit 1-A-Feinsicherung | 1 | 3 € |
| Lochrasterplatine, Stiftleisten, Litze | – | – | 10 € |

### Stufe 1: ein CAN-Kanal an 6/14

```
 NUCLEO-H723ZG                    CAN Pal 1                 OBD-Stecker
 PD1 (FDCAN1_TX) ───────────────► TX
 PD0 (FDCAN1_RX) ◄─────────────── RX
 GPIO „SILENT1“  ───────────────► SLNT     CANH ──────────► 6
 3V3             ───────────────► VIN      CANL ──────────► 14
 GND             ───────────────► GND ─────────────────────► 5
                                  Abschluss-Schalter: OFF

 12-V-Messung:
 OBD 16 ── Sicherung 1 A ── 47 kΩ ──┬── ADC-Eingang (z. B. A0)
                                    ├── 10 kΩ ── GND
                                    ├── 100 nF ── GND
                                    └── BAT54S (gegen GND und 3V3)
```

- **FDCAN1 an PD0/PD1** ist die übliche Belegung der Nucleo-H7-Boards. Die Lage am Zio-Stecker CN9 vor dem Löten im [Schaltplan MB1364](https://www.st.com/resource/en/schematic_pack/mb1364-h723zg-e01_schematic.pdf) nachsehen.
- **TX an TX, RX an RX:** Am Transceiver ist `TX` der Eingang für das Sendesignal des Controllers.
- **SLNT** auf High schaltet den Sender des TJA1051 hart ab. Die Firmware setzt den Pin im Listen-only-Modus und nach dem Einschalten, bis evsoc etwas anderes verlangt. So ist „nur mithören“ auch in der Hardware garantiert.
- **Spannungsteiler:** 47 kΩ / 10 kΩ teilt um den Faktor 5,7. 3,3 V am ADC entsprechen dann 18,8 V. Die Diode schützt den Eingang bei Spannungsspitzen, der Kondensator glättet.
- **Strom:** In Stufe 1 und 2 versorgt der Pi bzw. Rechner die Box über die USB-Buchse des Mikrocontrollers (USB-OTG, nicht die ST-LINK-Buchse). Pin 16 dient nur der Messung.

### Stufe 2: zweiter Kanal und Pin-Matrix

```
 FDCAN2 TX/RX ── CAN Pal 2 (TX, RX, SLNT an „SILENT2“, Abschluss OFF)
                        CANH ─┬─ K1 Kontakt 1 (Schließer) ── OBD 12
                              └─ K2 Kontakt 1 (Schließer) ── OBD 3
                        CANL ─┬─ K1 Kontakt 2 (Schließer) ── OBD 13
                              └─ K2 Kontakt 2 (Schließer) ── OBD 11

 GPIO „REL_12_13“ ── ULN2003A ── Spule K1 (5 V)
 GPIO „REL_3_11“  ── ULN2003A ── Spule K2 (5 V)
```

- **Ohne Strom sind alle Relais offen.** Kanal 2 hängt also an keinem Pin, bis die Firmware auf `EVSBUS CAN 12,13 …` ein Relais schaltet. Die Firmware schaltet nie beide gleichzeitig.
- **FDCAN2-Pins** in STM32CubeMX zuweisen und mit dem Schaltplan auf Konflikte prüfen. Ein Teil der Pins ist auf dem Nucleo schon mit Ethernet und dem Arduino-SPI belegt.
- **Relaisspulen** an 5 V vom Nucleo (aus USB). Zwei kleine Signalrelais ziehen zusammen unter 100 mA.

### Firmware

**Stand:** Firmware 0.1 in [firmware/](../../firmware/README.de.md) für Stufe 1 und 2. Der Kern läuft als Simulator auf dem PC und ist dort mit evsoc getestet (BMW-Adressierung, 29 Bit, Flusssteuerung, Lese-Filter, Mithören). Die STM32-Anbindung kompiliert gegen die ST-Treiber, ist aber noch nicht auf echter Hardware gelaufen. Einrichtung in STM32CubeIDE und Einbau: [firmware/README.md](../../firmware/README.de.md).

Die wichtigsten Einstellungen:

| Block | Einstellung |
|---|---|
| FDCAN1 | Kernel-Takt 80 MHz; Nominal: Prescaler 10, Seg1 13, Seg2 2, SJW 2 → **500 kbit/s**, Abtastpunkt 87,5 % |
| FDCAN1, CAN-FD-Datenphase | Prescaler 2, Seg1 15, Seg2 4, SJW 4 → 2 Mbit/s, Abtastpunkt 80 %, Transceiver-Delay-Compensation an |
| FDCAN, Mithören | Betriebsart „Bus Monitoring“, zusätzlich SLNT auf High |
| USB | USB_OTG_HS als Device mit internem Full-Speed-PHY, Middleware „CDC“ (virtueller COM-Port) |
| ADC1 | ein Kanal am Spannungsteiler, Mittelwert über einige Messungen |

Ohne Hardware ausprobieren: `make -C firmware`, dann `firmware/evsoc-box-sim bmw-i3` und `evsoc read -a box:<ausgegebener Port>`.

### Prüfen

1. **Ohne Auto:** `evsoc read -a box:/dev/ttyACM0 --log box.txt` muss `EVSI` erkennen. Fehlt die Kennung, lehnt evsoc die Box ab.
2. **Auf dem Labortisch:** CAN Pal 1 und 2 direkt verbinden (H an H, L an L), **nur hier** bei beiden den Abschluss einschalten. Dann sieht Kanal 2 im Mithörmodus, was Kanal 1 sendet.
3. **Am Auto:** zuerst `evsoc scan -a box:/dev/ttyACM0` (sendet nichts), dann `evsoc read -a box:/dev/ttyACM0`.

## Später: eigene Platine (Stufe 5)

Für den Dauerbetrieb im Auto reicht der Laboraufbau nicht. Nötig sind dann ein Step-down-Wandler mit sehr kleinem Ruhestrom, Verpolschutz, TVS-Diode gegen Lastabwurf, PhotoMOS statt mechanischer Relais und ein Schlafmodus, den Busaktivität beendet (z. B. mit dem TJA1463). Die Bauteilwahl dafür steht in [universal-adapter.md](universal-adapter.md#bauteile-für-die-eigene-platine).
