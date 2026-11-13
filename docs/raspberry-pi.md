# Raspberry Pi, wired only

A setup without WiFi and without Bluetooth: car, adapter, Pi and network hang on cables only.

```
 OBD socket ──short──► USB OBD adapter ──USB──┐
     or     ──short──► CAN HAT ───────────────┤ Raspberry Pi ──Ethernet cable──► home network / laptop
                                              │ (WiFi + Bluetooth off)              Home Assistant (MQTT)
```

evsoc supports this with **wired-only mode** (`--wired-only` or `EVSOC_WIRED_ONLY=1`). Then:

- USB adapters, CAN interfaces (`can://`) and ENET (`enet://`) are allowed. Wireless addresses (`ble://`, `tcp://`) are refused, and so are serial ports that are not USB devices, since paired Bluetooth adapters disguise themselves as a serial port.
- `evsoc devices` and the interface show only wired adapters, the Bluetooth search is off.
- The interface can be bound to a single network interface: `evsoc gui --host eth0`. It is then reachable only over this cable.

## Connection car ↔ Pi

| Variant | Advantages | Disadvantages |
|---|---|---|
| **USB OBD adapter** (e.g. OBDLink SX/EX, ELM327 USB) | simple, ready-made, all ELM profiles | no CAN FD, no other pins |
| **CAN HAT** (SocketCAN, e.g. with MCP2515 or MCP2518FD) | cheap, fast, true listening (`listen-only`), CAN FD with the MCP2518FD, freely wired (e.g. Leaf EV-CAN on pins 12/13, then `?pins=12,13`) | assemble the cable yourself: pin 6 = CAN high, pin 14 = CAN low, pin 5 = ground |
| **BMW/Mini ENET adapter** (cable or WiFi/LAN, e.g. UCSI-3000) | fast, no CAN board needed; `evsoc run` finds it by itself; setup over LAN in [test-bmw-i4.md](test-bmw-i4.md) | activates Ethernet in the car through pin 8: fine for testing, **do not leave it plugged in permanently** (it can keep the car from falling asleep); no 12 V measurement |
| **evsoc box over USB** | switches pins and bus by itself, CAN and CAN FD | self-built; firmware 0.1 tested in the simulator only, not on hardware yet ([box-build-guide.md](box-build-guide.md)) |

**Keep the CAN line short.** At 500 kbit/s the stub from the vehicle bus to the adapter should be only a few decimetres long. So the Pi or the adapter goes **into the car, close to the OBD socket**. The long run to the house goes over Ethernet.

## Connection Pi ↔ network

- **Ethernet** reaches up to 100 m and is galvanically isolated by the transformers in the network sockets. That matters because car and house can have different ground potentials, especially while charging. Long USB or CAN cables between car and house are therefore not a good idea. If it has to be USB, put a USB isolator (galvanic isolation) in between.
- **Plug in a laptop directly:** Ethernet cable laptop ↔ Pi. Both give themselves a 169.254.x.x address, and the Pi can be reached as `raspberrypi.local`. Alternatively a fixed IP.
- **Pi Zero 2 W** has no Ethernet: either use a USB Ethernet adapter or USB gadget mode (`usb0`), then the network runs over a USB cable to the laptop too.

## Power supply

A Raspberry Pi permanently draws much more than a sleeping adapter. Order of magnitude: 150 mA at 12 V is 3.6 Ah per day, which empties a 12 V battery in a few days. Options:

1. **Switched tap:** the Pi only gets power while the car is awake (ignition plus). Check that this tap is also live while charging, otherwise the charging curve is missing.
2. **Power management board** with undervoltage cut-off or time-based shut-off and switching on again when the 12 V voltage rises (the car wakes up).
3. **Garage:** the Pi runs on the house network, and only the USB OBD adapter is in the car. Then definitely use a USB isolator, see above.

In any case use an automotive 12 V → 5 V converter with load dump protection. Unplug it for longer standing.

## Setting up

