# evsoc

**Deutsch** · [English](README.md)

[![CI](https://github.com/GreyGoose01/evsoc/actions/workflows/ci.yml/badge.svg)](https://github.com/GreyGoose01/evsoc/actions/workflows/ci.yml)

Liest den Ladestand (SoC) und weitere Batteriewerte von E-Autos und Plug-in-Hybriden über die OBD-Buchse aus, in Python und ohne App.

- **270 Profile, 72 Marken.** Eigene Profile (u. a. aus OVMS-Quellcode abgeleitet) plus automatisch importierte Sammlungen von OBDb, ABRP und WiCAN, gruppiert nach baugleichen Plattformen. Liste: [docs/vehicles.md](docs/vehicles.md)
- **Automatische Erkennung.** Das Tool liest die VIN, wählt passende Profile und schickt gleiche Anfragen nur einmal.
- **Jeder Adapter.** ELM327/OBDLink über USB, Bluetooth, BLE und WLAN, das BMW-ENET-Kabel, rohe CAN-Interfaces (auch CAN-FD) über python-can und der Universal-Adapter zum Selberbauen (evsoc-Box, nur USB, [Bauanleitung](docs/de/bauanleitung-box.md)).
- **Richtige OBD-Art pro Fahrzeug.** evsoc weiß zu jedem Profil Bus-Art, Pins, Bitrate und Modus, prüft, ob dein Adapter das kann, und stellt einen Universal-Adapter selbst um (`evsoc plan "Nissan Leaf"`).
- **Als Gerät im Auto.** `evsoc run` findet Adapter und Fahrzeug selbst, überwacht dauerhaft, gibt die Werte weiter (MQTT/Home Assistant, Webhook, JSON) und zeigt eine Anzeige ohne Bedienelemente. Eingerichtet wird einmal im Browser (PIN-geschützt). Mehr in [docs/de/raspberry-pi.md](docs/de/raspberry-pi.md)
- **Oberfläche statt Terminal.** `evsoc gui` deckt alles ab: verbinden, Fahrzeug suchen, lesen, Probelauf mit Bericht, Steuergeräte und Fehlerspeicher, Rohbefehle, Mitlesen, Dauerbetrieb. Unter Linux trägt `evsoc desktop` das Programm ins Anwendungsmenü ein. Mehr in [docs/de/gui.md](docs/de/gui.md)
- **Andere Apps mitlesen.** `evsoc sniff` hört über ein Y-Kabel (CAN) oder als Zwischenstation (BMW-ENET, z. B. UCSI-3000) zu, was Car Scanner, BimmerLink & Co. fragen, zeigt, was evsoc davon schon kennt, findet Formeln zu abgelesenen Werten und schreibt daraus ein Profil. Auf Bussen mit Dauerbotschaften sucht es das Signal, das zu Referenzwerten passt; die Referenz kann ein zweiter Adapter automatisch liefern (`--referenz`). Mehr in [docs/de/mitlesen.md](docs/de/mitlesen.md)
- **Kompletten Verkehr auswerten lassen.** `evsoc analyse` zeichnet den ganzen CAN-Verkehr am Y-Kabel oder Automotive Ethernet (DoIP, HSFZ, SOME/IP, pcap) auf und verdichtet ihn zu einem Bericht, den du Claude zum Entschlüsseln geben kannst. Mehr in [docs/de/analyse.md](docs/de/analyse.md)
- **Probelauf.** `evsoc probe` testet am Auto alle passenden Profile komplett durch, vergleicht mit abgelesenen Werten, liest Kennung und Fehlerspeicher der Steuergeräte und schreibt einen Bericht mit allen Rohantworten, der sich später ohne Auto neu auswerten lässt. Mehr in [docs/de/probelauf.md](docs/de/probelauf.md)
- **Dauerbetrieb.** `evsoc monitor` bleibt am Auto, fragt nur ab, wenn es wach ist (Fahren, Laden), und schickt den Stand an Home Assistant, MQTT oder einen Webhook. Von außen lässt sich per MQTT-Befehl oder Knopf sofort lesen, ein schlafendes Auto wird dafür geweckt; `evsoc wake` testet vorher, ob das beim eigenen Auto geht. Mehr in [docs/de/dauerbetrieb.md](docs/de/dauerbetrieb.md)
- **Nur Kabel möglich.** `--nur-kabel` erlaubt nur USB-, CAN- und ENET-Adapter, kein WLAN/Bluetooth; die Oberfläche lässt sich an `eth0` binden. Mehr in [docs/de/raspberry-pi.md](docs/de/raspberry-pi.md)
- **Batteriegesundheit (SoH).** Direkt aus dem BMS (BMW i3/Mini, Corsa-e, Hyundai/Kia, Taycan …) oder beim VW-Konzern (ID., Enyaq, Born, Q4) aus dem Energieinhalt und der Nennkapazität (`--akku-kwh`). Mehr in [docs/de/batteriegesundheit.md](docs/de/batteriegesundheit.md)
- **Deutsch und Englisch.** Terminal und Oberflächen sprechen beide Sprachen, je nach Systemsprache oder mit `--lang de|en` bzw. dem Umschalter in der Oberfläche.
- **Nur lesend.** Schreib-, Lösch- und Codierbefehle werden blockiert, bevor sie den Adapter erreichen. Der Fehlerspeicher wird gelesen, nie gelöscht.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[all]"
.venv/bin/evsoc gui                                 # Oberfläche im Browser
.venv/bin/evsoc desktop                             # Linux: ins Anwendungsmenü eintragen
.venv/bin/evsoc read -a mock://corsa-e              # ausprobieren ohne Auto
.venv/bin/evsoc models ioniq                        # Fahrzeug suchen
.venv/bin/evsoc devices --ble                       # Adapter finden
.venv/bin/evsoc read -a /dev/cu.OBDLinkMXPlus       # echtes Auto
```

**Ohne git:** `evsoc-<version>-py3-none-any.whl` aus dem [neuesten Release](https://github.com/GreyGoose01/evsoc/releases/latest) herunterladen und mit `pipx install "./evsoc-<version>-py3-none-any.whl[all]"` installieren (oder `pip install` in einer virtuellen Umgebung). Mit `SHA256SUMS` im Release lässt sich der Download prüfen.

```
Lese Fahrgestellnummer (VIN) ...
Probiere 43 Profile ...
  Treffer: evsoc_stellantis_ecmp  (soc=79.959, soc_bms=79.959)

Profil: evsoc_stellantis_ecmp
  Fahrzeuge: Peugeot e-208 (2019-), Peugeot e-2008 (2019-), Opel Corsa-e / Corsa Electric (2019-) ...
  Ladestand (SoC)                  80.0 %
  Ladestand BMS                    80.0 %
```

> **Auf eigene Verantwortung.** evsoc ist ein privates Forschungsprojekt, ohne Verbindung zu einem Fahrzeughersteller und ohne Gewähr. Es sendet nur Lesebefehle, greift aber in die Fahrzeugdiagnose ein: Ein dauerhaft gesteckter Adapter kann die 12-V-Batterie entladen, und Eingriffe an der Fahrzeugelektrik können Garantie und Betriebserlaubnis berühren. Getestet ist fast alles nur mit simulierten Fahrzeugen. Nicht während der Fahrt bedienen.

## Dokumentation

| | |
|---|---|
| [Oberflächen](docs/de/gui.md) | Gerät (`evsoc run`) und Werkstatt (`evsoc gui`) im Vergleich, Bedienung, Sicherheit |
| [Schnellstart](docs/de/schnellstart.md) | Installation, erster Auslesevorgang, Optionen, Fehlersuche |
| [Fahrzeuge](docs/vehicles.md) | alle unterstützten Modelle, nach Marke und Plattform |
| [Batteriegesundheit](docs/de/batteriegesundheit.md) | SoH je Marke, VW MEB mit Nennkapazität, BMW, Grenzen |
| [BMW i4 über ENET testen](docs/de/test-bmw-i4.md) | Testanleitung mit WLAN-ENET-Adapter, Daten für den Gen5-SoH sammeln |
| [Adapter](docs/de/adapter.md) | welcher Adapter für welches Auto, Anschluss am Mac |
| [Dauerbetrieb](docs/de/dauerbetrieb.md) | Ladestand im geparkten Auto, Adapter dauerhaft im Auto, Home Assistant |
| [Gerät im Auto (Raspberry Pi)](docs/de/raspberry-pi.md) | nur Kabel: Aufbau, Strom, Installation als Dienst, einmalige Einrichtung, Betrieb |
| [Universal-Adapter](docs/de/universal-adapter.md) | OBD-Art pro Fahrzeug, Pins an der Buchse, Aufbau der evsoc-Box |
| [Bauanleitung Universal-Adapter](docs/de/bauanleitung-box.md) | selbst bauen: Raspberry Pi + CAN-Platine oder STM32-Box, Teile, Verdrahtung, Firmware-Stand |
| [Box-Protokoll](docs/de/box-protokoll.md) | Befehle, die die Firmware der Box können muss |
| [Firmware der Box](firmware/README.md) | Stand, Simulator ohne Hardware, Einbau in STM32CubeIDE |
| [Funktionsweise](docs/de/funktionsweise.md) | OBD, UDS, ISO-TP, Profile, Auto-Erkennung, Code-Aufbau |
| [Probelauf am Auto](docs/de/probelauf.md) | `evsoc probe`: alles durchtesten, Bericht schreiben, was zum Auswerten nötig ist, wann ein CAN-Mitschnitt reicht |
| [Eigene Profile](docs/de/eigene-profile.md) | ein neues Auto selbst entschlüsseln und hinzufügen |
| [Andere Apps mitlesen](docs/de/mitlesen.md) | welcher Weg für welchen Adapter, Y-Kabel, ENET-Mitleser, Pi-Ablauf, Formelsuche, Profil aus dem Mitschnitt |
| [Verkehr auswerten lassen](docs/de/analyse.md) | kompletten CAN- und Ethernet-Verkehr aufzeichnen, Bericht für Claude, Notizen, Automotive Ethernet anzapfen |
| [Quellen & Lizenzen](docs/de/quellen.md) | Herkunft der Daten, bekannte Abweichungen, `evsoc update` |

## Tests

```bash
.venv/bin/pip install -e ".[all,dev]" && .venv/bin/pytest && .venv/bin/ruff check .
```

Die Tests laufen ohne Auto. Sie nutzen einen simulierten ELM327, einen virtuellen CAN-Bus mit simuliertem Steuergerät, ein nachgebautes BMW-Gateway und die Firmware der evsoc-Box als Simulator auf dem PC, teils mit echten Mitschnitten (Corsa-e, BMW i3 und iX3, ID.4, Megane E-Tech).

## Mitmachen

Testdaten von echten Autos helfen am meisten: [CONTRIBUTING.md](CONTRIBUTING.md). Sicherheitslücken bitte vertraulich melden: [SECURITY.md](SECURITY.md).

## Lizenz

Der Code steht unter der [MIT-Lizenz](LICENSE). Die importierten Profile in `evsoc/profiles/generated/` behalten die Lizenz ihrer Quelle (OBDb: CC-BY-SA-4.0, WiCAN: GPL-3.0, ABRP: Apache-2.0), siehe [THIRD_PARTY.md](THIRD_PARTY.md).
