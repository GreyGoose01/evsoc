# BMW i4 über ENET testen (UCSI-3000)

Anleitung für einen i4 (G26) mit dem WLAN/LAN-ENET-Adapter UniCarScan UCSI-3000. Sie gilt genauso für iX, i5, i7 und iX3 und für jedes andere ENET-Kabel bzw. jeden anderen ENET-Adapter.

**Ziele:**

1. Prüfen, ob evsoc den Ladestand richtig liest (Profil `evsoc_bmw_gen5`, abgeleitet vom iX3/i5).
2. Rohdaten sammeln, um den SoH zu finden. Für Gen5 ist noch keine Kennung dafür bekannt.

Alles ist nur lesend: evsoc schickt ausschließlich Lesebefehle (Dienst `22`) und blockiert alles andere vor dem Senden.

## Vorbereitung

- Laptop mit evsoc ([schnellstart.md](schnellstart.md)), macOS oder Linux.
- Auto: Bremse **nicht** treten, Start-Knopf einmal drücken. Jetzt ist die Zündung an und das Gateway wach.
  - Für längere Tests (mehr als 10–15 Minuten) das Auto in „Bereit“ schalten (Bremse + Start) oder Ladekabel anstecken, damit die 12-V-Batterie nicht leer wird.
- UCSI-3000 in die OBD-Buchse stecken (Fahrerseite, unten links im Fußraum).
- Laptop mit dem WLAN des Adapters verbinden. Name und Passwort stehen in der beiliegenden Anleitung; Händler nennen „UCSI-3000“ bzw. „WIFI_ENET“ mit Passwort `12345678`. Alternativ das LAN-Kabel vom Adapter zum Laptop, Netzwerk auf „DHCP“ bzw. „automatisch“.
- Andere Netzwerke am besten trennen (zweites WLAN, Ethernet). Die Suche nach dem Auto läuft über das Standardnetz.

## 1. Auto finden

```bash
evsoc devices --enet
```

Erwartet wird eine Zeile wie `169.254.x.x  VIN WBY…  (Broadcast)` oder `192.168.x.x  VIN ?  (Gateway des WLAN/LAN-Adapters)`. Manche WLAN-Adapter leiten die Verbindung zum Auto nur an ihrer eigenen Adresse weiter, deshalb probiert evsoc auch die Gateway-Adresse.

Klappt das nicht: die IP des Autos bzw. des Adapters aus dessen Anleitung nehmen und direkt angeben, z. B. `-a enet://192.168.16.254`.

## 2. Ladestand lesen

Vorher den Ladestand im Kombiinstrument notieren.

```bash
evsoc read -a enet://auto --car "i4" --all --log i4-read.txt
```

Erwartet: Profil `evsoc_bmw_gen5`, Ladestand (SoC) ungefähr wie im Cockpit, Zelltemperaturen plausibel. Der Wert aus `22E5CE` ist der BMS-Ladestand. Er kann einige Prozentpunkte vom angezeigten abweichen, weil BMW unten und oben einen Puffer lässt.

## 2a. Alles in einem Lauf (empfohlen)

```bash
evsoc probe -a enet://auto --car i4 --notiz soc=54 --log i4-verkehr.txt \
  --raw ATSH6F1 ATCEA07 22DD00-22DFFF 22E500-22E5FF 226300-2263FF
```

Das testet alle BMW-Profile komplett, vergleicht mit dem notierten Ladestand, hängt die Rohdaten-Bereiche aus Schritt 3 an und schreibt alles in einen Bericht. Den Bericht und einen zweiten bei anderem Ladestand brauche ich zum Auswerten. Details: [probelauf.md](probelauf.md).

## 3. Rohdaten fürs SoH sammeln

```bash
evsoc raw -a enet://auto --treffer ATSH6F1 ATCEA07 \
  22DD00-22DFFF 22E500-22E5FF 226300-2263FF | tee i4-sme-1.txt
```

`ATCEA07` wählt das Batteriesteuergerät (SME). Die Bereiche umfassen rund 1000 Lesebefehle, das dauert über ENET etwa ein bis drei Minuten. Mit `--treffer` erscheinen nur Kennungen, die antworten.

**Wiederholen bei einem anderen Ladestand**, z. B. nach einer Fahrt oder Ladung, als `i4-sme-2.txt`. Werte, die sich mit dem Ladestand ändern, sind Ladestand, Energie oder Spannung. Werte, die gleich bleiben, sind Kandidaten für Kapazität und SoH.

## Mit dem Raspberry Pi als Gerät (UCSI-3000 per LAN-Kabel)