**1. Switch off radio** in `/boot/firmware/config.txt` (older systems: `/boot/config.txt`):

```
dtoverlay=disable-wifi
dtoverlay=disable-bt
```

**2. CAN HAT** (only for this variant). The line comes from the manufacturer's instructions, examples:

```
dtoverlay=mcp251xfd,spi0-0,interrupt=25                                      # MCP2518FD (CAN FD)
dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25,spimaxfrequency=2000000   # MCP2515
```

[deploy/80-can0.network](../deploy/80-can0.network) (systemd-networkd) brings the interface up at boot. By hand it goes like this:

```bash
sudo ip link set can0 up type can bitrate 500000                 # normal
sudo ip link set can0 up type can bitrate 500000 listen-only on  # listen only
```

**3. Install evsoc as a device:**

```bash
sudo useradd --system --home /opt/evsoc --shell /usr/sbin/nologin evsoc
sudo git clone https://github.com/GreyGoose01/evsoc.git /opt/evsoc
sudo chown -R evsoc: /opt/evsoc
sudo -u evsoc python3 -m venv /opt/evsoc/.venv
sudo -u evsoc /opt/evsoc/.venv/bin/pip install -e "/opt/evsoc[can,mqtt]"
sudo cp /opt/evsoc/deploy/evsoc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now evsoc
journalctl -u evsoc        # shows the setup code
```

The service [deploy/evsoc.service](../deploy/evsoc.service) runs as a user of its own without rights on the rest of the system. It stores configuration and state under `/var/lib/evsoc` and is reachable only over `eth0`.

**4. Set up once** (laptop on the Pi by Ethernet cable): open `http://<IP of eth0>:8080/setup` in the browser.

1. Enter the setup code from `journalctl -u evsoc`, then set a **PIN**.
2. **Adapter:** found automatically (evsoc box first, then USB adapter, then CAN interface, last BMW/Mini over ENET). To fix a particular one, enter e.g. `"adapter": "enet://192.168.16.254"` in `/var/lib/evsoc/config.json`.
3. **Vehicle:** search the model and "test" or "detect automatically". The car must be awake for this. For VW ID., Enyaq, Born, Q4 etc. also enter the net nominal capacity, otherwise the SoH stays empty ([battery-health.md](battery-health.md)).
4. **Outputs:** enter and test MQTT (Home Assistant creates the sensors itself) and/or a webhook.
5. **Save and start.** Done, the device stays in the car.

If nothing is set up, the device works anyway: it finds adapter and vehicle by itself as soon as the car is awake and shows the values. Setup only fixes the vehicle and switches on the outputs. The old address `/einrichtung` still works.

## In operation

| Who | What | Where |
|---|---|---|
| end users | display: state of charge, as of when, state, history, connections; no controls | `http://<Pi>:8080/` |
| other systems | are sent the values (MQTT, webhook) or fetch them | `GET http://<Pi>:8080/api/v1/state` (JSON) |
| the person setting up | change settings (PIN needed), read now (wakes the car) | `http://<Pi>:8080/setup` |

- **Forgot the PIN:** on the Pi `sudo -u evsoc EVSOC_CONFIG=/var/lib/evsoc/config.json /opt/evsoc/.venv/bin/evsoc pin`, then `sudo systemctl restart evsoc`.
- **SD card:** the state is only written on changes (every 15 minutes at the latest), not on every check.
- **Set a fixed IP for eth0**, because the service binds to the address of `eth0` at start.

## Security

- On the bus, as always: read commands only. With the CAN HAT in listen-only mode nothing is sent at all.
- Do not enable 120 Ω termination on the CAN HAT, since the vehicle bus is terminated already. Many boards have a jumper for it.
- The display is unencrypted (HTTP) and readable without login, but reachable only over the cable thanks to `--host eth0`. Everything that changes something needs the PIN (login with a session cookie, protection against foreign web pages and DNS rebinding, a 10 minute lock after 10 failed attempts).
