# Oberflächen

evsoc hat zwei Oberflächen:

| | `evsoc run` (Gerät) | `evsoc gui` (Werkstatt) |
|---|---|---|
| für | das fest eingebaute Gerät im Auto | Ausprobieren, Entwickeln, neue Fahrzeuge |
| Anzeige | nur Werte und Verbindung, keine Bedienung | alles: Adapterwahl, Profilwahl, Rohwerte |
| Einstellungen | einmalig unter `/einrichtung`, PIN-geschützt, gespeichert | nur für die laufende Sitzung |
| läuft | dauerhaft als Dienst | bei Bedarf |

Das Gerät mit `evsoc run` ist in [raspberry-pi.md](raspberry-pi.md) beschrieben. Der Rest dieser Seite behandelt die Werkstatt-Oberfläche.

## Werkstatt-Oberfläche

```bash
evsoc gui              # im Browser, http://127.0.0.1:8787
evsoc gui --fenster    # als eigenes Fenster (Chromium/Chrome, sonst Standardbrowser)
```

Die Oberfläche läuft lokal auf deinem Rechner, ohne Internet und ohne zusätzliche Pakete. Sie deckt alle Befehle ab, das Terminal ist nicht nötig.

### Start ohne Terminal (Linux)

```bash
evsoc desktop          # einmalig: trägt evsoc ins Anwendungsmenü ein
evsoc desktop --entfernen
```

Danach steht „evsoc“ im Anwendungsmenü (GNOME, KDE, Xfce …). Der Eintrag startet `evsoc gui --fenster`. Mit Chromium, Chrome, Brave, Edge oder Vivaldi öffnet sich ein eigenes Fenster ohne Adressleiste, sonst ein Tab im Standardbrowser. evsoc beendet sich selbst, wenn das Fenster drei Minuten geschlossen ist und nichts mehr läuft.

Für USB-Adapter muss dein Benutzer auf die serielle Schnittstelle zugreifen dürfen: `sudo usermod -aG dialout $USER`, danach ab- und anmelden.

### Aufbau

Links die Bereiche, oben rechts der Stand (Adapter, Profil, laufende Arbeit). Hell und Dunkel schaltet der Knopf unten links um.

| Bereich | Was er macht |
|---|---|
| **Verbindung** | gefundene USB-, CAN- und Bluetooth-Adapter, Beispiele, Testfahrzeuge und die simulierte evsoc-Box. Nach dem Verbinden steht da, was der Adapter kann (Bus-Arten, Pins, Mithören). „Busse suchen“ zeigt mit der evsoc-Box alle aktiven Busse an der Buchse. |
| **Fahrzeug** | Modell suchen. Ein Klick zeigt das Profil mit **OBD-Art** (Bus, Pins, Bitrate) und welche Adapter passen, auch ob **dein** verbundener Adapter passt. |
| **Ladestand** | „Lesen“ mit dem gewählten Profil, „Automatisch erkennen“ ohne Auswahl. Alle Werte, Verlauf, wiederholtes Lesen alle 10 Sekunden. Die Nennkapazität braucht nur der SoH bei VW MEB ([batteriegesundheit.md](batteriegesundheit.md)). |
| **Probelauf** | `evsoc probe` per Knopf: abgelesene Werte eintragen, starten. Das Ergebnis zeigt je Profil alle Werte mit „passt zu“ oder „weicht ab von“. Profile mit identischem Ergebnis sind zusammengefasst. Berichte landen in `~/evsoc-berichte` und lassen sich später ohne Auto öffnen und neu auswerten ([probelauf.md](probelauf.md)). |
| **Steuergeräte & Fehler** | Kennung und Fehlerspeicher der Steuergeräte aus dem letzten Probelauf. Nur lesend, Löschen ist gesperrt. |
| **Werkzeuge** | einzelne Lesebefehle und Bereiche (`evsoc raw`); andere Apps über ein Y-Kabel mitlesen oder einen Mitschnitt auswerten (`evsoc sniff`, [mitlesen.md](mitlesen.md)). |
| **Dauerbetrieb** | `evsoc monitor` mit Knopfdruck: Abstände, Wach-Schwelle und optionales Wecken, dazu „Jetzt lesen (weckt das Auto)“ und der Wecktest ([dauerbetrieb.md](dauerbetrieb.md)). |
| **Protokoll** | was gerade passiert, inklusive Fehlermeldungen |

