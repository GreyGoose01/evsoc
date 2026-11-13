# Adapter

evsoc spricht drei Arten von Hardware an:

1. **ELM327-kompatible Adapter** (ELM327-Klone, OBDLink, Vgate, Veepeak, vLinker, WiCAN). Der Adapter übernimmt CAN und ISO-TP, evsoc schickt Textbefehle.
2. **BMW/Mini ENET-Kabel.** Ethernet direkt zum Fahrzeug-Gateway (HSFZ, TCP 6801).
3. **Rohe CAN-Interfaces** über python-can (CANable, candleLight, PCAN, Kvaser, Vector, SocketCAN, comma panda). evsoc übernimmt ISO-TP und Adressierung selbst, kann CAN-FD und hört passiv mit.

Alle drei führen dieselben Profile aus. Die ELM-Befehle in den Profilen (`ATSH`, `ATCRA`, `ATCEA` …) übersetzt evsoc für ENET und CAN automatisch.

## Welcher Adapter für welches Auto?

Die Software beantwortet das pro Fahrzeug selbst:

```bash
evsoc plan "Peugeot e-208"
evsoc plan "Nissan Leaf" -a /dev/cu.OBDLinkMXPlus     # passt mein Adapter?
```

Mit einem festen Profil (`read -p …`) prüft evsoc vor dem ersten Byte, ob der Adapter Bus, Pins und Modus des Profils kann. Die Auto-Erkennung lässt unpassende Profile weg. Die Übersicht:

| Fahrzeug | empfohlen | Hinweis |
|---|---|---|
| fast alle E-Autos und Hybride | OBDLink MX+ (Bluetooth), OBDLink CX (BLE), OBDLink SX/EX (USB) | zuverlässige AT-Befehle, schnell |
| BMW i3, Mini SE, BMW-PHEV | OBDLink oder vLinker (`ATCEA` nötig) **oder** ENET-Kabel | Billig-Klone scheitern hier meist |
| BMW/Mini F/G-Serie allgemein | ENET-Kabel (`enet://auto`) | nutzt Ethernet statt CAN, sehr schnell |
| Tesla Model 3/Y | CAN-Adapterkabel vom Diagnosestecker plus beliebiger CAN-Adapter | OBD-Buchse hat bei Tesla keine Daten, evsoc hört passiv mit |
| Autos mit CAN-FD (zunehmend bei neuen Modellen) | CAN-FD-Interface über `can://…?fd=1` | ELM327-Chips können kein CAN-FD |
| ältere Hybride mit K-Line | OBDLink MX+/SX (können K-Line) | |

## Anschluss am Mac

**Bluetooth Classic** (OBDLink MX+, die meisten ELM327-BT): In den Systemeinstellungen unter Bluetooth koppeln, PIN meist `1234` oder `0000`. Danach gibt es einen seriellen Port:

```bash
evsoc devices                  # zeigt /dev/cu.OBDLinkMXPlus o. ä.
evsoc read -a /dev/cu.OBDLinkMXPlus
```

**Bluetooth LE** (OBDLink CX, Veepeak BLE, vLinker MC+/FS, Adapter „für iPhone“): Nicht koppeln. evsoc verbindet sich direkt. Beim ersten Mal fragt macOS nach der Bluetooth-Freigabe für das Terminal.

```bash
evsoc devices --ble
evsoc read -a "ble://OBDLink CX"
```

**WLAN** (ELM327 WiFi, WiCAN): Mac mit dem WLAN des Adapters verbinden (Internet fällt dann meist weg).

```bash
evsoc read -a tcp://192.168.0.10:35000     # WiCAN Pro: 192.168.0.10:35000, WiCAN: 192.168.80.1:3333
```

**USB:** Treiber meist schon in macOS, Port `/dev/cu.usbserial-…` oder `/dev/cu.usbmodem…`. OBDLink SX/EX laufen mit 115200 Baud: `serial:///dev/cu.usbserial-X?baud=115200`.

