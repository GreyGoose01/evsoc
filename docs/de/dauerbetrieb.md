# Ladestand im geparkten Auto dauerhaft überwachen

## Grundsatz

**Direkt über die OBD-Buchse bei ausgeschaltetem, nicht ladendem Auto geht es in aller Regel nicht.** Batteriesteuergerät und Gateway schlafen, Anfragen bleiben unbeantwortet. Oder sie wecken Steuergeräte auf und ziehen Strom aus der 12-V-Batterie. Das berichten Nutzer von Car Scanner und OVMS übereinstimmend.

**Das ist aber weniger schlimm, als es klingt:**

1. Ein geparktes, nicht ladendes Auto verliert kaum Ladung. Der **letzte Wert beim Abstellen** ist praktisch der aktuelle.
2. **Während des Ladens** ist das Batteriesteuergerät wach. Bei vielen Autos lässt es sich dann lesen, aber nicht bei allen (siehe Test unten).
3. Ob das Auto wach ist, verrät die **12-V-Spannung**. Läuft das Hochvoltsystem (Fahren, Laden, Vorklimatisieren), hält der DC/DC-Wandler die 12-V-Batterie auf etwa 13,2–14,7 V. Im Schlaf ruht sie bei etwa 12,2–12,9 V. Der Adapter misst das selbst, **ohne eine einzige Botschaft auf den Bus zu schicken**.

Genau so arbeitet `evsoc monitor`: Spannung prüfen. Ist das Auto wach, liest er den Ladestand. Schläft es, schickt er nichts und meldet den letzten Wert samt Zeitstempel.

```
08:12:03  SoC 80.0 % (Stand 08:12:03)  12V 14.10 V  wach
08:13:03  SoC 79.8 % (Stand 08:13:03)  12V 14.05 V  wach
08:14:04  SoC 79.8 % (Stand 08:13:03)  12V 12.61 V  schläft
...
22:30:11  SoC 81.2 % (Stand 22:30:11)  12V 13.92 V  wach        ← Laden gestartet
```

## Aufbau

### Variante A: Adapter im Auto, evsoc zu Hause (Garage oder Stellplatz mit WLAN)

```
 Auto: WiCAN in der OBD-Buchse ──WLAN──► Heimnetz ──► Raspberry Pi / Home-Assistant-Server / Mac
                                                       evsoc monitor ──MQTT──► Home Assistant
```

1. WiCAN mit dem Heim-WLAN verbinden (Station-Modus) und als Protokoll „ELM327“ wählen.
2. Auf dem Rechner zu Hause:

```bash
evsoc monitor -a tcp://wican.local:3333 --car "e-208" \
  --state ~/evsoc-state.json \
  --mqtt "mqtt://user:passwort@homeassistant.local:1883/evsoc/auto"
```

Den Port zeigt die WiCAN-Weboberfläche (Standard 3333, WiCAN Pro 35000). Ist das Auto unterwegs, behält evsoc den letzten Wert und verbindet sich neu, sobald es zurück ist. Jeder ELM327-Adapter, der sich in ein vorhandenes WLAN einbuchen kann, funktioniert genauso; die meisten billigen WLAN-Adapter spannen aber nur ein eigenes Netz auf.

### Variante B: nur Kabel, ohne Funk

Pi im Auto, Adapter per USB oder CAN-Platine, Ethernet-Kabel ins Heimnetz. Läuft als Gerät mit `evsoc run`: [raspberry-pi.md](raspberry-pi.md).

### Variante C: unterwegs (Mobilfunk)

Kleiner Rechner plus Adapter plus LTE-Stick, evsoc meldet per MQTT an einen Server. Der Rechner braucht dann einen Abgriff, der nur bei wachem Auto Strom hat. Fertige Geräte wie WiCAN oder OVMS sind dafür meist einfacher.

## Optionen von `evsoc monitor`

