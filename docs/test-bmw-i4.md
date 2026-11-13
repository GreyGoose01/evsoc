# Testing a BMW i4 over ENET (UCSI-3000)

Instructions for an i4 (G26) with the WiFi/LAN ENET adapter UniCarScan UCSI-3000. They apply equally to iX, i5, i7 and iX3 and to any other ENET cable or adapter.

**Goals:**

1. Check whether evsoc reads the state of charge correctly (profile `evsoc_bmw_gen5`, derived from the iX3/i5).
2. Collect raw data to find the SoH. No identifier is known for it on Gen5 yet.

Everything is read only: evsoc sends read commands only (service `22`) and blocks everything else before sending.

## Preparation

- Laptop with evsoc ([quickstart.md](quickstart.md)), macOS or Linux.
- Car: do **not** press the brake, press the start button once. Now the ignition is on and the gateway awake.
  - For longer tests (more than 10–15 minutes) put the car in "ready" (brake + start) or plug in the charging cable so that the 12 V battery does not run flat.
- Plug the UCSI-3000 into the OBD socket (driver side, bottom left in the footwell).
- Connect the laptop to the adapter's WiFi. Name and password are in the enclosed instructions; dealers list "UCSI-3000" or "WIFI_ENET" with the password `12345678`. Alternatively the LAN cable from the adapter to the laptop, network set to "DHCP" or "automatic".
- Best disconnect other networks (second WiFi, Ethernet). The search for the car runs over the default network.

## 1. Find the car

```bash
evsoc devices --enet
```

Expected is a line like `169.254.x.x  VIN WBY…  (broadcast)` or `192.168.x.x  VIN ?  (gateway of the WiFi/LAN adapter)`. Some WiFi adapters pass the connection to the car on at their own address only, so evsoc also tries the gateway address.

If that does not work: take the IP of the car or adapter from its instructions and give it directly, e.g. `-a enet://192.168.16.254`.

## 2. Read the state of charge

Note the state of charge on the instrument cluster beforehand.

```bash
evsoc read -a enet://auto --car "i4" --all --log i4-read.txt
```

Expected: profile `evsoc_bmw_gen5`, state of charge (SoC) roughly as in the cockpit, cell temperatures plausible. The value from `22E5CE` is the BMS state of charge. It can differ by a few percentage points from the displayed one, because BMW leaves a buffer at the bottom and top.

## 2a. Everything in one run (recommended)

```bash
evsoc probe -a enet://auto --car i4 --note soc=54 --log i4-traffic.txt \
  --raw ATSH6F1 ATCEA07 22DD00-22DFFF 22E500-22E5FF 226300-2263FF
```

This tests all BMW profiles completely, compares with the noted state of charge, appends the raw data ranges from step 3 and writes everything into one report. I need the report and a second one at a different charge level for the evaluation. Details: [test-drive.md](test-drive.md).

## 3. Collect raw data for the SoH

```bash
evsoc raw -a enet://auto --hits ATSH6F1 ATCEA07 \
  22DD00-22DFFF 22E500-22E5FF 226300-2263FF | tee i4-sme-1.txt
```

`ATCEA07` selects the battery control unit (SME). The ranges cover about 1000 read commands, which takes one to three minutes over ENET. With `--hits` only identifiers that answer appear.

**Repeat at a different charge level**, e.g. after a drive or a charge, as `i4-sme-2.txt`. Values that change with the charge are state of charge, energy or voltage. Values that stay the same are candidates for capacity and SoH.

## With the Raspberry Pi as a device (UCSI-3000 on a LAN cable)

Recommended: the UCSI-3000 on a **USB LAN adapter**, the built-in `eth0` stays in the home network. Then everything runs over cables, WiFi and Bluetooth stay off, and the display stays on `eth0` as in [raspberry-pi.md](raspberry-pi.md).

```
 i4 OBD ── UCSI-3000 ──LAN── USB LAN adapter ─┐
                                               Raspberry Pi  eth0 ──LAN──► home network (display, Home Assistant)
```

**1. Find the name of the USB LAN adapter.** On Raspberry Pi OS it is usually `enx` plus the MAC address, e.g. `enx00e04c680123`:

```bash
ip -br link        # the line that appears after plugging in
```

In the following, `<usb-lan>` stands for this name.

**2. Set up the port for the adapter.** First see whether the adapter hands out an address (UCSI-3000 plugged in, ignition on):

```bash
ip -4 addr show <usb-lan>
```

If there is an address, the adapter is a DHCP server. So that it does not redirect the Pi's internet, mark the connection as "never default route" (name of the connection with `nmcli con show`):

```bash
sudo nmcli con mod "<connection name>" ipv4.never-default yes && sudo nmcli con up "<connection name>"
```

If there is no address, create a link-local connection (addresses 169.254.x.x, as with the ENET cable):

```bash
sudo nmcli con add type ethernet ifname <usb-lan> con-name enet ipv4.method link-local ipv6.method disabled
sudo nmcli con up enet
```

**3. Check** (ignition on):

```bash
/opt/evsoc/.venv/bin/evsoc devices --enet      # shows address and VIN of the car
```

evsoc searches on all interfaces and tries the gateways of the networks. So normally you do not need to know the address.

If the UCSI-3000 is on the built-in `eth0` instead, the Pi needs WiFi or a USB LAN adapter for home, and the display has to move there: in `/etc/systemd/system/evsoc.service` replace `--host eth0` with the other name, then `sudo systemctl daemon-reload && sudo systemctl restart evsoc`.

**4. Is it running?** `journalctl -u evsoc -f` shows `Adapter found: enet://auto`. If the car is asleep, evsoc reports "no connection" and keeps the last value, because the gateway is then not reachable.

ENET is not meant for continuous operation: the adapter switches on the Ethernet in the car through pin 8 and can thereby keep the car from falling asleep. First observe one night (12 V voltage or messages in the car) or plug the adapter in only when needed. Better for the long term is a CAN board on pins 6/14 ([box-build-guide.md](box-build-guide.md), way A).

## 4. What I need back

- `i4-read.txt`, `i4-sme-1.txt`, `i4-sme-2.txt`
- for each measurement: displayed state of charge, remaining range, odometer
- if known: an SoH from another source (the workshop's BMW battery certificate, ISTA, Aviloo test). With that the right value can be assigned unambiguously.

The VIN is in the files. If you do not want to share it, replace it beforehand.

## Troubleshooting

| Message | Remedy |
|---|---|
| `No BMW found over ENET` | Ignition on? Connected to the adapter's WiFi? Mobile data or second network off? Give the address directly (`enet://<IP>`). |
| `No ENET connection to …:6801` | Adapter not ready yet (wait for the LED) or wrong address. |
| `Gateway reports error 0x00xx` | Control unit not reachable: ignition on, car not in deep sleep. |
| `NRC 0x31 requestOutOfRange` | This identifier does not exist in the control unit. Normal during a range scan. |
| State of charge differs strongly | Send the file `i4-read.txt`; then the formula does not fit the i4. |
