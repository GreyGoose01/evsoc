# Universal-Adapter (evsoc-Box)

Ein Adapter für alle Autos braucht drei Dinge. Nur das erste ist Hardware:

| Ebene | Frage | Lösung |
|---|---|---|
| Elektrik | Auf welchen Pins und mit welchem Protokoll redet das Auto? | genug Transceiver und eine Pin-Umschaltung (evsoc-Box) |
| Zugang | Lässt das Gateway Diagnoseanfragen durch? | meistens; Tesla braucht ein Spezialkabel, manche Gateways eine Freischaltung |
| Bedeutung | Welche Anfrage liefert den Ladestand, und wie rechnet man ihn um? | die Profile von evsoc |

Bauen: [bauanleitung-box.md](bauanleitung-box.md). Firmware-Befehle: [box-protokoll.md](box-protokoll.md).

## So wählt evsoc die OBD-Art

1. **Fahrzeug bestimmen:** `--car`, VIN oder Auto-Erkennung.
2. **Bus pro Abfrageschritt ableiten** (`evsoc/connection.py`) aus den Protokollbefehlen des Profils (`ATSP6` = CAN 11 Bit, `ATSP7` = 29 Bit, `ATSPB` + `ATPB…` = Sondereinstellung, `ATSP3`–`5` = K-Line). Profile können das übersteuern, z. B. `"connection": {"pins": [12, 13]}` beim Leaf oder `{"fd": true}` für CAN-FD.
3. **Adapter prüfen:** Jeder Adaptertyp kennt seine Bus-Arten, Pins und ob er mithören kann. Passt er nicht, sagt evsoc vor dem ersten Byte, warum, und welcher passen würde.
4. **Umschalten:** Die evsoc-Box stellt evsoc vor jedem Schritt um (`EVSBUS CAN 12,13 500000`, `EVSLISTEN 1`).

```bash
evsoc plan "Nissan Leaf"                     # welche OBD-Art, welche Adapter passen
evsoc plan "Nissan Leaf" -a /dev/cu.OBDLink  # passt mein Adapter?
evsoc scan -a box:/dev/ttyACM0               # welche Busse liegen an? (nur mit Box)
```

| Fahrzeug | OBD-Art | Hinweis |
|---|---|---|
| Peugeot e-208, Opel Corsa-e | CAN 500 kbit/s, 11 Bit, Pins 6/14 | jeder Adapter |
| VW ID.3/ID.4, Renault Zoe Ph2 | CAN 500 kbit/s, 29 Bit, Pins 6/14 | jeder Adapter |
| BMW i3, Mini SE | CAN 11 Bit mit erweiterter Adressierung **oder** Ethernet (ENET) | Billig-Klone scheitern an `ATCEA` |
| Nissan Leaf bis 2017 | passiv: EV-CAN an Pins 12/13 | evsoc-Box oder CAN-Interface mit eigenem Kabel |
| Tesla Model 3/Y | CAN, nur mithören, Tesla-Diagnosekabel | an der OBD-Buchse keine Daten |
| ältere Hybride | teils K-Line an 7/15 | OBDLink oder evsoc-Box |
| GM ab ca. 2020 | teils CAN-FD | ELM327-Adapter können das nicht |

## Was an der OBD-Buchse anliegen kann

| Pins | Bus | wo |
|---|---|---|
| 6 / 14 | High-Speed-CAN 500 kbit/s, zunehmend CAN-FD | alle E-Autos |
| 3 / 11 | Mid-Speed-CAN (Ford), AV-CAN (Leaf) | herstellerspezifisch |
| 12 / 13 | EV-CAN (Leaf bis 2017) | herstellerspezifisch |
| 1 | Single-Wire-CAN | GM |
| 3 / 11 / 12 / 13 + 8 | Automotive Ethernet, ISO 13400-4 Option 1 | BMW (ENET), zunehmend andere |
| 1 / 9 / 12 / 13 + 8 | Automotive Ethernet, Option 2 | neuere Autos |
| 7 / 15 | K-Line (ISO 9141, KWP2000) | ältere Autos und Hybride |
| 16 / 4 / 5 | 12 V, Karosseriemasse, Signalmasse | immer |

Pin 8 aktiviert Ethernet. Die Optionen unterscheiden sich in den Empfangsleitungen (3/11 oder 1/9).

## Was handelsübliche Adapter abdecken

| Adapter | HS-CAN | CAN-FD | andere Pins | K-Line | Ethernet | in evsoc |
|---|---|---|---|---|---|---|
| ELM327-Klon | ja (oft wackelig) | nein | nein | teils | nein | `/dev/cu…`, `tcp://`, `ble://` |
| OBDLink MX+ / SX / EX | ja | nein | MS-/SW-CAN (schaltet evsoc noch nicht) | ja | nein | `/dev/cu…` |
| BMW-ENET-Kabel | nein | nein | – | nein | ja (BMW) | `enet://` |
| CAN(-FD)-Interface + Kabel | ja | mit FD-Interface | über Kabel (`?pins=12,13`) | nein | nein | `can://` |
| **evsoc-Box** (nur USB) | ja | ja | alle, umschaltbar | ja | geplant | `box:/dev/ttyACM0` |

Ohne Eigenbau deckt OBDLink + ENET-Kabel + CAN-FD-Interface + Tesla-Kabel praktisch jedes Auto ab, zusammen etwa 150–200 €.