| Option | Standard | Bedeutung |
|---|---|---|
| `--interval` | 60 s | Abstand, solange das Auto wach ist |
| `--sleep-interval` | 300 s | Abstand der Spannungsprüfung im Schlaf (kein Busverkehr) |
| `--awake-voltage` | 13,0 V | Schwelle wach/schläft |
| `--wake-every STD` | aus | schlafendes Auto wecken, wenn der letzte Wert älter als STD Stunden ist (z. B. 24) |
| `--wake-at HH:MM` | aus | zusätzlich täglich zu dieser Uhrzeit wecken (mehrfach angebbar) |
| `--min-voltage` | 12,2 V | nie wecken, wenn die 12-V-Batterie darunter liegt |
| `--wake-gap MIN` | 10 | Mindestabstand zwischen zwei Weckvorgängen auf Anforderung (MQTT, Knopf) |
| `--akku-kwh` | – | Nennkapazität netto für den SoH bei VW MEB (siehe [batteriegesundheit.md](batteriegesundheit.md)) |
| `--state DATEI` | – | letzter Stand als JSON; beim Neustart wird er geladen, auch das erkannte Profil |
| `--mqtt URL` | – | MQTT mit Home-Assistant-Discovery (Ladestand, Zeitstempel, 12-V-Spannung, Status, SoH) |
| `--webhook URL` | – | Stand als JSON per HTTP POST |
| `--json`, `--once` | – | JSON-Zeilen bzw. nur eine Prüfung (für cron oder systemd-Timer) |

Bei rohen CAN-Interfaces (`can://`) gibt es keine Spannungsmessung. Dort gilt das Auto als wach, wenn auf dem Bus Verkehr ist. Auch das geht ohne zu senden.

## Von außen lesen und wecken

Für den Blick von außen gehen die Werte per MQTT oder Webhook raus (oben). In die andere Richtung kann jetzt eine Anforderung hineinkommen: „lies jetzt“. Ist das Auto wach, liest evsoc sofort. Schläft es, weckt evsoc es dafür.

| Weg | So geht es |
|---|---|
| MQTT | `wake` (oder `read`) an `<thema>/cmd` senden, z. B. `mosquitto_pub -t evsoc/auto/cmd -m wake`. Läuft automatisch mit, sobald `--mqtt` gesetzt ist. |
| Home Assistant | bekommt über die Discovery einen Knopf „Jetzt lesen (weckt das Auto)“ |
| Oberfläche | Knopf „Jetzt lesen (weckt das Auto)“ unter Dauerbetrieb (`evsoc gui`) bzw. auf der Einrichtungsseite des Geräts (`evsoc run`, mit PIN) |

Schutz, damit eine Automation die 12-V-Batterie nicht leer zieht:

- nie unter `--min-voltage` (12,2 V),
- höchstens ein Weckvorgang alle `--wake-gap` Minuten (10). Frühere Anforderungen werden abgelehnt, das steht dann in `last_wake_result`,
- 30 Minuten nach dem Wecken prüft evsoc, ob das Auto wieder schläft, und warnt sonst.

Der MQTT-Weg braucht keinen offenen Port am Gerät: Es verbindet sich selbst zum Broker. Wer Befehle senden darf, regelt der Broker. Das Gerät im Auto braucht dafür eine Netzverbindung (WLAN am Stellplatz, LTE-Router oder -Stick). Im Nur-Kabel-Betrieb ohne Netz gibt es keinen Weg von außen.

## Wecktest: geht das bei meinem Auto?

Ob ein geparktes Auto auf eine Anfrage an der OBD-Buchse aufwacht, hängt von Auto, Adapter und Bus ab. `evsoc wake` misst es:

```bash
evsoc wake -a /dev/ttyUSB0 --car "e-208"          # Auto vorher abschließen, 15–30 min warten
evsoc wake -a enet://auto --car i4 --dauer 30
```

1. Zustand vorher: erreichbar, 12-V-Spannung, wach oder nicht.
2. Wecken: Ladestand lesen, bis zu fünf Versuche, Zeit bis zur ersten Antwort.
3. Beobachten, bis das Auto wieder schläft (`--dauer`, Standard 20 Minuten), ohne weitere Anfragen.