**ENET (BMW/Mini):** Kabel an OBD und an einen USB-Ethernet-Adapter. Netzwerk auf „DHCP“ bzw. automatisch stellen, dann vergibt sich der Mac eine 169.254.x.x-Adresse. Zündung an.

```bash
evsoc devices --enet           # findet das Auto per Broadcast und zeigt die VIN
evsoc read -a enet://auto
```

**ENET mit WLAN** (z. B. UniCarScan UCSI-3000): Laptop mit dem WLAN des Adapters verbinden, dann ebenfalls `enet://auto`. Antwortet das Auto nicht auf die Suche, versucht evsoc die Gateway-Adresse des Adapters. Schritt für Schritt am Beispiel BMW i4: [test-bmw-i4.md](test-bmw-i4.md).

**evsoc-Box (Universal-Adapter):** `box:` vor den USB-Port setzen, z. B. `box:/dev/ttyACM0` (Pi) oder `box:/dev/cu.usbmodem1` (Mac). Die Box hat bewusst nur USB, kein WLAN und kein Bluetooth. evsoc schaltet dann pro Fahrzeug Pins und Bus-Art selbst um. Zum Ausprobieren gibt es `box:mock://leaf`. Details in [universal-adapter.md](universal-adapter.md), Bau in [bauanleitung-box.md](bauanleitung-box.md).

**Rohes CAN** (python-can):

```bash
evsoc read -a "can://slcan//dev/cu.usbmodem1?bitrate=500000"   # CANable mit slcan-Firmware
evsoc read -a "can://gs_usb/0"                                  # candleLight
evsoc read -a "can://pcan/PCAN_USBBUS1"                         # PEAK
evsoc read -a "can://socketcan/can0"                            # Linux / Raspberry Pi
evsoc read -a "can://gs_usb/0?fd=1"                             # CAN-FD
```

Dafür braucht es ein Kabel von der OBD-Buchse auf das Interface (Pin 6 = CAN-High, Pin 14 = CAN-Low, Pin 5 = Masse). Greift das Kabel andere Pins ab, etwa 12/13 beim Nissan Leaf, sag es evsoc mit `?pins=12,13`. Dann ordnet es die passenden Profile richtig zu.

## Billig-Klone

Viele günstige „ELM327 v1.5“- oder „v2.1“-Adapter haben einen nachgebauten Chip, der nur einen Teil der Befehle kann. evsoc meldet dann `Adapter kennt 'ATxx' nicht`. Für die meisten Hyundai-, Kia-, VW- und Stellantis-Profile reicht ein Klon oft. Für BMW (`ATCEA`), lange Antworten und schnelle Abfragen lohnt sich ein OBDLink.

## Sicherheit

- evsoc sendet nur Lese-Services: `01`, `09` (OBD), `22` (ReadDataByIdentifier), `21`/`1A` (ältere Lesedienste), `10 01`/`10 03` (Sitzungswechsel, nötig bei manchen Autos) und `3E` (TesterPresent), dazu das Lesen des Fehlerspeichers (`19 01`/`19 02`, OBD `03`/`07`/`0A`). Löschen (`14`, OBD `04`) ist gesperrt. Alles andere wird vor dem Senden abgelehnt.
- Passives Mithören (Tesla) sendet über ELM-Adapter nichts, weil sie standardmäßig „silent monitoring“ nutzen. Ein rohes CAN-Interface bestätigt empfangene Botschaften dagegen normalerweise (ACK). Für rein passives Mithören `can://…?listen_only=1` verwenden, sofern python-can das für das Interface unterstützt (z. B. PCAN, Kvaser). Bei SocketCAN stellt man es am Interface selbst ein (`ip link set can0 type can bitrate 500000 listen-only on`). evsoc meldet einen Fehler, wenn der Modus nicht geht, statt still weiterzumachen. Im Listen-only-Modus sind Anfragen abgeschaltet.
- Adapter nicht dauerhaft stecken lassen: Viele ziehen Strom aus der 12-V-Batterie und halten Steuergeräte wach.
