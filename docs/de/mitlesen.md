# Andere Apps mitlesen (`evsoc sniff`)

Car Scanner, EV Scanner, BimmerLink, Leaf Spy & Co. kennen für viele Autos Werte, die evsoc noch fehlen. `evsoc sniff` liest mit, während so eine App läuft, und lernt daraus:

- welche Anfragen die App an welches Steuergerät schickt (inkl. Flusssteuerung, 11/29 Bit, BMW-Adressierung),
- welche davon evsoc schon kennt (mit den Werten, die die Profile daraus berechnen) und welche **neu** sind,
- welche Formel einen in der App abgelesenen Wert ergibt,
- und schreibt daraus auf Wunsch ein fertiges evsoc-Profil.

Geht es nicht um eine App, sondern um den **kompletten Verkehr** auf dem Bus (auch Automotive Ethernet), ist [`evsoc analyse`](analyse.md) das passende Werkzeug.

evsoc sendet dabei selbst keine Diagnoseanfragen. Beim CAN-Mitlesen hört es nur zu. Beim ENET-Mitlesen reicht es die Nachrichten der App unverändert durch.

**Nur-Kabel gilt hier nicht.** Das Nur-Kabel-Prinzip ist für evsoc im Dauerbetrieb und für die evsoc-Box gedacht. Beim Mitlesen sind Handy, Bluetooth und WLAN ausdrücklich erlaubt, deshalb ignoriert `sniff` die Einstellung `--nur-kabel`.

---

## 1. Welcher Weg passt? (Entscheidungsplan)

Entscheidend ist, **wie die App mit dem Auto redet**, nicht wie das Handy mit dem Adapter redet (Bluetooth, BLE, WLAN ist egal).

