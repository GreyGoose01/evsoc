# Kompletten Verkehr auswerten lassen (`evsoc analyse`)

`evsoc sniff` sucht gezielt nach den Anfragen einer anderen App. `evsoc analyse` nimmt dagegen **alles**, was auf dem Bus oder der Leitung liegt, und verdichtet es zu einem Bericht, den du Claude geben kannst. Ein roher Mitschnitt von ein paar Minuten hat Hunderttausende Zeilen und ist zum Einfügen zu groß. Der Bericht hat einige hundert Zeilen und enthält das, was man zum Entschlüsseln braucht.

evsoc sendet dabei nichts.

```bash
evsoc analyse -a "can://slcan//dev/ttyACM0?bitrate=500000"    # CAN am Y-Kabel aufzeichnen, Ende mit Strg+C
evsoc analyse -a eth://eth0 --dauer 60                        # Ethernet aufzeichnen (Linux, root)
evsoc analyse -d mitschnitt.log                               # vorhandenen Mitschnitt auswerten
evsoc analyse -d fahrt.pcapng                                 # Wireshark-/tcpdump-Aufzeichnung auswerten
evsoc analyse -a mock://tesla-m3 --dauer 5                    # ohne Auto ausprobieren
```

Am Ende steht `Bericht: mitschnitt-….analyse.md`. Diese Datei gibst du Claude (hochladen oder Inhalt einfügen) und schreibst dazu, was du wissen willst, z. B. „Welche Botschaft enthält den Ladestand?“ oder „Was ändert sich beim Öffnen der Tür?“.

## Während der Aufnahme mitschreiben

Tippe ins Terminal, was du gerade tust oder abliest, jeweils mit Enter:

```
Tür auf
Laden gestartet
soc 80.5
```

Jede Zeile landet mit Uhrzeit im Mitschnitt und im Bericht. Das ist der wichtigste Teil: Nur so lässt sich zuordnen, welches Bit zur Tür gehört und welche Zahl zum Ladestand. Am besten immer nur **eine** Sache ändern und ein paar Sekunden warten. Zeilen der Form `name wert` gelten wie bei `sniff` als abgelesener Wert.

## Was im Bericht steht

- **Übersicht:** Dauer, Anzahl der Botschaften und IDs, geschätzte Buslast.
- **Notizen** mit Zeitpunkt.
- **Diagnose:** jede Anfrage eines Testers (App, Werkstattgerät) mit Antwort, ob evsoc sie schon kennt, und wie sich die Antwort über die Zeit verändert. Gilt für CAN (ISO-TP, 11/29 Bit, BMW-Adressierung), HSFZ und DoIP.
- **Jede CAN-ID:** Abstand der Botschaften, Länge und was jedes Byte tut: konstant, Zähler, Prüfsumme (Summe/XOR wird erkannt), Zustand mit wenigen Werten, Signal mit Wertebereich. Benachbarte Bytes, die ineinander überlaufen, werden als 16/24/32-Bit-Zahl erkannt, samt Byte-Reihenfolge.
- **Verlauf:** je Botschaft ein Dutzend Zeilen über die ganze Aufnahme verteilt.
- **Änderungen:** Ändert sich eine Botschaft nur selten, steht jede Änderung mit Zeitpunkt da (`+12.00 s  B 00→01`). Das passt dann zu den Notizen.
- **Ethernet zusätzlich:** Teilnehmer (IP, MAC, VLAN), Verbindungen mit erkannter Art, DoIP-Fahrzeugmeldung und Routing-Aktivierung, angebotene SOME/IP-Dienste und Abos aus der Service Discovery, SOME/IP-Botschaften je Dienst und Methode mit derselben Byte-Auswertung wie bei CAN, dazu unbekanntes UDP und Layer-2-Verkehr (gPTP, AVTP …).

Die Seriennummer der Fahrgestellnummer und die Antworten auf VIN-Abfragen blendet der Bericht aus. Andere Antworten können trotzdem persönliche Daten enthalten, also vor dem Weitergeben kurz ansehen. Die Rohdaten (`*.log`, `*.pcap`) bleiben bei dir und stehen in `.gitignore`.

### Nachfragen

Fragt Claude nach Einzelheiten zu einer Botschaft, liefert `--id` sie in voller Länge (mehr Verlaufszeilen, jede Änderung):

```bash
evsoc analyse -d mitschnitt.log --id 3D2 -o -                  # eine CAN-ID
evsoc analyse -d mitschnitt.log --id 3D2 --id 22D410 -o -      # mehrere, auch Diagnose-Anfragen
evsoc analyse -d fahrt.pcapng --id "1234.8001" -o -            # SOME/IP-Dienst.Methode
```

