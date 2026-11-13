# Funktionsweise

## Der Weg einer Anfrage

```
evsoc ──"22D410"──► Adapter ──CAN-Frame 6B4: 03 22 D4 10──► Batteriesteuergerät
evsoc ◄─"6940562D4106D9D"── Adapter ◄──CAN-Frame 694: 05 62 D4 10 6D 9D───┘
```

1. **Service 22 (ReadDataByIdentifier)** aus der Diagnosenorm UDS: „Gib mir den Wert mit der Kennung (DID) D410.“
2. Der Adapter verpackt das in einen CAN-Frame an die Adresse des Steuergeräts (`6B4`). Die erste Datenbyte-Stelle ist die Länge (ISO-TP).
3. Das Steuergerät antwortet von `694` mit `62` (= 22 + 40, also positiv), der Kennung `D4 10` und den Daten `6D 9D`.
4. evsoc rechnet: `0x6D9D = 28061`, `28061 / 512 = 54,8 %`.

Längere Antworten (z. B. Hyundai `220105` mit über 40 Bytes) kommen in mehreren Frames: ein „First Frame“ mit der Gesamtlänge, dann „Consecutive Frames“. Dazwischen schickt der Tester eine Flusssteuerung („Flow Control“). Das Zusammensetzen heißt ISO-TP (ISO 15765-2).

Ältere Verfahren, die evsoc ebenfalls nutzt:

- **OBD-Service 01** mit genormten PIDs, z. B. `015B` (Hybridbatterie-Restladung), `019A` (Spannung/Strom), `01B2` (SoH)
- **KWP2000-Service 21** bei älteren Hyundai/Kia und Toyota
- **Passives Mithören** bei Tesla: keine Anfrage, nur die Botschaft `0x292` lesen, die das Auto ohnehin ständig sendet

## Adressierung

| Art | Beispiel | AT-Befehle |
|---|---|---|
| 11 Bit, normal | Hyundai: an `7E4`, Antwort `7EC` | `ATSP6 ATSH7E4 ATCRA7EC` |
| 11 Bit, erweitert (BMW) | an `6F1` mit Zieladresse `07` im ersten Datenbyte, Antwort `607` | `ATSH6F1 ATCEA07 ATCRA607` |
| 29 Bit, normal fixed | Renault: `18DADBF1` → `18DAF1DB` | `ATSP7 ATCP18 ATSHDADBF1` |
| 29 Bit, VW-Stil | `17FC007B` → `17FE007B` | `ATSP7 ATCP17 ATSHFC007B ATCRA17FE007B` |

## Profile

Ein Profil (JSON, Format v2) besteht aus **Schritten** und **Feldern**:

