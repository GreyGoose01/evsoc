# Probelauf am Auto (`evsoc probe`)

`evsoc read` hört beim ersten Profil auf, das einen plausiblen Ladestand liefert. `evsoc probe` urteilt nicht: Es fragt alles ab, was die zum Auto passenden Profile kennen, hebt jede Rohantwort auf und zeigt, was jedes Profil daraus macht. Was stimmt, entscheiden wir danach anhand der Werte, die du im Auto abgelesen hast.

Alles ist nur lesend. Schreib-, Lösch- und Codierbefehle blockiert evsoc vor dem Senden.

Ohne Terminal geht dasselbe in der Oberfläche unter „Probelauf“ ([gui.md](gui.md)).

Zum Probelauf gehört ein Blick in die Steuergeräte: Für jedes, das geantwortet hat, liest evsoc Kennung (Teilenummer, Seriennummer, Softwarestand) und Fehlerspeicher. Über ENET fragt es dazu die bekannten BMW-Adressen ab, mit `--alle` alle 256. Der Fehlerspeicher wird nur gelesen (UDS `19 02`, OBD `03`/`07`/`0A`); Löschen (`14`, OBD `04`) bleibt gesperrt. Die Codes erscheinen als Nummer und hex, Klartexte sind herstellerspezifisch und nicht hinterlegt. Abschalten mit `--ohne-diagnose`.

## Ablauf

1. Zündung an (bei BMW: Start-Knopf ohne Bremse), Adapter stecken.
2. Im Auto ablesen und notieren: Ladestand in Prozent, Reichweite, Kilometerstand, Außentemperatur. Falls die Hersteller-App einen SoH oder eine Batterietemperatur zeigt, auch die.
3. Probelauf starten und die abgelesenen Werte mitgeben:

```bash
evsoc probe -a enet://auto --car i4 --notiz soc=54 --notiz km=23150 --log i4-verkehr.txt
evsoc probe -a /dev/cu.OBDLinkMXPlus --notiz soc=71           # Auto wird über die VIN erkannt
```

4. Am besten später bei einem **anderen Ladestand** wiederholen (nach einer Fahrt oder Ladung). Werte, die sich mit dem Ladestand bewegen, sind Ladestand, Energie oder Spannung. Werte, die gleich bleiben, sind Kandidaten für Kapazität und SoH.

Ausgabe (gekürzt):

```
Fahrzeug: VR3ATTENTKY000001, Modelljahr 2019   Adapter: ELM327-Adapter, 13.9 V
53 Anfragen, 14 Antworten, 41 s
Notiert: soc=51

evsoc_stellantis_phev   8/8 Werte plausibel   <- das würde 'evsoc read' wählen
    soc                            50 %   passt zu soc=51
    voltage                       340 V
    current                       -12 A
    soh                            96 %
    ...

obdb_peugeot_208   1/4 Werte plausibel
    soc                    -            (Keine Antwort: NO DATA)
    soc_bms                     0.391 %   WEICHT AB von soc=51
    soh                    -            (Antwort zu kurz: 24 Bits nötig, 16 vorhanden)
    ...

evsoc_stellantis_ecmp   3/11 Werte plausibel   anderes Steuergerät (22D860: 2 statt 3 Datenbytes)
    ...

Bericht: evsoc-probe-VR3ATTENTKY000001-20261112-101500.json
```

## Optionen

| Option | Wirkung |
|---|---|
| `--car "i4"` | Modell vorgeben statt über die VIN suchen |
| `--notiz name=wert` | abgelesener Wert zum Vergleich, mehrfach möglich. `soc` und `soh` werden mit allen Feldern der Familie verglichen (`soc_bms`, `soc_display` …, Toleranz 3 Prozentpunkte), andere Namen nur mit dem gleichnamigen Feld (5 %) |
| `--alle` | alle 270 Profile testen, nicht nur die passenden. Für Autos, die evsoc nicht kennt; dauert einige Minuten |
| `--raw BEFEHL …` | danach zusätzliche Lesebefehle wie bei `evsoc raw`, auch Bereiche: `--raw ATSH6F1 ATCEA07 22E500-22E5FF` |
| `--ohne-diagnose` | Kennung und Fehlerspeicher der Steuergeräte nicht lesen |
| `--akku-kwh 77` | Nennkapazität, falls ein Profil den SoH aus dem Energieinhalt rechnet |
| `--log datei` | zusätzlich den gesamten Adapter-Verkehr mitschreiben |
| `-o datei.json` | Name des Berichts |
| `-d bericht.json` | kein Auto: einen Bericht mit den aktuellen Profilen neu auswerten |

## Was ich zum Auswerten brauche

1. **Die Berichtsdatei** `evsoc-probe-….json`. Sie enthält jede Anfrage mit Rohantwort, die VIN, den Adapter und deine Notizen. Daraus lässt sich alles nachrechnen.
2. **Die abgelesenen Werte**, am besten gleich als `--notiz`, sonst dazugeschrieben. Ohne Vergleichswert lässt sich nur sagen, ob ein Wert plausibel ist, nicht, ob er stimmt.
3. **Zwei Läufe bei unterschiedlichem Ladestand**, wenn es um neue Werte geht (SoH, Kapazität).
4. Bei Problemen die `--log`-Datei.

Die VIN steht im Bericht. Wer sie nicht weitergeben will, ersetzt die letzten sechs Stellen in der Datei.

Weil der Bericht die Rohantworten enthält, kann eine korrigierte Formel ohne Auto geprüft werden: Profil ändern, `evsoc probe -d bericht.json` zeigt das neue Ergebnis.

## Reicht ein reiner CAN-Mitschnitt (z. B. CL2000)?

Meist nicht. Bei fast allen Autos ab etwa 2016 sitzt hinter der OBD-Buchse ein Gateway. Ohne Anfrage ist der Bus dort still, die Batteriewerte kommen nur als Antwort auf einen Lesebefehl. Ein Logger, der nur zuhört, zeichnet dann nichts Brauchbares auf.

Ein Mitschnitt hilft in drei Fällen:

| Fall | Was der Logger sieht | Auswertung |
|---|---|---|
| Der Logger hängt per Y-Kabel **parallel**, während evsoc oder eine App (Car Scanner, BimmerLink …) fragt | Anfragen und Antworten | `evsoc sniff -d datei.txt`, siehe [mitlesen.md](mitlesen.md) |
| Autos **ohne Gateway** an der Buchse (smart electric drive 451, Tesla über Diagnosekabel, Leaf an Pins 12/13) | die Botschaften des Fahrzeugs | `evsoc sniff -d datei.txt` |
| Der Logger sendet selbst eine Liste von Anfragen | nur Antworten, die in eine Botschaft passen (bis 7 Bytes). Für längere müsste er die Flusssteuerung des ISO-TP-Protokolls senden | eingeschränkt |

`evsoc sniff -d` liest die Textdateien des CL1000/CL2000 (`Timestamp;Type;ID;Data`). Das Format ist nach der Herstellerbeschreibung umgesetzt und noch mit keiner echten Datei geprüft; eine Beispieldatei hilft.

Für BMW über ENET gibt es keinen CAN-Mitschnitt, dort läuft alles über das Netzwerkkabel. Der Probelauf mit `--log` ist das Gegenstück.