Das Ergebnis steht als Text da und als `evsoc-wecktest-DATUM.json` mit Zeitverlauf. In der Oberfläche: Dauerbetrieb → Wecktest.

Je nach Adapter sieht evsoc unterschiedlich viel:

| Adapter | Wach-Erkennung | Wecken |
|---|---|---|
| ELM327/OBDLink | 12-V-Spannung, ohne Busverkehr | Leseanfrage auf dem CAN |
| CAN-Interface (`can://`) | Verkehr auf dem Bus | Leseanfrage auf dem CAN |
| ENET (BMW/Mini) | nur „Gateway erreichbar“ | unklar, siehe unten |

**BMW über ENET:** Ein schlafendes Auto ist über ENET nicht erreichbar, und evsoc kann dort keine 12-V-Spannung messen. Ob Verbindungsversuche das Gateway wecken, ist nicht belegt; der Wecktest zeigt es. Umgekehrt kann ein dauerhaft gestecktes ENET-Kabel das Auto wach halten und die 12-V-Batterie leeren. Vor dem Dauerbetrieb über ENET deshalb den Wecktest machen und die 12-V-Spannung über Nacht kontrollieren. Für dauerhaftes Auslesen ist ein Adapter an den CAN-Pins (OBDLink, CAN-Interface, evsoc-Box) die besser prüfbare Wahl, weil er die Spannung misst.

## Einmal am Tag wecken?

**Ja, das ist ein guter Kompromiss.** Damit hast du auch nach Tagen Standzeit einen frischen Wert, etwa um einen schleichenden Verlust durch Wächter-Funktionen, Vorklimatisierung oder einen defekten Verbraucher zu bemerken.

```bash
evsoc monitor -a tcp://wican.local:3333 -p evsoc_stellantis_ecmp \
  --wake-every 24 --wake-at 06:30 --state ~/evsoc-state.json --mqtt "mqtt://…"
```

**Was beim Wecken passiert:**

1. evsoc schickt eine Leseanfrage. Die CAN-Botschaft weckt das Gateway, das wiederum das Batteriesteuergerät weckt.
2. Das Hochfahren dauert oft einen Moment. evsoc versucht es deshalb bis zu 3-mal im Abstand von 3 Sekunden.
3. Danach fragt evsoc nichts mehr, und das Auto schläft nach seiner eigenen Nachlaufzeit (meist Sekunden bis wenige Minuten) wieder ein.
4. **Nach 30 Minuten** prüft evsoc an der 12-V-Spannung, ob das Auto wirklich wieder schläft. Wenn nicht, erscheint ein Hinweis im Status (`note`).

**Schutzregeln:**

- Geweckt wird nur, wenn der letzte Wert älter ist als `--wake-every`. Kommst du gerade von einer Fahrt, passiert nichts.
- Pro Zeitraum gibt es höchstens einen Weckversuch. Antwortet das Auto nicht, versucht evsoc es erst im nächsten Zeitraum wieder. Das Ergebnis steht in `last_wake_result`.
- Unter `--min-voltage` (Standard 12,2 V) wird nie geweckt, damit eine ohnehin schwache 12-V-Batterie nicht weiter belastet wird.

**Was kostet das?** Größenordnung, nicht gemessen: Wach ziehen Gateway und Steuergeräte grob 1–5 A für ein paar Minuten, also etwa 0,05–0,3 Ah pro Weckvorgang. Ein Adapter ohne Schlafmodus mit 50 mA zieht dagegen 1,2 Ah **pro Tag**. **Der Ruhestrom des Adapters ist also viel wichtiger als ein tägliches Wecken.**

**Grenzen:** Nicht jedes Auto lässt sich über die OBD-Buchse wecken. Manche Gateways ignorieren Diagnoseanfragen bei ausgeschalteter Zündung komplett, oder das Batteriesteuergerät antwortet erst mit „Bereit“. Dann meldet evsoc `keine Antwort nach 3 Versuchen` und lässt das Auto in Ruhe. Probier es beim ersten Mal aus, während du in der Nähe bist: Wenn ein Auto beim Wecken Lichter oder Warnmeldungen zeigt, ist das Wecken für dieses Modell nichts.