Weitere Schalter: `--punkte 30` (mehr Verlaufszeilen), `--max-ids 200` (mehr Botschaften einzeln), `--bitrate 250000` (für die Buslast), `-o DATEI`.

## CAN am Y-Kabel

Aufbau, Adapter und Kabel sind dieselben wie in [mitlesen.md](mitlesen.md#2-can-mitlesen-mit-y-kabel), es gelten dieselben Adressen (`-a`). Ein CAN-Interface (CANable mit slcan, gs_usb, SocketCAN) ist hier klar besser als ein ELM327: Es sieht 11 und 29 Bit gleichzeitig und verliert bei vollem Bus nichts.

An der OBD-Buchse liegt bei vielen neueren Autos nur der Diagnose-CAN hinter dem Gateway. Dort ist es still, solange kein Tester fragt. Dann zeigt der Bericht nur die Diagnose. Den vollen Verkehr gibt es an einem Bus im Fahrzeug selbst.

Gelesen werden candump (`-L`, Standard, `-ta`), `.asc`, `.blf`, `.trc`, `.csv`, ATMA-Text und pcap-Aufzeichnungen eines CAN-Interfaces (`tcpdump -i can0 -w can.pcap`).

## Automotive Ethernet

Ein Y-Kabel geht bei Ethernet nicht, weil jede Leitung genau zwei Geräte verbindet. Zum Mitlesen braucht es eine der folgenden Lösungen:

| Leitung | so kommst du an die Daten |
|---|---|
| 100BASE-T1 / 1000BASE-T1 zwischen Steuergeräten (ein Adernpaar) | aktiver TAP für Automotive Ethernet, oder zwei Medienkonverter (T1 ↔ RJ45) mit einem Switch mit Spiegel-Port dazwischen. Das ist ein Eingriff in die Leitung, also nur im Stand und mit passenden Steckern |
| ENET an der OBD-Buchse (BMW/Mini, 100BASE-TX) | `evsoc analyse -a enet-proxy://auto` (evsoc zwischen App und Auto, siehe [mitlesen.md](mitlesen.md#3-enet-mitlesen-bmwmini)), oder Switch mit Spiegel-Port zwischen Laptop und Auto |
| DoIP an der OBD-Buchse (VW-Konzern, Mercedes, Volvo …) | Switch mit Spiegel-Port zwischen Tester und Auto, oder auf dem Tester-Laptop selbst mit Wireshark aufzeichnen |

Aufzeichnen am Pi oder Linux-Rechner, der am TAP oder Spiegel-Port hängt:

```bash
sudo evsoc analyse -a eth://eth0            # schreibt mitschnitt-….pcap und den Bericht
```

Am Mac oder mit Wireshark: dort aufzeichnen (`sudo tcpdump -i en5 -w fahrt.pcap`) und danach `evsoc analyse -d fahrt.pcap`. Notizen zu einer pcap-Datei stehen in `DATEI.pcap.notizen`.

Erkannt werden DoIP (Port 13400), HSFZ (6801/6811), SOME/IP und SOME/IP-SD (auch über TCP), VLAN-Tags, dazu gPTP, AVTP, DLT, TLS und die üblichen Netzdienste dem Namen nach. HSFZ-Diagnose erscheint in der BMW-CAN-Schreibweise (`6F1[07] → 607`), so dass evsoc bekannte Anfragen erkennt.

## Grenzen

- Ich habe `analyse` mit nachgebautem Verkehr getestet, noch nicht an einem echten Auto. Die Einstufung der Bytes ist eine Schätzung: Ein gleichmäßig steigender Wert sieht aus wie ein Zähler, und Signale, die nicht an Bytegrenzen liegen (z. B. 10 Bit), erscheinen als mehrere Einzelbytes. Dafür zeigt der Bericht je Byte die Bits, die sich ändern.
- Verschlüsselter Verkehr (TLS, MACsec, SecOC-geschützte Inhalte) lässt sich zählen, aber nicht lesen.
- SOME/IP-Inhalte werden als Bytes ausgewertet, nicht nach der Schnittstellenbeschreibung (FIBEX/ARXML) zerlegt. Segmentierte Botschaften (SOME/IP-TP) werden nicht zusammengesetzt.
- Bei Botschaften über 64 Bytes werden die ersten 64 ausgewertet.
- `eth://` gibt es nur unter Linux. K-Line, LIN und FlexRay liest evsoc nicht.