Empfohlen: der UCSI-3000 an einem **USB-LAN-Adapter**, das eingebaute `eth0` bleibt im Heimnetz. Dann läuft alles über Kabel, WLAN und Bluetooth bleiben abgeschaltet, und die Anzeige bleibt wie in [raspberry-pi.md](raspberry-pi.md) auf `eth0`.

```
 i4 OBD ── UCSI-3000 ──LAN── USB-LAN-Adapter ─┐
                                               Raspberry Pi  eth0 ──LAN──► Heimnetz (Anzeige, Home Assistant)
```

**1. Namen des USB-LAN-Adapters finden.** Unter Raspberry Pi OS heißt er meist `enx` plus die MAC-Adresse, z. B. `enx00e04c680123`:

```bash
ip -br link        # die Zeile, die nach dem Einstecken dazukommt
```

Im Folgenden steht `<usb-lan>` für diesen Namen.

**2. Den Anschluss für den Adapter einrichten.** Erst nachsehen, ob der Adapter eine Adresse vergibt (UCSI-3000 eingesteckt, Zündung an):

```bash
ip -4 addr show <usb-lan>
```

Steht dort eine Adresse, ist der Adapter DHCP-Server. Damit er dem Pi nicht das Internet umleitet, die Verbindung als „nie Standardroute“ markieren (Name der Verbindung mit `nmcli con show`):

```bash
sudo nmcli con mod "<Name der Verbindung>" ipv4.never-default yes && sudo nmcli con up "<Name der Verbindung>"
```

Steht dort keine Adresse, eine Link-Local-Verbindung anlegen (Adressen 169.254.x.x, wie beim ENET-Kabel):

```bash
sudo nmcli con add type ethernet ifname <usb-lan> con-name enet ipv4.method link-local ipv6.method disabled
sudo nmcli con up enet
```

**3. Prüfen** (Zündung an):

```bash
/opt/evsoc/.venv/bin/evsoc devices --enet      # zeigt Adresse und VIN des Autos
```

evsoc sucht auf allen Schnittstellen und probiert die Gateways der Netze. Die Adresse muss man deshalb normalerweise nicht kennen.

Hängt der UCSI-3000 stattdessen am eingebauten `eth0`, braucht der Pi für zu Hause WLAN oder einen USB-LAN-Adapter, und die Anzeige muss dorthin: in `/etc/systemd/system/evsoc.service` `--host eth0` durch den anderen Namen ersetzen, dann `sudo systemctl daemon-reload && sudo systemctl restart evsoc`.

**4. Läuft es?** `journalctl -u evsoc -f` zeigt `Adapter gefunden: enet://auto`. Schläft das Auto, meldet evsoc „keine Verbindung“ und behält den letzten Wert, denn das Gateway ist dann nicht erreichbar.

Für den Dauerbetrieb ist ENET nicht gedacht: Der Adapter schaltet über Pin 8 das Ethernet im Auto ein und kann damit das Einschlafen verhindern. Erst eine Nacht beobachten (12-V-Spannung bzw. Meldungen im Auto) oder den Adapter nur bei Bedarf stecken. Dauerhaft besser ist eine CAN-Platine an Pin 6/14 ([bauanleitung-box.md](bauanleitung-box.md), Bauweg A).

## 4. Was ich zurück brauche

- `i4-read.txt`, `i4-sme-1.txt`, `i4-sme-2.txt`
- zu jeder Messung: angezeigter Ladestand, Restreichweite, Kilometerstand
- falls bekannt: ein SoH aus anderer Quelle (BMW-Batteriezertifikat der Werkstatt, ISTA, Aviloo-Test). Damit lässt sich der richtige Wert eindeutig zuordnen.

Die VIN steht in den Dateien. Wer sie nicht teilen will, ersetzt sie vorher.

## Fehlersuche

| Meldung | Abhilfe |
|---|---|
| `Kein BMW per ENET gefunden` | Zündung an? Mit dem WLAN des Adapters verbunden? Mobile Daten bzw. zweites Netz aus? Adresse direkt angeben (`enet://<IP>`). |
| `Keine ENET-Verbindung zu …:6801` | Adapter noch nicht bereit (LED abwarten) oder falsche Adresse. |
| `Gateway meldet Fehler 0x00xx` | Steuergerät nicht erreichbar: Zündung an, Auto nicht im Tiefschlaf. |
| `NRC 0x31 requestOutOfRange` | Diese Kennung gibt es im Steuergerät nicht. Beim Bereichsscan normal. |
| Ladestand weicht stark ab | Datei `i4-read.txt` schicken; dann passt die Formel für den i4 nicht. |
