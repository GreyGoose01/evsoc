# evsoc box firmware

Firmware for the universal adapter from [docs/box-build-guide.md](../docs/box-build-guide.md), way B (NUCLEO-H723ZG + CAN Pal). It speaks the ELM327 command set that evsoc and common OBD programs use, plus the EVS commands from [docs/box-protocol.md](../docs/box-protocol.md). Only read commands leave the box, whatever program is on the USB.

German version: [README.de.md](README.de.md).

## Status (version 0.1, stages 1 and 2)

| Part | Status |
|---|---|
| Core (`core/`): ELM327 commands, ISO-TP with flow control, 11/29 bit, extended addressing (BMW), listening (`ATMA`), read filter, `EVSI`, `EVSBUS`, `EVSLISTEN`, `EVSSCAN` | done; runs in the simulator against evsoc, tested in `tests/test_firmware.py` |
| STM32 port (`port/stm32h7/`): CAN FD, USB CDC, 12 V measurement, silent pin, relays (stage 2) | compiles without warnings against the ST drivers (`stm32h7xx_hal_driver`), **not yet tested on real hardware** |
| K-line, single-wire CAN, Ethernet/DoIP (stages 3–4) | missing |
| Multi-frame **requests** (over 7 bytes) | missing, not needed for read commands (`ERR TOO LONG`) |

## Trying it without hardware

```bash
make -C firmware                          # builds the simulator (needs only a C compiler)
firmware/evsoc-box-sim bmw-i3             # prints the port, e.g. /dev/pts/3
evsoc read -a box:/dev/pts/3 -p evsoc_bmw_sme --all
```

Test vehicles in the simulator: `corsa-e`, `bmw-i3` (extended addressing, multi-frame answers), `id4` (29 bit, gateway with fixed flow control), `leaf` (listening only on pins 12/13). The simulator continues multi-frame answers only after correct flow control and aborts if the box sends in listen mode.

## Structure

```
core/hal.h        interface to the hardware (8 functions)
core/box.c        commands, ISO-TP, filter, EVS commands; platform independent
port/stm32h7/     port to the STM32H723 with ST HAL (FDCAN, USB CDC, ADC, GPIO)
sim/sim.c         the same interface on the PC: pseudo terminal + simulated control units
```

## Putting it on the NUCLEO-H723ZG

1. Install **STM32CubeIDE**, create a new project for the board NUCLEO-H723ZG (do not initialise the peripherals with default values).
2. In the configuration (`.ioc`) set:

   | Block | Setting |
   |---|---|
   | FDCAN1 | enabled, pins PD0 (RX) and PD1 (TX); clock source such that the FDCAN clock is **80 MHz** (e.g. PLL1Q). The firmware sets the bit timings itself. |
   | USB_OTG_HS | "Device only", internal full-speed PHY; middleware USB_DEVICE, class "Communication Device Class" |
   | ADC1 | one channel on the pin with the voltage divider (e.g. A0), resolution 16 bit |
   | GPIO | output with user label `SILENT1` (to SLNT of the CAN Pal), initial value **high** |
   | Stage 2 | additionally FDCAN2 (message RAM offset 1280 so that the two channels do not overlap), outputs `SILENT2`, `REL_12_13`, `REL_3_11` (initial value low) and the symbol `EVSOC_STAGE2` under *Preprocessor* |

3. Let it generate the code. Then add the folders `firmware/core` and `firmware/port/stm32h7` to the project (as linked source folders) and add to the `USER CODE` sections in three places:

   ```c
   /* usbd_cdc_if.c, in CDC_Receive_HS() before USBD_CDC_ReceivePacket(): */
   evsoc_usb_received(Buf, *Len);

   /* main.c, after the MX_..._Init() calls: */
   evsoc_start();

   /* main.c, in the while(1) loop: */
   evsoc_poll();
   ```

   Declare the three functions in `main.h` with `void evsoc_usb_received(const uint8_t *, uint32_t); void evsoc_start(void); void evsoc_poll(void);`.

4. Build and flash through the ST-LINK socket. Afterwards connect the board through the **microcontroller's USB socket** to the computer or Pi. It appears as `/dev/ttyACM0` (Linux) or `/dev/cu.usbmodem…` (Mac).

## First test

```bash
evsoc read -a box:/dev/ttyACM0 --log box.txt    # without a car: must recognise "EVSOC-BOX 0.1", then NO DATA
```

On the car, listen first (sends nothing), then read:

```bash
evsoc scan -a box:/dev/ttyACM0
evsoc read -a box:/dev/ttyACM0
```

By hand it works with any serial terminal: `ATZ`, `ATI`, `EVSI`, `ATRV`.

## Limits of version 0.1

- CAN FD data phase with an 80 MHz FDCAN clock: 1 and 2 Mbit/s. For 4 or 5 Mbit/s choose another clock (must be divisible by bitrate × 20).
- `ATSP0` (automatic) tries 11 bit, then 29 bit, each at 500 kbit/s.
- Without `ATCRA` the box accepts answers from 7E8–7EF or identifier+8 (11 bit) and from 18DA F1xx (29 bit), like an ELM327.
