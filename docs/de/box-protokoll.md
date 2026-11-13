# evsoc-Box: Protokoll 0.1

Diese Beschreibung legt fest, was eine Universal-Adapter-Firmware können muss, damit evsoc sie über `box:…` nutzen kann. Umgesetzt ist die Gegenseite in `evsoc/universal.py`, die Simulation in `evsoc/mock.py` (`MockBoxTransport`).

## Grundlagen

- **Transport:** ausschließlich USB-CDC (virtueller serieller Port, unter Linux `/dev/ttyACM0`). Die Box hat kein WLAN und kein Bluetooth. Die Baudrate ist bei USB-CDC egal.
- **Format wie ELM327:** Befehl plus `CR`, Antwortzeilen mit `CR` getrennt, am Ende das Prompt-Zeichen `>`.
- **ELM327-Befehlssatz:** Die Box muss mindestens das können, was evsoc-Profile verwenden: `ATZ ATD ATI ATE0 ATL0 ATS0 ATH1 ATD0 ATRV ATSP ATSH ATCP ATCRA ATCEA ATCAF ATFCSH ATFCSD ATFCSM ATST ATAT ATAL ATPB ATMA`, dazu Diagnoseanfragen als Hex-Text. Damit funktionieren auch andere OBD-Programme, die einen ELM327 per USB ansprechen.
- **Antwortformat für Daten** wie beim ELM327 mit `ATH1 ATS0 ATD0`: eine Zeile pro CAN-Frame, `<CAN-ID><Datenbytes>` in Hex. Bei CAN-FD dürfen Frames mehr als 8 Datenbytes haben.
- **`ATZ`/`ATD`** setzen auch die Bus-Wahl zurück auf CAN an 6/14 und schalten den Mithörmodus aus.

## Zusätzliche Befehle

### `EVSI`: Kennung und Fähigkeiten

```
>EVSI
EVSOC-BOX 0.1 KINDS=CAN,CANFD PINS=6/14,12/13,3/11 LISTEN=1
```

| Feld | Bedeutung |
|---|---|
| `EVSOC-BOX <version>` | muss am Zeilenanfang stehen, sonst lehnt evsoc den Adapter als Box ab |
| `KINDS=` | unterstützte Bus-Arten: `CAN`, `CANFD`, `KLINE`, `J1850`, `SWCAN`, `DOIP` |
| `PINS=` | erreichbare Pinpaare, z. B. `6/14,12/13`, oder `ANY` |
| `LISTEN=1` | Listen-only-Modus vorhanden |

### `EVSBUS`: Bus wählen

```
EVSBUS <ART> <PINS> [BITRATE] [DATENBITRATE]
```

| Beispiel | Bedeutung |
|---|---|
| `EVSBUS CAN 6,14 500000` | High-Speed-CAN an den Standard-Pins |
| `EVSBUS CAN 12,13 500000` | zweiter Bus an 12/13 (z. B. Nissan Leaf EV-CAN) |
| `EVSBUS CANFD 6,14 500000 2000000` | CAN-FD, 500 kbit/s Arbitrierung, 2 Mbit/s Daten |
| `EVSBUS KLINE 7,15 10400` | K-Line |
| `EVSBUS SWCAN 1 33333` | GM Single-Wire-CAN |
| `EVSBUS DOIP 1` | Ethernet nach ISO 13400-4 Option 1 (Pins 3/11/12/13, Aktivierung Pin 8); `2` = Option 2 |

Antwort `OK` oder `ERR <Grund>`, z. B. `ERR PINS` (Pinpaar nicht schaltbar) oder `ERR ETHERNET-ON-PINS` (dort liegt Ethernet, CAN wird nicht zugeschaltet). Die Protokolldetails (11/29 Bit, Header, Filter) kommen weiter über die normalen ELM-Befehle (`ATSP`, `ATSH`, `ATCRA` …). `EVSBUS` wählt nur Pins, Transceiver und Bitrate.

### `EVSLISTEN`: nur mithören

```
EVSLISTEN 1      # Listen-only: keine Bestätigungen (ACK), keine Fehlerrahmen, kein Senden
EVSLISTEN 0
```

Bei `EVSLISTEN 1` beantwortet die Box Diagnoseanfragen mit `ERR LISTEN-ONLY`. Mitgehört wird mit `ATCRA <ID>` und `ATMA`.

### `EVSSCAN`: aktive Busse suchen

```
>EVSSCAN
BUS CAN 6,14 500000 FRAMES=812 IDS=1A0,1A1,5C0,7BB
BUS CAN 12,13 500000 FRAMES=240 IDS=55B,5BC
BUS DOIP 1 100000000
OK
```

Die Box sucht nur im Listen-only-Modus (Ablauf siehe [universal-adapter.md](universal-adapter.md#firmware)). Sie stellt danach wieder CAN an 6/14 ein. Die Dauer ist begrenzt, evsoc wartet bis zu 30 Sekunden.

## Sicherheitsanforderungen an die Firmware

1. **Lesedienste-Filter in der Firmware:** Nur die Dienste `01`, `09`, `21`, `22`, `1A`, `10 01`, `10 03` und `3E` dürfen gesendet werden, alles andere mit `ERR BLOCKED` ablehnen. Das gilt auch für Anfragen fremder Apps.
2. **Rohsenden** (`ATCAF0` mit eigenen Frames) nur, wenn der Inhalt einer erlaubten Anfrage entspricht.
3. **Kein Abschlusswiderstand** auf irgendeinem Bus.
4. **Ethernet zuerst erkennen:** Bevor ein CAN-Transceiver auf 3/11, 1/9 oder 12/13 geschaltet wird, Pin 8 prüfen.
5. **Unterspannung:** unter etwa 11,8 V keine Anfragen mehr senden und in den Schlafmodus wechseln.
6. **Kein Funk:** Die Hardware hat keine Funkschnittstelle. Die Firmware darf nur über USB erreichbar sein.

## Versionierung

Neue Befehle kommen mit neuer Versionsnummer in `EVSI` dazu. evsoc wertet nur die Felder aus, die es kennt.
