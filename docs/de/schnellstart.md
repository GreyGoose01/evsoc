# Schnellstart

> Die Optionen heißen inzwischen englisch (`--wired-only`, `--note`, `--battery-kwh`, `--duration`, `--value` …). Die deutschen Namen in dieser Dokumentation (`--nur-kabel`, `--notiz`, `--akku-kwh`, `--dauer`, `--wert` …) funktionieren weiter. Die englische Fassung steht in [../quickstart.md](../quickstart.md).

## Installation

```bash
git clone https://github.com/GreyGoose01/evsoc.git && cd evsoc
python3 -m venv .venv
.venv/bin/pip install -e ".[all]"     # all = Bluetooth LE (bleak) + rohes CAN (python-can)
```

Ohne Extras (`pip install -e .`) gehen nur USB-, Bluetooth-Classic- und WLAN-Adapter sowie ENET.

## Oberfläche oder Kommandozeile

Wer lieber klickt: `.venv/bin/evsoc gui` öffnet alles im Browser ([gui.md](gui.md)). Die folgenden Schritte beschreiben die Kommandozeile.

## 1. Ohne Auto ausprobieren

```bash
.venv/bin/evsoc read -a mock://corsa-e
.venv/bin/evsoc read -a mock://tesla-m3 --all
```

Testfahrzeuge: `corsa-e`, `bmw-i3`, `bmw-ix3`, `ioniq5`, `id4`, `megane`, `bz4x`, `e-c3`, `tesla-m3`, `hybrid`.

## 2. Adapter verbinden

1. Adapter in die OBD-Buchse stecken (meist links unter dem Lenkrad, manchmal hinter einer Klappe).
2. Zündung bzw. „Bereit“ einschalten. Viele E-Autos antworten nur dann, und das Batteriesteuergerät schläft sonst.
3. Adapter suchen:

```bash
.venv/bin/evsoc devices --ble --enet
```

| Adapter | Adresse für `-a` |
|---|---|
| Bluetooth Classic (OBDLink MX+, ELM327 BT) | erst in den macOS-Einstellungen koppeln, dann `/dev/cu.<Name>` |
| USB | `/dev/cu.usbserial-…`, ggf. `serial:///dev/cu.…?baud=115200` |
| WLAN | Mac ins WLAN des Adapters, dann `tcp://192.168.0.10:35000` |
| Bluetooth LE (OBDLink CX, Veepeak BLE, vLinker) | `ble://<Name>` (Terminal braucht Bluetooth-Freigabe) |
| BMW/Mini ENET | `enet://auto` |
| CAN-Interface (CANable, PCAN …) | `can://slcan//dev/cu.usbmodem1?bitrate=500000` |

Mehr dazu in [adapter.md](adapter.md).

## 3. Ladestand lesen

```bash
.venv/bin/evsoc read -a /dev/cu.OBDLinkMXPlus
```

Ablauf: evsoc liest die VIN, sucht die Profile für Marke und Konzern und probiert sie durch. Anfragen, die mehrere Profile teilen, gehen nur einmal ans Auto. Am Ende steht das erkannte Profil. Beim nächsten Mal geht es mit `-p <Profil>` sofort.

Schneller und sicherer wird es, wenn du das Modell vorgibst:

```bash
.venv/bin/evsoc read -a /dev/cu.X --car "e-208"
.venv/bin/evsoc read -a /dev/cu.X --car "Ioniq 5" --year 2022
```

## Optionen

| Option | Wirkung |
|---|---|
| `-p NAME` | festes Profil statt Auto-Erkennung (`evsoc profiles`, `evsoc models`) |
| `--car TEXT` | Modell vorgeben; probiert auch baugleiche Modelle anderer Marken |
| `--vin`, `--year` | VIN bzw. Modelljahr vorgeben (manche Befehle gelten nur für bestimmte Jahre) |
| `--all` | alle Werte des Profils (Spannung, Strom, SoH, Temperatur …) samt Fehlern |
| `--akku-kwh 77` | Nennkapazität netto; nötig für den SoH bei Autos, die nur den Energieinhalt melden (VW MEB), siehe [batteriegesundheit.md](batteriegesundheit.md) |
| `--watch 10` | alle 10 Sekunden neu lesen |
| `--json` | eine JSON-Zeile pro Messung, für Skripte, Home Assistant, Datenbanken |
| `--log datei.txt` | kompletten Adapterverkehr mitschreiben |

Weitere Befehle:

```bash
evsoc models corsa                 # Fahrzeug suchen, zeigt auch baugleiche Profile
evsoc models --markdown            # komplette Liste (erzeugt docs/fahrzeuge.md)
evsoc profiles -v --source obdb    # Profile mit Details
evsoc raw -a … -p evsoc_stellantis_ecmp 22D410 22D815    # einzelne Lesebefehle
evsoc raw -a … --treffer ATSH6F1 ATCEA07 22DD00-22DDFF   # Bereich abfragen, nur Antworten zeigen
evsoc update                       # Profile neu aus OBDb, ABRP, WiCAN importieren
evsoc monitor -a … --mqtt mqtt://…  # dauerhaft überwachen, siehe dauerbetrieb.md
evsoc plan "Nissan Leaf"           # welche OBD-Art (Bus, Pins) und welcher Adapter passt
evsoc scan -a box:/dev/cu.X        # aktive Busse suchen (evsoc-Box)
```

## Fehlersuche

| Meldung | Ursache und Abhilfe |
|---|---|
| `Adapter antwortet nicht` | falscher Port, Adapter nicht gekoppelt, WLAN nicht verbunden. Bei BT-Klonen hilft oft Aus- und wieder Einstecken. |
| `Adapter kennt 'ATCEA07' nicht` | Billig-Klon. Für BMW/Mini und manche Profile braucht es OBDLink, vLinker oder ENET. |
| `NO DATA` bei allen Profilen | Zündung aus, Auto schläft, oder das Gateway sperrt. Tür auf und zu, „Bereit“ einschalten, nochmal versuchen. |
| `NRC 0x31 requestOutOfRange` | Das Steuergerät kennt diese Datenkennung nicht, also falsches Profil oder falsches Modelljahr. |
| `NRC 0x22 conditionsNotCorrect` | Das Auto will dafür „Bereit“ oder einen anderen Zustand. |
| `Kein Profil hat einen plausiblen Ladestand geliefert` | Auto unbekannt. Mit `--log` mitschneiden und nach [eigene-profile.md](eigene-profile.md) vorgehen. |
| Werte „(unplausibel)“ | Formel passt nicht zu diesem Modell. Anderes Profil probieren (`ebenfalls plausibel: …`). |
