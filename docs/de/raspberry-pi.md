# Raspberry Pi, nur über Kabel

Aufbau ohne WLAN und ohne Bluetooth: Auto, Adapter, Pi und Netzwerk hängen ausschließlich an Kabeln.

```
 OBD-Buchse ──kurz──► USB-OBD-Adapter ──USB──┐
     oder   ──kurz──► CAN-Aufsteckplatine ───┤ Raspberry Pi ──Ethernet-Kabel──► Heimnetz / Laptop
                                             │ (WLAN + Bluetooth abgeschaltet)    Home Assistant (MQTT)
```

evsoc unterstützt das mit dem **Nur-Kabel-Modus** (`--nur-kabel` oder `EVSOC_NUR_KABEL=1`). Dann gilt:

- Erlaubt sind USB-Adapter, CAN-Schnittstellen (`can://`) und ENET (`enet://`). Funk-Adressen (`ble://`, `tcp://`) lehnt evsoc ab, ebenso serielle Ports, die kein USB-Gerät sind. Gekoppelte Bluetooth-Adapter tarnen sich nämlich als serieller Port.
- `evsoc devices` und die Oberfläche zeigen nur Kabel-Adapter, die Bluetooth-Suche ist aus.
- Die Oberfläche lässt sich an eine einzige Netzwerkschnittstelle binden: `evsoc gui --host eth0`. Damit ist sie nur über dieses Kabel erreichbar.

## Verbindung Auto ↔ Pi

| Variante | Vorteile | Nachteile |
|---|---|---|
| **USB-OBD-Adapter** (z. B. OBDLink SX/EX, ELM327 USB) | einfach, fertig, alle ELM-Profile | kein CAN-FD, keine anderen Pins |
| **CAN-Aufsteckplatine** (SocketCAN, z. B. mit MCP2515 oder MCP2518FD) | günstig, schnell, echtes Mithören (`listen-only`), mit MCP2518FD auch CAN-FD, frei verdrahtbar (z. B. Leaf-EV-CAN an Pin 12/13, dann `?pins=12,13`) | Kabel selbst konfektionieren: Pin 6 = CAN-High, Pin 14 = CAN-Low, Pin 5 = Masse |
| **BMW/Mini-ENET-Adapter** (Kabel oder WLAN/LAN, z. B. UCSI-3000) | schnell, ohne CAN-Platine; `evsoc run` findet ihn selbst; Einrichtung per LAN in [test-bmw-i4.md](test-bmw-i4.md) | aktiviert über Pin 8 das Ethernet im Auto: zum Testen gut, **nicht dauerhaft stecken lassen** (kann das Einschlafen verhindern); keine 12-V-Messung |
| **evsoc-Box per USB** | schaltet Pins und Bus selbst um, CAN und CAN-FD | Eigenbau; Firmware 0.1 nur im Simulator getestet, auf Hardware noch nicht ([bauanleitung-box.md](bauanleitung-box.md)) |

**Die CAN-Leitung kurz halten.** Der Abzweig vom Fahrzeugbus zum Adapter sollte bei 500 kbit/s nur wenige Dezimeter lang sein. Also kommt der Pi bzw. der Adapter **ins Auto, nahe an die OBD-Buchse**. Die lange Strecke zum Haus läuft über Ethernet.

## Verbindung Pi ↔ Netz

- **Ethernet** reicht bis 100 m und ist durch die Übertrager in den Netzwerkbuchsen galvanisch getrennt. Das ist wichtig, weil Auto und Haus unterschiedliches Massepotential haben können, besonders während des Ladens. Lange USB- oder CAN-Kabel zwischen Auto und Haus sind deshalb keine gute Idee. Falls es doch USB sein muss, einen USB-Isolator (galvanische Trennung) dazwischen setzen.
- **Laptop direkt anstecken:** Ethernet-Kabel Laptop ↔ Pi. Beide vergeben sich eine 169.254.x.x-Adresse, der Pi ist dann als `raspberrypi.local` erreichbar. Alternativ eine feste IP.
- **Pi Zero 2 W** hat kein Ethernet: entweder einen USB-Ethernet-Adapter nehmen oder den USB-Gadget-Modus (`usb0`), dann läuft auch das Netzwerk über ein USB-Kabel zum Laptop.

## Stromversorgung

Ein Raspberry Pi zieht dauerhaft deutlich mehr als ein schlafender Adapter. Größenordnung: 150 mA bei 12 V sind 3,6 Ah pro Tag, das leert eine 12-V-Batterie in wenigen Tagen. Möglichkeiten:

1. **Geschalteter Abgriff:** Der Pi bekommt nur Strom, wenn das Auto wach ist (Zündungsplus). Prüfen, ob dieser Abgriff auch beim Laden Strom hat, sonst fehlt der Ladeverlauf.
2. **Power-Management-Platine** mit Unterspannungsabschaltung bzw. Abschaltung nach Zeit und Wiedereinschalten, wenn die 12-V-Spannung steigt (Auto wacht auf).
3. **Garage:** Der Pi läuft am Hausnetz, und nur der USB-OBD-Adapter steckt im Auto. Dann unbedingt mit USB-Isolator, siehe oben.