Zum Ausprobieren ohne Auto: unter Verbindung „Testfahrzeug corsa-e“ wählen, verbinden, dann „Probelauf“ öffnen, bei Ladestand 80 eintragen und starten. Für die Box: „Simulierte evsoc-Box: leaf“ verbinden, unter Fahrzeug „Leaf ZE0“ suchen, `evsoc_nissan_leaf_evcan` anklicken und „Mit diesem Profil lesen“ drücken.

Probelauf und Mitlesen laufen im Hintergrund, die Seite zeigt den Fortschritt. Währenddessen sind Verbinden, Lesen und Dauerbetrieb gesperrt, damit sich nichts in die Quere kommt.

### Nur über Kabel (Raspberry Pi)

```bash
evsoc --nur-kabel gui --host eth0
```

Zeigt nur Kabel-Adapter (USB, CAN, ENET), blendet die Bluetooth-Suche aus und lehnt Funk-Adressen ab. Durch `--host eth0` ist die Oberfläche nur über das Ethernet-Kabel erreichbar, ebenfalls nur mit dem Link-Schlüssel. Mit `--token` bzw. `EVSOC_GUI_TOKEN` bleibt der Schlüssel über Neustarts gleich. Mehr in [raspberry-pi.md](raspberry-pi.md).

### Vom Handy aus (Heimnetz)

```bash
evsoc gui --host 0.0.0.0
```

Das Terminal zeigt einen Link mit Zugangsschlüssel (`…/?token=…`). Nur mit diesem Link lässt sich die Seite öffnen. Gedacht ist das zum Beispiel für einen Raspberry Pi mit `evsoc monitor`, den du vom Handy aus im WLAN anschaust.

Achtung: Die Verbindung ist unverschlüsselt (HTTP). Nur im eigenen Netz verwenden, nicht ins Internet freigeben. Für den Zugriff von unterwegs ist Home Assistant über `--mqtt` die bessere Wahl.

### Sicherheit

- Standardmäßig nur auf diesem Rechner erreichbar (127.0.0.1 und ::1).
- Jede Anfrage an die Schnittstelle braucht einen Sitzungsschlüssel, der in die Seite eingebettet ist. Fremde Webseiten im Browser können deshalb nicht auf die Oberfläche zugreifen.
- Der Host-Name wird geprüft, das verhindert sogenanntes DNS-Rebinding.
- Für das Auto gilt dasselbe wie überall in evsoc: nur Lesebefehle.

### Schnittstelle

Die Oberfläche nutzt eine kleine JSON-Schnittstelle, die auch Skripte verwenden können (Header `X-Evsoc-Token`):

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/info` | Version, Anzahl Profile und Marken |
| GET | `/api/devices`, `/api/devices/ble` | Adapter auflisten |
| GET | `/api/models?q=` | Fahrzeugsuche |
| GET | `/api/plan?profile=` oder `?car=` | OBD-Art und passende Adapter |
| GET | `/api/status` | Verbindung, letzter Wert, Verlauf, Dauerbetrieb, Protokoll |
| POST | `/api/connect` `{"url": …}`, `/api/disconnect` | Adapter verbinden/trennen |
| POST | `/api/read` `{"profile"\|"car", "all", "battery_kwh"}` | Ladestand lesen |
| POST | `/api/monitor/start` `{…}`, `/api/monitor/stop` | Dauerbetrieb |
