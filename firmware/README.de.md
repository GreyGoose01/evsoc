# Firmware der evsoc-Box

Firmware für den Universal-Adapter aus [docs/de/bauanleitung-box.md](../docs/de/bauanleitung-box.md), Bauweg B (NUCLEO-H723ZG + CAN Pal). Sie spricht den ELM327-Befehlssatz, den evsoc und übliche OBD-Programme nutzen, plus die EVS-Befehle aus [docs/de/box-protokoll.md](../docs/de/box-protokoll.md). Es verlassen nur Lesebefehle die Box, egal welches Programm am USB hängt.

## Stand (Version 0.1, Stufe 1 und 2)

| Teil | Stand |
|---|---|
| Kern (`core/`): ELM327-Befehle, ISO-TP mit Flusssteuerung, 11/29 Bit, erweiterte Adressierung (BMW), Mithören (`ATMA`), Lese-Filter, `EVSI`, `EVSBUS`, `EVSLISTEN`, `EVSSCAN` | fertig; läuft im Simulator gegen evsoc, getestet in `tests/test_firmware.py` |
| STM32-Anbindung (`port/stm32h7/`): CAN-FD, USB-CDC, 12-V-Messung, Silent-Pin, Relais (Stufe 2) | kompiliert ohne Warnungen gegen die ST-Treiber (`stm32h7xx_hal_driver`), **noch nicht auf echter Hardware getestet** |
| K-Line, Single-Wire-CAN, Ethernet/DoIP (Stufe 3–4) | fehlt |
| Mehrteilige **Anfragen** (über 7 Bytes) | fehlt, für Lesebefehle nicht nötig (`ERR TOO LONG`) |

## Ohne Hardware ausprobieren

```bash
make -C firmware                          # baut den Simulator (braucht nur einen C-Compiler)
firmware/evsoc-box-sim bmw-i3             # gibt den Port aus, z. B. /dev/pts/3
evsoc read -a box:/dev/pts/3 -p evsoc_bmw_sme --all
```

Testfahrzeuge im Simulator: `corsa-e`, `bmw-i3` (erweiterte Adressierung, mehrteilige Antworten), `id4` (29 Bit, Gateway mit fester Flusssteuerung), `leaf` (nur Mithören auf Pins 12/13). Der Simulator setzt mehrteilige Antworten nur nach korrekter Flusssteuerung fort und bricht ab, wenn die Box im Mithörmodus sendet.

## Aufbau

```
core/hal.h        Schnittstelle zur Hardware (8 Funktionen)
core/box.c        Befehle, ISO-TP, Filter, EVS-Befehle; plattformunabhängig
port/stm32h7/     Anbindung an STM32H723 mit ST-HAL (FDCAN, USB CDC, ADC, GPIO)
sim/sim.c         dieselbe Schnittstelle auf dem PC: Pseudo-Terminal + simulierte Steuergeräte
```

## Auf das NUCLEO-H723ZG bringen

1. **STM32CubeIDE** installieren, neues Projekt für das Board NUCLEO-H723ZG anlegen (Peripherie nicht mit Standardwerten initialisieren).
2. In der Konfiguration (`.ioc`) einstellen:

   | Block | Einstellung |
   |---|---|
   | FDCAN1 | aktiviert, Pins PD0 (RX) und PD1 (TX); Taktquelle so, dass der FDCAN-Takt **80 MHz** ist (z. B. PLL1Q). Die Bit-Zeiten setzt die Firmware selbst. |
   | USB_OTG_HS | „Device only“, interner Full-Speed-PHY; Middleware USB_DEVICE, Klasse „Communication Device Class“ |
   | ADC1 | ein Kanal an dem Pin mit dem Spannungsteiler (z. B. A0), Auflösung 16 Bit |
   | GPIO | Ausgang mit Benutzerbezeichnung `SILENT1` (an SLNT des CAN Pal), Startwert **High** |
   | Stufe 2 | zusätzlich FDCAN2 (Message-RAM-Offset 1280, damit sich die beiden Kanäle nicht überlappen), Ausgänge `SILENT2`, `REL_12_13`, `REL_3_11` (Startwert Low) und das Symbol `EVSOC_STAGE2` unter *Preprocessor* |

3. Code erzeugen lassen. Dann die Ordner `firmware/core` und `firmware/port/stm32h7` ins Projekt aufnehmen (als verlinkte Quellordner) und an drei Stellen in den `USER CODE`-Abschnitten ergänzen:

   ```c
   /* usbd_cdc_if.c, in CDC_Receive_HS() vor USBD_CDC_ReceivePacket(): */
   evsoc_usb_received(Buf, *Len);

   /* main.c, nach den MX_..._Init()-Aufrufen: */
   evsoc_start();

   /* main.c, in der while(1)-Schleife: */
   evsoc_poll();
   ```

   Die drei Funktionen mit `void evsoc_usb_received(const uint8_t *, uint32_t); void evsoc_start(void); void evsoc_poll(void);` in `main.h` bekannt machen.

4. Bauen und über die ST-LINK-Buchse flashen. Danach das Board über die **USB-Buchse des Mikrocontrollers** an den Rechner bzw. Pi. Es erscheint als `/dev/ttyACM0` (Linux) oder `/dev/cu.usbmodem…` (Mac).

## Erster Test

```bash
evsoc read -a box:/dev/ttyACM0 --log box.txt    # ohne Auto: muss "EVSOC-BOX 0.1" erkennen, dann NO DATA
```

Am Auto zuerst mithören (sendet nichts), dann lesen:

```bash
evsoc scan -a box:/dev/ttyACM0
evsoc read -a box:/dev/ttyACM0
```

Von Hand geht es mit jedem seriellen Terminal: `ATZ`, `ATI`, `EVSI`, `ATRV`.

## Grenzen der Version 0.1

- CAN-FD-Datenphase bei 80 MHz FDCAN-Takt: 1 und 2 Mbit/s. Für 4 oder 5 Mbit/s einen anderen Takt wählen (muss durch Bitrate × 20 teilbar sein).
- `ATSP0` (automatisch) probiert 11 Bit, dann 29 Bit, jeweils mit 500 kbit/s.
- Ohne `ATCRA` nimmt die Box Antworten von 7E8–7EF bzw. Kennung+8 an (11 Bit) und von 18DA F1xx (29 Bit), wie ein ELM327.