| App-Adapter | wie er mit dem Auto redet | so liest evsoc mit | Abschnitt |
|---|---|---|---|
| OBDLink MX+, CX, LX, ELM327 (BT/BLE/WLAN/USB), vLinker, Veepeak, WiCAN | CAN an Pin 6/14 | **Y-Kabel + CAN-Interface** am Pi/Mac | [2](#2-can-mitlesen-mit-y-kabel) |
| ENET-Adapter mit WLAN/LAN (UCSI-3000 u. ä.) | Ethernet (Pins 3/11/12/13 + 8) | **evsoc dazwischen schalten** (`enet-proxy://`) | [3](#3-enet-mitlesen-bmwmini) |
| ENET-Kabel am Laptop (ISTA, E-Sys, BimmerCode Windows/Mac) | Ethernet | **evsoc dazwischen schalten** | [3](#3-enet-mitlesen-bmwmini) |
| eigener Adapter der App (Carly, BimmerLink-Adapter …) | meist CAN an 6/14 | Y-Kabel + CAN-Interface, sonst wie oben | [2](#2-can-mitlesen-mit-y-kabel) |
| CAN-FD-Autos (neuere GM, teils neue Modelle) | CAN-FD an 6/14 | Y-Kabel + **CAN-FD**-Interface (`?fd=1`) | [2](#2-can-mitlesen-mit-y-kabel) |
| Leaf Spy & Co. auf Sonderbussen (Leaf EV-CAN 12/13) | CAN an anderen Pins | Y-Kabel, das **alle 16 Pins** durchreicht, + Interface/Box an diesen Pins | [2](#2-can-mitlesen-mit-y-kabel) |
| ältere Hybride mit K-Line (7/15) | K-Line | **noch nicht unterstützt** | [6](#6-grenzen) |

**Kann der OBDLink MX+ ENET?** Nein. Der MX+ kann alle OBD-Protokolle (CAN, K-Line, J1850) und bei GM/Ford zusätzlich SW-CAN/MS-CAN, aber kein Ethernet/ENET. BMW-Apps (BimmerLink, BimmerCode) sprechen mit dem MX+ über den **CAN-Bus an Pin 6/14 (D-CAN)**. Den gibt es bei BMW F/G/I zusätzlich zu ENET. Das ist langsamer, lässt sich aber ganz normal per Y-Kabel mitlesen. Ob eine App beim jeweiligen Auto die Batteriewerte über CAN bekommt, zeigt der erste Versuch: Erscheinen bei laufender App keine Anfragen, holt sie die Werte nur über ENET.

Für einen BMW/Mini gibt es also zwei Wege, die sich ergänzen:

1. **App + MX+ über CAN**, mitgelesen per Y-Kabel. Funktioniert parallel mit einem CAN-Interface am Pi.
2. **App + UCSI-3000 über ENET**, mitgelesen per `enet-proxy://`. Funktioniert ohne Y-Kabel.

---

## 2. CAN mitlesen mit Y-Kabel

```
 OBD-Buchse ── Y-Kabel ──┬── Adapter der App (z. B. OBDLink MX+) ⟷ Bluetooth ⟷ Handy
                         └── CAN-Interface ⟷ USB ⟷ Raspberry Pi oder Mac (evsoc sniff)
```

### Hardware für den zweiten Zweig

| zweiter Adapter | Adresse (`-a`) | Hinweis |
|---|---|---|
| **CANable 2.0 mit slcan-Firmware** (USB, ca. 20–35 €) | `"can://slcan//dev/ttyACM0?bitrate=500000"` (Pi), `…//dev/cu.usbmodemXXXX…` (Mac) | **Empfehlung:** echtes Listen-only (kein ACK), kein Treiber nötig |
| candleLight / gs_usb (CANable mit candleLight-Firmware, FYSETC UCAN) | `can://gs_usb/0` | Pi/Mac: `pip install pyusb`, Mac zusätzlich `brew install libusb`. Kann über python-can kein Listen-only, bestätigt also Botschaften (ACK) wie jedes Steuergerät, sendet aber selbst nichts |
| CAN-Aufsteckplatine am Pi (Waveshare, PiCAN, MCP2515) | `can://socketcan/can0` | vorher `sudo ip link set can0 down && sudo ip link set can0 type can bitrate 500000 listen-only on && sudo ip link set can0 up` |
| CAN-FD-Interface | `"can://gs_usb/0?fd=1"`, `can://socketcan/can0` mit FD | nur nötig bei CAN-FD-Autos |
| zweiter ELM327/OBDLink per USB (z. B. OBDLink SX) | `/dev/ttyUSB0` bzw. `/dev/cu.usbserial-X` | Mithörmodus `ATMA` ohne ACK. Protokoll angeben: `--protokoll 6` (11 Bit, Standard) oder `7` (29 Bit). Klone verlieren bei viel Verkehr Botschaften |
| evsoc-Box | `box:/dev/ttyACM0` | Listen-only, `--pins 12,13` für andere Busse |

Ein CAN-Interface sieht 11- und 29-Bit-Botschaften gleichzeitig. Bei ELM/OBDLink/Box muss das Protokoll vorher stimmen, weil nichts gesendet wird, um es zu erkennen.

### Kabel

- **Y-Kabel:** Für CAN reichen Pin 4/5 (Masse), 6/14 (CAN) und 16 (12 V). Für Sonderbusse (Leaf 12/13, Ford 3/11) und für ENET auf demselben Y-Kabel muss es **alle 16 Pins** durchreichen. Das ist bei billigen Y-Kabeln oft nicht der Fall, also mit dem Multimeter prüfen.
- **Vom Y-Kabel zum CAN-Interface:** OBD-Stecker auf offene Adern oder DB9. Pin 6 = CAN-High, Pin 14 = CAN-Low, Pin 5 = Masse. Bei DB9 die Belegung des Interfaces prüfen, verbreitet ist CAN-L 2, Masse 3, CAN-H 7.
- **Abschlusswiderstand aus:** Der 120-Ω-Jumper am Interface muss offen sein, denn der Bus im Auto ist schon abgeschlossen.

### Ablauf

```bash
evsoc sniff -a "can://slcan//dev/ttyACM0?bitrate=500000"
```

1. Zündung an bzw. Auto „bereit“. Dann am Handy die App mit dem MX+ verbinden und **nur einen** Wert öffnen (z. B. Ladestand). So ist klar, welche Anfrage dazugehört.
2. evsoc zeigt jede neue Anfrage einmal an:
   ```
   21:03:10.295  6B4 → 694  22 D4 10   2 Bytes  bekannt: evsoc_stellantis_ecmp (soc 79.96 %)
   21:03:10.400  7E4 → 7EC  22 01 05  46 Bytes  NEU für evsoc
   ```
3. Den Wert, den die App gerade zeigt, ins Terminal tippen, z. B. `soc 80.5` + Enter. evsoc merkt ihn mit Uhrzeit. **Mindestens zweimal bei verschiedenen Werten**, etwa vor und nach einer Fahrt oder während des Ladens. Dann bleibt meist genau eine Formel übrig.
4. Nächsten Wert in der App öffnen, wieder eintippen, z. B. `voltage 398.4` oder `batt_temp 21`.
5. `Strg+C`. evsoc fasst zusammen: alle Anfragen, Häufigkeit, letzte Daten, veränderliche Bytes (`A`, `B` … wie in den Formeln), Warnungen und die Formelsuche.

`--alles` zeigt jede einzelne Antwort, geänderte Bytes stehen in `[ ]`. Das ist praktisch, um live zu sehen, welches Byte beim Laden mitläuft.

---

## 3. ENET mitlesen (BMW/Mini)

ENET ist Ethernet zwischen genau zwei Geräten. Ein Y-Kabel funktioniert hier nicht, zwei Geräte an denselben Leitungen stören die Verbindung. Stattdessen sitzt evsoc **in der Mitte**: Für die App sieht evsoc wie ein ENET-Adapter aus, und alles, was die App schickt, reicht evsoc unverändert an den UCSI-3000 bzw. das ENET-Kabel weiter. Die Antworten gehen genauso zurück.

```
 App (Handy/Laptop) ──WLAN/LAN──► evsoc (Pi/Mac)  TCP 6801 + Fahrzeugsuche UDP 6811 ──► UCSI-3000/ENET-Kabel ──► Auto
```

```bash
evsoc sniff -a enet-proxy://auto                          # Auto/Adapter selbst suchen
evsoc sniff -a enet-proxy://192.168.16.254                 # Adresse fest (z. B. UCSI-Gateway)
evsoc sniff -a "enet-proxy://auto?vin=WBY71AW0XXXXXXXXX"   # VIN für die Suchantwort vorgeben
evsoc sniff -a "enet-proxy://auto?suche=0"                 # Fahrzeugsuche nicht beantworten (App mit fester IP)
evsoc sniff -a "enet-proxy://auto?listen=192.168.1.50"     # nur auf dieser Adresse lauschen
```

Die Fahrzeugsuche der App beantwortet evsoc mit der Antwort des echten Autos. Liefert der Adapter keine, baut evsoc eine eigene mit der VIN des Autos. Ausgabe, Formelsuche, Profil-Export und Mitschnitt sind dieselben wie bei CAN. Die Anfragen erscheinen als BMW-Adressierung (`6F1[07] → 607`), und daraus erzeugte Profile laufen über ENET **und** über CAN-Adapter.

### Aufbau-Varianten am Pi

**Variante A: Pi als WLAN-Hotspot (empfohlen)**

```
 Handy ──WLAN „evsoc-sniff“──► Pi wlan0 (Hotspot, 10.42.0.1)
                               Pi USB-LAN (enx…) oder eth0 ──LAN──► UCSI-3000 ──► Auto
```

Das Handy ist nur mit dem Pi verbunden. Die Fahrzeugsuche der App sieht deshalb nur evsoc und nicht zusätzlich den UCSI oder das Auto, und evsoc reicht alles weiter. Den UCSI per LAN anschließen wie in [test-bmw-i4.md](test-bmw-i4.md). Sein eigenes WLAN wird nicht gebraucht.

Einmalig das WLAN des Pi einschalten. Im Gerätebetrieb ist es per `dtoverlay=disable-wifi` aus, siehe [raspberry-pi.md](raspberry-pi.md):

```bash
sudo sed -i 's/^dtoverlay=disable-wifi/#dtoverlay=disable-wifi/' /boot/firmware/config.txt && sudo reboot
```

Dann für jede Sitzung den Hotspot starten (Raspberry Pi OS mit NetworkManager):

```bash
sudo nmcli dev wifi hotspot ifname wlan0 ssid evsoc-sniff password evsoc-sniff-1
```

Handy mit `evsoc-sniff` verbinden, dann in der App „Verbinden“. Hotspot beenden mit `sudo nmcli con down Hotspot`. Willst du den Pi danach wieder als reines Kabelgerät betreiben, die Zeile in `config.txt` wieder aktivieren (das `#` entfernen) und neu starten.

**Variante B: Handy im Heim-WLAN**

```
 Handy ──Heim-WLAN──► Router ──LAN──► Pi eth0
                                     Pi USB-LAN (enx…) ──LAN──► UCSI-3000 ──► Auto
```

Ohne Hotspot, wenn das Heim-WLAN bis zum Auto reicht (Garage, Einfahrt). Die App sucht im Heimnetz und findet evsoc auf dem Pi.

**Variante C: alles am Laptop/Mac**

Laptop per LAN-Kabel am UCSI-3000 oder am ENET-Kabel, App am Handy im selben Netz wie der Laptop. Läuft die App auf demselben Laptop (E-Sys, ISTA, BimmerCode für Windows/Mac), in der App als Adresse `127.0.0.1` eintragen und `?suche=0` setzen.

**Variante D: ENET-Kabel statt UCSI**

Ein ENET-Kabel (OBD auf RJ45) am USB-LAN-Adapter des Pi funktioniert genauso wie der UCSI per LAN. Das Auto hat dann eine 169.254-Adresse, `enet-proxy://auto` findet es per Suche.

### Wenn die App evsoc nicht findet

Ich habe evsoc nur gegen nachgebaute Gateways getestet, noch nicht mit echten Apps. Apps finden ENET-Adapter unterschiedlich. Der Reihe nach probieren:

1. **Eigene Adresse eintragen:** Viele Apps erlauben unter „Adapter/ENET/WLAN“ eine feste IP. Dort die Adresse des Pi eintragen (Variante A: `10.42.0.1`, Variante B: seine Heimnetz-IP).
2. **Nachsehen, was die App versucht:** Am Pi `sudo tcpdump -ni any port 6801 or port 6811` laufen lassen und in der App „Verbinden“ drücken. Erscheinen keine Pakete, sucht die App an einer festen Adresse.
3. **App erwartet die feste UCSI-Adresse** (z. B. `192.168.16.254`): In Variante A dem Hotspot genau diese Adresse geben (`nmcli con modify Hotspot ipv4.addresses 192.168.16.254/24`, dann neu verbinden). Weil der UCSI selbst diese Adresse hat, geht das nur mit einem ENET-Kabel als Verbindung zum Auto (Variante D), sonst hätten zwei Geräte dieselbe Adresse.
4. **evsoc meldet „Port 6801 ist belegt“:** Dienst stoppen, siehe [Abschnitt 4](#4-auf-dem-raspberry-pi).

Sobald klar ist, was eine bestimmte App braucht, kommt es hier in die Liste.

---

## 4. Auf dem Raspberry Pi

```bash
ssh pi@evsoc.local
sudo systemctl stop evsoc                # evsoc run gibt Adapter, CAN und Port 6801 frei
cd ~ && evsoc sniff -a … -o ~/mitschnitt-$(date +%F).log
# … Werte aus der App direkt in die SSH-Sitzung tippen, z. B. „soc 80.5“, Ende mit Strg+C
sudo systemctl start evsoc               # Dauerbetrieb wieder an
```

- Den Mitschnitt holst du dir mit `scp pi@evsoc.local:~/mitschnitt-*.log .` auf den Mac und kannst ihn dort mit `evsoc sniff -d …` beliebig oft auswerten.
- Bricht die SSH-Verbindung ab, endet auch der Mitschnitt. Für lange Sitzungen in `tmux` starten (`sudo apt install tmux`, dann `tmux`, wieder verbinden mit `tmux attach`).
- 12-V-Batterie: Bei längeren Sitzungen das Auto auf „bereit“ stellen oder laden. Siehe [dauerbetrieb.md](dauerbetrieb.md).

---

## 5. Auswerten und Profil bauen

Der Mitschnitt landet als `mitschnitt-DATUM.log` (candump-Format, lesbar mit can-utils, SavvyCAN, python-can). Eingetippte Werte stehen mit Uhrzeit darin. Später erneut auswerten:

```bash
evsoc sniff -d mitschnitt.log
evsoc sniff -d mitschnitt.log --wert soc=54.8@21:03:10 --wert soc=79.9@21:40:00   # Werte nachträglich, mit Uhrzeit
evsoc sniff -d mitschnitt.log --json                                               # zum Weiterverarbeiten
```

`-d` liest auch fremde Mitschnitte: candump (`-L`, Standard, `-ta`), rohe `ATMA`-Ausgabe, `.asc`, `.blf`, `.trc`, `.csv`. Dazu die Textdateien der Logger CL1000/CL2000 (`Timestamp;Type;ID;Data`, noch mit keiner echten Datei geprüft). Wann ein reiner Mitschnitt reicht: [probelauf.md](probelauf.md#reicht-ein-reiner-can-mitschnitt-z-b-cl2000).

### Formelsuche

evsoc probiert für jede beantwortete Leseanfrage jedes Byte und Bytepaar als 8/16/24 Bit (mit und ohne Vorzeichen, auch Little-Endian), mit den üblichen Skalierungen (`/2`, `/10`, `/16`, `/512`, `*100/255` …) und Temperatur-Versatz (`-40`, `-50`). Treffer müssen alle abgelesenen Werte erklären. Die Toleranz richtet sich nach den eingetippten Nachkommastellen („79.96“ heißt ±0,01, „80“ heißt ±1), mindestens aber 0,25 %, weil Apps nicht immer exakt runden (Corsa-e: App 54,79 %, Formel 54,81 %). Eigene Toleranz: `--toleranz 0.5`.

```
  soc = 54.79, 79.96
    6B4 → 694  22 D4 10   INT16(A,B)/512   ergibt 54.81, 79.96
```

Gebräuchliche Namen: `soc`, `soc_display`, `soc_bms`, `soh`, `voltage`, `current`, `batt_temp`, `cell_min_voltage`, `cell_max_voltage`, `energy_available`. Daraus setzt evsoc Einheit und Plausibilitätsgrenzen.

### Profil erzeugen

```bash
evsoc sniff -d mitschnitt.log --wert soc=54.79@21:03:10 --wert soc=79.96@21:40:00 --wert voltage=426.2 \
            --profil evsoc_mein_auto.json --car "Opel Corsa-e"
```

Für jeden Wert nimmt evsoc die beste Formel und baut die AT-Befehle so, dass ein Adapter genau die Anfrage der App wiederholt (`ATSP`, `ATSH`/`ATCP`, `ATCRA`, `ATCEA`, bei abweichender Flusssteuerung `ATFCSH`/`ATFCSD`/`ATFCSM1`). Hat die App vorher die Diagnosesitzung gewechselt (z. B. `10 03`, erweiterte Sitzung), übernimmt evsoc das als `"pre": ["1003"]` in den Schritt. Das Profil wird vor dem Schreiben geprüft und braucht mindestens einen Ladestand-Wert (`soc…`). Danach prüfen, nach `evsoc/profiles/own/` kopieren und am Auto testen: [eigene-profile.md](eigene-profile.md).

---

## Dauerbotschaften: Werte ohne Anfrage finden

Hinter einem Gateway (Abgriff an einem internen Bus) und bei Autos ohne Gateway an der Buchse senden die Steuergeräte ihre Werte von selbst im Takt. Dort fragt niemand, also gibt es keine Anfrage-Antwort-Paare. evsoc sucht stattdessen in jeder Botschaft nach einem Bitfeld und einer Skalierung, die zu Referenzwerten mit Uhrzeit passen.

Die Referenzwerte kommen auf zwei Wegen:

```bash
# 1. automatisch: ein zweiter Adapter liest das Auto per Diagnose, der erste hört nur zu
evsoc sniff -a "can://slcan//dev/ttyACM0?bitrate=500000" --referenz enet://auto --car i4 --dauer 1800

# 2. von Hand: Werte beim Mitlesen eintippen ("soc 54.3" + Enter) oder nachträglich angeben
evsoc sniff -d mitschnitt.log --wert soc=54.3@12:01:10 --wert soc=57.0@12:20:40
```

Mit `--referenz` liest evsoc alle 10 Sekunden (`--referenz-abstand`) sämtliche Werte des Profils und merkt sie mit Uhrzeit im Mitschnitt. In der Oberfläche: Werkzeuge → Andere Apps mitlesen → Referenz-Adapter.

Ausgabe:

```
Dauerbotschaften: 6 IDs. Suche nach den notierten Werten:

  soc: 6 Referenzwerte, 6 verschiedene (54.3 … 60.1)
    3A5  Byte 3–4 (16 Bit, höherwertiges zuerst) × 0.01   Abweichung höchstens 0, 6 verschiedene Werte getroffen
    1F0  Byte 2 × 0.5   Abweichung höchstens 0.2, 6 verschiedene Werte getroffen
    Für ein Profil: Schritt {'id': 'b3A5', …, 'listen': '3A5'}  Feld-Dekoder {'type': 'dbc', 'start': 23, 'len': 16, …}
```

Was die Suche kann und was nicht:

- Geprüft werden einzelne Bytes, 16-Bit-Felder in beiden Byte-Reihenfolgen (auch mit Vorzeichen) und 10- bzw. 12-Bit-Felder an Byte-Grenzen, jeweils mit üblichen Skalierungen und Offsets. Passt keine übliche, zeigt evsoc eine angepasste und markiert sie als „krumme Skalierung“.
- **Die Aussagekraft hängt an der Zahl verschiedener Referenzwerte.** Bei einem einzigen Wert passen viele Bytes zufällig. Ab drei verschiedenen wird es belastbar. Also so lange mitschneiden, dass sich der Wert bewegt: eine Fahrt oder eine Ladung.
- Zähler und Konstanten werden aussortiert. Schnell wechselnde Werte wie Strom und Leistung passen zeitlich schlecht zu Referenzwerten im 10-Sekunden-Takt.
- Geprüft ist das bisher nur mit einem künstlichen Mitschnitt, an keinem Auto. Die Signalsuche arbeitet nur auf CAN und CAN-FD. Ethernet-Aufzeichnungen (pcap) wertet `evsoc analyse` aus ([analyse.md](analyse.md)), FlexRay liest evsoc nicht.
- Das Übernehmen ins Profil ist Handarbeit: Schritt und Dekoder aus der Ausgabe in eine Profildatei kopieren ([eigene-profile.md](eigene-profile.md)).

## 6. Grenzen

| Fall | Stand | Ausweg |
|---|---|---|
| K-Line (ältere Hybride, Pin 7/15) | evsoc liest K-Line nicht mit | App-Mitschnitt der App selbst (Car Scanner: Log exportieren) |
| App liest nur Broadcast-Botschaften (z. B. Tesla-Apps, kein Frage-Antwort) | evsoc zeigt diese IDs und ihre veränderlichen Bytes, sucht aber noch keine Formeln darin | DBC-Daten aus OBDb/opendbc, Formelsuche für Broadcasts wäre der nächste Ausbau |
| Werte in Bitfeldern (z. B. 10 Bit über Bytegrenzen) | Formelsuche arbeitet byteweise | veränderliche Bytes ansehen, Bitfeld von Hand als `bits`-Decoder |
| App nutzt Sicherheitszugang (`27`) vor dem Lesen | evsoc sieht das und warnt. Das Profil allein reicht dann nicht | solche Werte bleiben außen vor (evsoc sendet kein `27`) |
| Bus sehr voll, ELM-Klon als Mitleser | `BUFFER FULL`, Lücken | CAN-Interface verwenden |
| ENET: App findet evsoc nicht | siehe [Abschnitt 3](#wenn-die-app-evsoc-nicht-findet) | |

## 7. Sicherheit

- **CAN:** evsoc sendet keine Botschaften. ELM-Adapter laufen im „silent monitoring“ (`ATCSM1`), die evsoc-Box mit `EVSLISTEN 1`, CAN-Interfaces im Listen-only-Modus, sofern sie das können. Ein Interface ohne Listen-only bestätigt Botschaften (ACK) wie jedes Steuergerät, sendet aber selbst nichts. evsoc weist darauf hin.
- **ENET:** evsoc reicht die Nachrichten der App unverändert durch und erzeugt selbst keine Diagnoseanfragen. Einzige Ausnahme: Wenn der Adapter die Fahrzeugsuche nicht beantwortet, liest evsoc beim Start einmal die VIN (`22F190`, nur lesend). Mit `?vin=…` oder `?suche=0` entfällt auch das.
- **Was die App tut, verantwortet die App.** Schickt sie schreibende, löschende oder codierende Dienste (`2E`, `14`, `31`, `27` …), markiert evsoc das deutlich. Codier-Apps (BimmerCode, E-Sys) über `enet-proxy://` können das Auto verändern. Für die Werte-Suche reichen Diagnose-Apps im Lesemodus.
- `ATMA` bleibt für `read`/`raw` gesperrt. Nur `sniff` und das Mithören einzelner IDs nutzen es intern.