## Die 12-V-Batterie schonen

- **Ruhestrom des Adapters:** Ein Adapter ohne Schlafmodus, der zum Beispiel 50 mA zieht, kostet in einer Woche rund 8 Ah. Das ist bei kleinen 12-V-Batterien von E-Autos ein spürbarer Anteil. Besser sind Adapter mit Schlafmodus (WiCAN, OBDLink). Bei längerer Standzeit den Adapter abziehen.
- **Wecken nur sparsam.** Einmal alle 12–24 Stunden ist vertretbar (siehe oben), alle paar Minuten nicht.
- **Schwelle prüfen:** Einmal bei schlafendem und einmal bei wachem Auto `evsoc monitor -a … --once` laufen lassen und die angezeigten Spannungen vergleichen. Autos mit 12-V-Lithium-Batterie ruhen höher (teils über 13 V). Dann `--awake-voltage` entsprechend anheben, etwa auf 13,6.
- **Manche Autos laden die 12-V-Batterie im Stand selbst nach.** Hyundai und Kia machen das zum Beispiel. Dabei steigt die Spannung kurz an, evsoc fragt ab, und das ist in Ordnung, denn das Auto ist in diesem Moment ohnehin wach.

## Test: Antwortet mein Auto beim Laden?

1. Auto abschließen, 10 Minuten warten, Ladekabel anstecken und Laden starten.
2. `evsoc read -a … -p <dein Profil>`
3. Kommt ein Ladestand, klappt der Dauerbetrieb inklusive Ladeverlauf. Kommt `NO DATA`, ist bei deinem Modell das Gateway beim Laden zu. Dann bleibt für den Ladeverlauf nur die Hersteller-Cloud, und evsoc liefert den Wert bei jeder Fahrt.

## Home Assistant

Mit `--mqtt` legt Home Assistant automatisch ein Gerät „evsoc …“ an mit den Sensoren *Ladestand*, *Ladestand Stand* (Zeitstempel), *12V-Batterie*, *Status* und *Batteriegesundheit*. Beispiel-Automation:

```yaml
automation:
  - alias: "Auto bei 80 % fertig"
    trigger:
      - platform: numeric_state
        entity_id: sensor.evsoc_evsoc_auto_ladestand
        above: 79.5
    action:
      - service: notify.mobile_app_handy
        data:
          message: "Auto hat {{ states('sensor.evsoc_evsoc_auto_ladestand') }} % erreicht."
```

## Alternativen ohne OBD

Im geparkten Auto ist die **Hersteller-Cloud** die zuverlässigste Quelle: Das Auto meldet seinen Stand über das eingebaute Modem beim Einschlafen und beim Laden. Dafür braucht es ein Konto, und die Werte können einige Minuten alt sein. Integrationen für Home Assistant:

| Hersteller | Integration |
|---|---|
| Peugeot, Opel, Citroën, DS, Fiat, Jeep | [homeassistant-stellantis-vehicles](https://github.com/andreadegiovine/homeassistant-stellantis-vehicles) |
| Hyundai, Kia, Genesis | [kia_uvo](https://github.com/Hyundai-Kia-Connect/kia_uvo) |
| VW, Skoda, Cupra | [volkswagencarnet](https://github.com/robinostlund/homeassistant-volkswagencarnet), [myskoda](https://github.com/skodaconnect/myskoda) |
| BMW, Mini | BMW CarData, z. B. [bmw-cardata-ha](https://github.com/kvanbiesen/bmw-cardata-ha) |
| Mercedes | [mbapi2020](https://github.com/ReneNulschDE/mbapi2020) |
| Ford | [ha-fordpass](https://github.com/marq24/ha-fordpass) |
| MG | [saic-python-mqtt-gateway](https://github.com/SAIC-iSmart-API/saic-python-mqtt-gateway) |
| Tesla | Tesla Fleet API, [TeslaMate](https://github.com/teslamate-org/teslamate) |
| Renault, Volvo, Polestar, Toyota | Home Assistant bzw. HACS |