```json
{
  "name": "evsoc_stellantis_ecmp",
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

- **Jeder Schritt bringt den kompletten Adapterzustand mit** (`at`). Dadurch lassen sich Schritte beliebig mischen, und die Auto-Erkennung kann Anfragen verschiedener Profile zusammenlegen.
- Optional: `years` (gilt nur für diese Modelljahre), `pre`/`post` (z. B. Sitzungswechsel `1003`), `listen` statt `request` (passives Mithören).
- Optional `connection` (ganzes Profil) bzw. `bus` (ein Schritt), wenn es nicht normales CAN an 6/14 ist: `{"pins": [12, 13]}`, `{"fd": true, "data_bitrate": 2000000}`, `{"kind": "kline"}`, `{"cable": "Tesla-Diagnosekabel"}`. Ohne Angabe leitet evsoc den Bus aus `ATSP`/`ATPB` ab ([universal-adapter.md](universal-adapter.md)).
- `min`/`max` sind Plausibilitätsgrenzen. Daran erkennt die Auto-Erkennung, ob ein Profil passt.

### Vier Formel-Typen

| `type` | Herkunft | zählt Bytes … | Beispiel |
|---|---|---|---|
| `equation` | ABRP/Torque, eigene | ab dem ersten Datenbyte nach `62 xx xx`: `A`, `B`, …, `Z`, `AA` … | `INT16(A,B)/512`, `Signed(K)*256+L`, `{A:3}` |
| `wican` | WiCAN | in den rohen CAN-Bytes **inklusive** Längen- und Rahmenbytes: `B0`, `B1` … | `[B4:B5]/512`, `S21`, `B15:0` |
| `bits` | OBDb | bitgenau ab dem ersten Datenbyte | `{"bix": 248, "len": 8, "div": 2}` |
| `dbc` | DBC-Dateien | in einer Broadcast-Botschaft | `{"start": 10, "len": 10, "factor": 0.1}` |

Beispiel, warum das wichtig ist: Hyundai `220105`, Ladestand in Datenbyte 31.

- OBDb: `bix` 248 (31 × 8)
- WiCAN: `B41`, weil 5 Rahmenbytes und 5 Bytes Kopf davorliegen
- ABRP: müsste `af` sein

Alle drei beschreiben dasselbe Byte. Die Tests prüfen das mit einer simulierten Antwort.

## Auto-Erkennung

1. **VIN lesen** (`0902`, sonst `22F190`). Aus den ersten drei Zeichen folgt der Hersteller, aus dem zehnten das Modelljahr.
2. **Kandidaten bilden.** Zuerst Profile des Herstellers, dann der Konzernschwestern (z. B. Peugeot → Opel, Citroën, DS, Fiat, Jeep) und derselben Plattform. Ganz am Ende kommen das Standardprofil und das passive Mithören. Mit `--car` stattdessen Modell und Plattform.
3. **Probieren mit Cache.** Für jedes Profil nur die Ladestand-Schritte. Gleiche Anfragen (gleicher Adapterzustand plus gleicher Befehl) gehen nur einmal ans Auto. Der Adapter wird nur zurückgesetzt, wenn sonst Einstellungen eines anderen Profils übrig blieben.
4. **Bewerten.** Ein Profil passt, wenn ein Ladestand plausibel ist. Bei mehreren Treffern gewinnt: modellgenau vor „alle Modelle“, mehr plausible Werte, bekannte E-Plattform, dann die Quelle (eigene, OBDb, ABRP, WiCAN). Die anderen Treffer stehen unter „ebenfalls plausibel“.

## Code-Aufbau

```
evsoc/
  cli.py          Kommandozeile
  appliance.py    evsoc run: Gerätedienst (Dauerbetrieb, Weitergabe, Anzeige, PIN-geschützte Einrichtung)
  config.py       gespeicherte Gerätekonfiguration, PIN-Hash
  detect.py       Adapter selbst finden (evsoc-Box, USB, CAN)
  gui.py          Werkstatt-Oberfläche (evsoc gui), Seite in web/index.html
  web/app.html    Anzeige des Geräts, web/setup.html Einrichtung
  reader.py       Profile ausführen, dekodieren, Auto-Erkennung
  monitor.py      Dauerbetrieb: 12-V-Spannung als Wach-Erkennung, MQTT/HA, Webhook, Statusdatei
  profiles.py     Profilformat v2, Laden, Kandidatenwahl
  vehicles.py     VIN → Hersteller/Modelljahr, Konzerne, Plattformen
  decoders.py     equation / wican / bits / dbc
  equation.py     Torque/ABRP-Formeln (eigener Parser, kein eval)
  connection.py   OBD-Art pro Profil-Schritt (Bus, Pins, Bitrate, passiv), Adapter-Fähigkeiten, Prüfung
  universal.py    evsoc-Box: Bus-Wahl (EVSBUS), Mithörmodus, Bus-Suche
  wired.py        Nur-Kabel-Modus: USB-Erkennung, SocketCAN, Bindung an eine Netzwerkschnittstelle
  elm.py          ELM327/STN: AT-Befehle, Zustands-Cache, ISO-TP, Mithören
  canbus.py       rohes CAN über python-can: eigenes ISO-TP, CAN-FD
  enet.py         BMW ENET (HSFZ über TCP 6801)
  transports.py   Seriell/Bluetooth, WLAN, BLE, Mitschnitt
  safety.py       Sperre: nur Lesedienste
  importers.py    OBDb, ABRP, WiCAN → Profile (evsoc update)
  mock.py         simulierter ELM327 mit Testfahrzeugen
  profiles/own/        eigene, geprüfte Profile
  profiles/generated/  importierte Profile (nicht von Hand ändern)
```