In jedem Fall einen kfz-tauglichen 12-V→5-V-Wandler mit Schutz gegen Lastabwurf verwenden. Bei längerer Standzeit abziehen.

## Einrichten

**1. Funk abschalten** in `/boot/firmware/config.txt` (ältere Systeme: `/boot/config.txt`):

```
dtoverlay=disable-wifi
dtoverlay=disable-bt
```

**2. CAN-Aufsteckplatine** (nur bei dieser Variante). Die Zeile kommt aus der Anleitung des Herstellers, Beispiele:

```
dtoverlay=mcp251xfd,spi0-0,interrupt=25                                      # MCP2518FD (CAN-FD)
dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25,spimaxfrequency=2000000   # MCP2515
```

Die Schnittstelle beim Start einrichten lässt [deploy/80-can0.network](../../deploy/80-can0.network) (systemd-networkd). Von Hand geht es so:

```bash
sudo ip link set can0 up type can bitrate 500000                 # normal
sudo ip link set can0 up type can bitrate 500000 listen-only on  # nur mithören
```

**3. evsoc als Gerät installieren:**

```bash
sudo useradd --system --home /opt/evsoc --shell /usr/sbin/nologin evsoc
sudo git clone https://github.com/GreyGoose01/evsoc.git /opt/evsoc
sudo chown -R evsoc: /opt/evsoc
sudo -u evsoc python3 -m venv /opt/evsoc/.venv
sudo -u evsoc /opt/evsoc/.venv/bin/pip install -e "/opt/evsoc[can,mqtt]"
sudo cp /opt/evsoc/deploy/evsoc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now evsoc
journalctl -u evsoc        # zeigt den Einrichtungscode
```

Der Dienst [deploy/evsoc.service](../../deploy/evsoc.service) läuft als eigener Benutzer ohne Rechte am restlichen System. Er speichert Konfiguration und Status unter `/var/lib/evsoc` und ist nur über `eth0` erreichbar.

**4. Einmal einrichten** (Laptop per Ethernet-Kabel am Pi): Im Browser `http://<IP von eth0>:8080/einrichtung` öffnen.

1. Einrichtungscode aus `journalctl -u evsoc` eingeben, dann eine **PIN** festlegen.
2. **Adapter:** wird automatisch gefunden (evsoc-Box zuerst, dann USB-Adapter, dann CAN-Schnittstelle, zuletzt BMW/Mini über ENET). Soll es fest ein bestimmter sein, in `/var/lib/evsoc/config.json` z. B. `"adapter": "enet://192.168.16.254"` eintragen.
3. **Fahrzeug:** Modell suchen und „testen“ oder „automatisch erkennen“. Das Auto muss dafür wach sein. Bei VW ID., Enyaq, Born, Q4 usw. zusätzlich die Nennkapazität netto eintragen, sonst bleibt der SoH leer ([batteriegesundheit.md](batteriegesundheit.md)).
4. **Weitergabe:** MQTT (Home Assistant legt die Sensoren selbst an) und/oder Webhook eintragen und testen.
5. **Speichern und starten.** Fertig, das Gerät bleibt im Auto.

Wird gar nichts eingerichtet, arbeitet das Gerät trotzdem: Es sucht Adapter und Fahrzeug selbst, sobald das Auto wach ist, und zeigt die Werte an. Die Einrichtung legt das Fahrzeug nur fest und schaltet die Weitergabe ein.

## Im Betrieb

| Wer | Was | Wo |
|---|---|---|
| Endnutzer | Anzeige: Ladestand, Stand von wann, Zustand, Verlauf, Verbindungen; keine Bedienelemente | `http://<Pi>:8080/` |
| andere Systeme | bekommen die Werte geschickt (MQTT, Webhook) oder holen sie ab | `GET http://<Pi>:8080/api/v1/state` (JSON) |
| Einrichter | Einstellungen ändern (PIN nötig) | `http://<Pi>:8080/einrichtung` |

- **PIN vergessen:** am Pi `sudo -u evsoc EVSOC_CONFIG=/var/lib/evsoc/config.json /opt/evsoc/.venv/bin/evsoc pin`, dann `sudo systemctl restart evsoc`.
- **SD-Karte:** Der Status wird nur bei Änderungen geschrieben (spätestens alle 15 Minuten), nicht bei jeder Prüfung.
- **Feste IP für eth0** einrichten, denn der Dienst bindet sich beim Start an die Adresse von `eth0`.

## Sicherheit

- Auf dem Bus gilt wie immer: nur Lesebefehle. Bei der CAN-Platine im Listen-only-Modus wird gar nichts gesendet.
- Keine 120-Ω-Terminierung auf der CAN-Platine aktivieren, denn der Fahrzeugbus ist schon terminiert. Viele Platinen haben dafür einen Jumper.
- Die Anzeige ist unverschlüsselt (HTTP) und ohne Anmeldung lesbar, aber durch `--host eth0` nur über das Kabel erreichbar. Alles, was etwas ändert, braucht die PIN (Anmeldung mit Sitzungs-Cookie, Schutz gegen fremde Webseiten und DNS-Rebinding, nach 10 Fehlversuchen 10 Minuten Sperre).