## Aufbau der Box

**Anforderungen:** alle Busse der Tabelle per Software umschaltbar; ELM327-kompatibel plus eigene Befehle; standardmäßig nur lesend; Mithören ohne Bestätigungen; nur USB, **kein WLAN und kein Bluetooth** (weniger Strom, keine Angriffsfläche, keine Funkzulassung); Ruhestrom unter 1 mA.

```
 OBD 16 ─ 12 V ─► Verpolschutz ─ TVS ─ Step-down (Ruhestrom < 50 µA) ─ Spannungsmessung
 OBD 6/14, 3/11, 12/13, 1/9, 1, 7/15, 8
        │
   Pin-Matrix (Relais/PhotoMOS): jedes Pinpaar auf einen Kanal schaltbar, Standard: nur 6/14
        │
   3× CAN-FD-Transceiver · SW-CAN · K-Line · 100BASE-TX-PHY + Übertrager
        │
   STM32H723 (3× FDCAN, Ethernet-MAC, USB)
        │
   USB-C (virtueller COM-Port) ── optional USB-Isolator ──► Raspberry Pi / Rechner
```

**Pin-Matrix:**

- Ein Transceiver an Pins, auf denen Ethernet liegt, kann stören. Deshalb hängt anfangs nur CAN-Kanal 1 an 6/14. Alles andere wird erst zugeschaltet, wenn das Profil es verlangt oder die Bus-Suche es bestätigt.
- Die Schalter müssen Bordspannung aushalten (Fehlerfall) und wenig Kapazität haben (CAN-FD). Analogschalter für 3,3 V reichen nicht.
- Kein eigener Abschlusswiderstand.
- Vor Ethernet erst Pin 8 prüfen und nie gleichzeitig einen CAN-Transceiver an dieselben Pins schalten.

### Bauteile für die eigene Platine

| Funktion | Beispiel | Warum |
|---|---|---|
| Mikrocontroller | STM32H723 | 3× CAN-FD, Ethernet-MAC und USB auf einem Chip (STM32G474: ohne Ethernet; STM32H563: nur 2× CAN) |
| CAN-FD-Transceiver | TI TCAN1462, NXP TJA1463 | bis 5 Mbit/s; der TJA1463 weckt das Gerät bei Busaktivität |
| K-Line | ST L9637D | Standardbaustein für ISO 9141/KWP2000 |
| Ethernet | 100BASE-TX-PHY (z. B. LAN8742A) + Übertrager | DoIP an der OBD-Buchse ist 100BASE-TX |
| USB | USB-C mit ESD-Schutz, optional Trennung mit ADuM3160 | einzige Verbindung zum Pi |
| Stromversorgung | Step-down mit sehr kleinem Ruhestrom, Verpolschutz, TVS | Dauerbetrieb ohne die 12-V-Batterie zu leeren |

### Firmware

```
 USB-CDC  →  Befehlsparser (ELM327 + EVS)  →  Sicherheitsfilter (nur Lesedienste)
          →  ISO-TP (klassisch + FD), KWP, DoIP/HSFZ  →  Bus-Treiber + Pin-Matrix
```

Der Sicherheitsfilter sitzt **zusätzlich** zur Sperre in evsoc in der Firmware, damit die Box auch mit fremden Programmen nur lesend bleibt.

**Bus-Suche (`EVSSCAN`)**, nur im Mithörmodus:

1. Pin 8: Ethernet vorhanden, Option 1 oder 2?
2. Pin 7: K-Line-Ruhepegel (~12 V)?
3. Jedes CAN-Pinpaar bei 500, 250, 125 und 1000 kbit/s je ~200 ms mithören. Die erste Bitrate mit fehlerfreien Botschaften gewinnt.
4. Viele Fehler trotz Verkehr deuten auf CAN-FD: mit 2 bzw. 5 Mbit/s Datenphase wiederholen.
5. Pin 1 bei 33,3 kbit/s (Single-Wire-CAN).

Ergebnis: Busse mit Bitrate und gesehenen CAN-IDs. Die IDs sind ein Fingerabdruck, an dem sich das Fahrzeug später erkennen lässt.

## Was evsoc dafür schon kann

- Verbindungsmodell: Bus pro Profilschritt, Fähigkeiten aller Adaptertypen, Prüfung (`evsoc/connection.py`)
- Box-Ansteuerung: Bus-Wahl vor jedem Schritt, Bus-Suche (`evsoc/universal.py`)
- simulierte Box mit drei Bussen: `box:mock://leaf`
- `evsoc plan`, `evsoc scan`, Prüfung bei `evsoc read -p`, Tests in `tests/test_connection.py`

## Grenzen

- **Gateways mit Freischaltung** (z. B. Stellantis SGW, Mercedes): Batteriewerte lassen sich oft trotzdem lesen, sonst braucht es eine Freischaltung oder einen Abgriff vor dem Gateway.
- **DoIP-Adressen** vergibt jeder Hersteller anders. CAN-Profile lassen sich nicht automatisch übertragen, außer bei BMW (ENET).
- **Schlafende Steuergeräte** antworten oft nur bei „Bereit“ oder beim Laden ([dauerbetrieb.md](dauerbetrieb.md)).
- **Tesla** braucht immer ein Kabel an den Diagnosestecker.
