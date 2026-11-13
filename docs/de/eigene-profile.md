# Ein neues Auto entschlüsseln

So bin ich beim Corsa-e vorgegangen, und so geht es bei jedem Auto, das evsoc noch nicht kennt.

## 1. Gibt es schon etwas?

```bash
evsoc models <modell>
evsoc update                   # holt die neuesten Profile aus OBDb, ABRP, WiCAN
evsoc read -a … --car "<modell>"
```

Oft hilft ein baugleiches Modell einer anderen Marke, das `--car` über die Plattform automatisch mitprobiert. Außerdem lohnt ein Blick in das OBDb-Repository des Modells (`github.com/OBDb/<Marke>-<Modell>`): Unter `tests/test_cases` liegen oft echte Mitschnitte, auch wenn noch keine Signale eingetragen sind.

## 2. Mitschnitt besorgen

**Variante A: eine App, die das Auto schon kann.** Car Scanner (iOS/Android) kann für viele Autos Ladestand und Spannung anzeigen und unter *Einstellungen → Adapter → Log exportieren* den kompletten Adapterverkehr speichern.

1. Nur den Ladestand-Sensor öffnen und ein paar Sekunden laufen lassen.
2. Den angezeigten Wert notieren, idealerweise bei zwei verschiedenen Ladeständen.
3. Log exportieren.

**Variante A2: mit Y-Kabel mitlesen.** Zweiten Adapter per Y-Kabel anstecken und `evsoc sniff` laufen lassen, während die App den Wert anzeigt. Werte eintippen, evsoc sucht die Formel und schreibt das Profil (`--profil`). Siehe [mitlesen.md](mitlesen.md).

**Variante B: selbst suchen.** Mit `evsoc raw` Kennungen abklopfen (nur Lesen):

```bash
evsoc raw -a /dev/cu.X ATSP6 ATSH7E4 ATCRA7EC 220101 220105
```

## 3. Antwort finden und Formel ableiten

Im Log nach Zeilen wie dieser suchen:

```
>22D410
6940562D4106D9D
```

| Teil | Bedeutung |
|---|---|
| `694` | Absender (Steuergerät) → `ATCRA694`, Anfrage ging an `6B4` (Zeile `ATSH6B4` davor) |
| `05` | ISO-TP-Länge: 5 Bytes folgen |
| `62 D4 10` | positive Antwort auf `22 D4 10` |
| `6D 9D` | Daten: `A = 0x6D`, `B = 0x9D` |

Dann probieren, welche Rechnung den notierten Wert ergibt:

| Rechnung | Ergebnis | Anzeige 54,79 % |
|---|---|---|
| `A` | 109 | nein |
| `INT16(A,B)` | 28061 | nein |
| `INT16(A,B)/512` | **54,81** | ja |

Mit einem zweiten Wert gegenprüfen. Im Corsa-Log ergab `9F EB` 79,96 %, und die Zellspannung passte dazu.

Typische Skalierungen: `/2`, `/10`, `/100`, `/512`, `*100/255`, `/2.5`, `-40` (Temperaturen), `Signed()` für Ströme.

## 4. Profil schreiben

Datei `evsoc/profiles/own/evsoc_<name>.json` (Name muss mit `evsoc_` beginnen):

```json
{
  "name": "evsoc_mein_auto",
  "description": "Marke Modell, BMS 6B4 -> 694, aus Car-Scanner-Log abgeleitet",
  "source": "eigener Mitschnitt 2026-10",
  "verified": "Modell Baujahr, SoC bei 2 Werten geprüft",
  "vehicles": [{"make": "Peugeot", "model": "e-208", "years": [2019, null]}],
  "init": [],
  "steps": [
    {"id": "soc", "at": ["ATSP6", "ATSH6B4", "ATCRA694", "ATCEA", "ATFCSH6B4", "ATFCSD300000", "ATFCSM1"],
     "request": "22D410"}
  ],
  "fields": {
    "soc": {"step": "soc", "decode": {"type": "equation", "expr": "INT16(A,B)/512"},
            "min": -5, "max": 105, "unit": "%"}
  }
}
```

Hinweise:

- In `at` alles, was der Schritt braucht. `ATCEA` (ohne Wert) und `ATFCSM0` setzen die Einstellungen anderer Profile zurück.
- `ATFCSH…`, `ATFCSD300000`, `ATFCSM1` nur nötig, wenn das Steuergerät eine eigene Flusssteuerungs-Adresse erwartet (steht dann so im Log).
- Weitere Felder nach Bedarf: `soc_display`, `soc_bms`, `soh`, `voltage`, `current`, `batt_temp`, `cell_min_voltage`, `cell_max_voltage`, `capacity`.
- Meldet das Auto keinen SoH, sondern nur den maximalen Energieinhalt in kWh: Feld `soh` mit derselben Formel und `"percent_of": "battery_kwh"`. Dann rechnet evsoc mit der angegebenen Nennkapazität (`--akku-kwh`). Unter `"battery_kwh": [58, 77]` die üblichen Werte nennen, sie erscheinen im Hinweis, wenn die Angabe fehlt. Beispiel: `evsoc_vw_meb`.

## 5. Testen

```bash
evsoc profiles -v | grep -A3 evsoc_mein_auto     # lädt das Profil (Syntaxfehler fallen hier auf)
evsoc read -a /dev/cu.X -p evsoc_mein_auto --all
```

Für einen Test ohne Auto die Antwort in `evsoc/mock.py` unter `VEHICLES` eintragen und in `tests/test_end_to_end.py` einen Testfall ergänzen.

## 6. Teilen (optional)

Funktionierende Profile freuen auch andere: als Pull Request an [OBDb](https://github.com/OBDb), [ABRP ev-obd-pids](https://github.com/iternio/ev-obd-pids) oder [WiCAN](https://github.com/meatpiHQ/wican-fw). Nach dem nächsten `evsoc update` kommen sie dann automatisch zurück.
