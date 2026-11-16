# Interfaces

evsoc has two interfaces:

| | `evsoc run` (device) | `evsoc gui` (workshop) |
|---|---|---|
| for | the device installed permanently in the car | trying things out, developing, new vehicles |
| Display | only values and connection, no controls | everything: adapter choice, profile choice, raw values |
| Settings | once under `/setup`, PIN protected, stored | for the running session only |
| runs | permanently as a service | when needed |

The device with `evsoc run` is described in [raspberry-pi.md](raspberry-pi.md). The rest of this page covers the workshop interface.

## Workshop interface

```bash
evsoc gui              # in the browser, http://127.0.0.1:8787
evsoc gui --window     # as its own window (Chromium/Chrome, otherwise the default browser)
```

The interface runs locally on your computer, without internet and without extra packages. It covers all commands, the terminal is not needed.

When you close the tab or window, evsoc quits a few seconds later, but not while continuous operation (`evsoc monitor`) or a test is running. `--keep-running` keeps it running, `--no-browser` does not open a page (and does not quit by itself).

### Starting without a terminal (Linux)

```bash
evsoc desktop          # once: adds evsoc to the application menu
evsoc desktop --remove
```

Afterwards "evsoc" is in the application menu (GNOME, KDE, Xfce …). The entry starts `evsoc gui --window`. With Chromium, Chrome, Brave, Edge or Vivaldi a window of its own without an address bar opens, otherwise a tab in the default browser. evsoc quits by itself a few seconds after the window is closed, unless continuous operation or a test is running.

For USB adapters your user must be allowed to access the serial port: `sudo usermod -aG dialout $USER`, then log out and in again.

### Layout

The sections are on the left, the status (adapter, profile, running work) at the top right. The button at the bottom left switches between light and dark. A button switches between English and German.

| Section | What it does |
|---|---|
| **Connection** | found USB, CAN and Bluetooth adapters, examples, test vehicles and the simulated evsoc box. After connecting it shows what the adapter can do (bus types, pins, listening). "Search buses" shows all active buses at the socket with the evsoc box. |
| **Vehicle** | search a model. One click shows the profile with its **OBD type** (bus, pins, bitrate) and which adapters fit, also whether **your** connected adapter fits. |
| **State of charge** | "Read" with the chosen profile, "Detect automatically" without a choice. All values, history, repeated reading every 10 seconds. The nominal capacity is only needed for the SoH on VW MEB ([battery-health.md](battery-health.md)). |
| **Test drive** | `evsoc probe` at the push of a button: enter the values read off, start. The result shows every value of each profile with "fits" or "differs from". Profiles with an identical result are merged. Reports end up in `~/evsoc-reports` and can be opened later without the car and re-evaluated ([test-drive.md](test-drive.md)). |
| **Control units & faults** | identification and fault memory of the control units from the last test drive. Read only, clearing is blocked. |
| **Tools** | single read commands and ranges (`evsoc raw`); listen in on other apps through a Y cable or evaluate a capture (`evsoc sniff`, [listening-in.md](listening-in.md)). |
| **Continuous operation** | `evsoc monitor` at the push of a button: intervals, wake threshold and optional waking, plus "Read now (wakes the car)" and the wake test ([continuous-operation.md](continuous-operation.md)). |
| **Log** | what is happening right now, including error messages |

To try it without a car: under Connection choose "Test vehicle corsa-e", connect, then open "Test drive", enter 80 for the state of charge and start. For the box: connect "Simulated evsoc box: leaf", search "Leaf ZE0" under Vehicle, click `evsoc_nissan_leaf_evcan` and press "Read with this profile".

Test drive and listening in run in the background, the page shows the progress. Meanwhile connecting, reading and continuous operation are locked so that nothing gets in the way.

### Wired only (Raspberry Pi)

```bash
evsoc --wired-only gui --host eth0
```

Shows only wired adapters (USB, CAN, ENET), hides the Bluetooth search and refuses wireless addresses. With `--host eth0` the interface is reachable only over the Ethernet cable, and only with the link key. With `--token` or `EVSOC_GUI_TOKEN` the key stays the same across restarts. More in [raspberry-pi.md](raspberry-pi.md).

### From a phone (home network)

```bash
evsoc gui --host 0.0.0.0
```

The terminal shows a link with an access key (`…/?token=…`). The page can be opened only with this link. It is meant for example for a Raspberry Pi with `evsoc monitor` that you look at from the phone on the WiFi.

Caution: the connection is unencrypted (HTTP). Use it only in your own network, do not expose it to the internet. For access from outside, Home Assistant through `--mqtt` is the better choice.

### Security

- By default reachable only on this computer (127.0.0.1 and ::1).
- Every request to the interface needs a session key that is embedded in the page. Foreign web pages in the browser therefore cannot access the interface.
- The host name is checked, which prevents so-called DNS rebinding.
- For the car the same applies as everywhere in evsoc: read commands only.

### Interface (API)

The interface uses a small JSON API that scripts can use as well (header `X-Evsoc-Token`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/info` | version, number of profiles and makes |
| GET | `/api/devices`, `/api/devices/ble` | list adapters |
| GET | `/api/models?q=` | vehicle search |
| GET | `/api/plan?profile=` or `?car=` | OBD type and matching adapters |
| GET | `/api/status` | connection, last value, history, continuous operation, log |
| GET | `/api/job`, `/api/probe`, `/api/probe/report`, `/api/reports` | background work, test drive results and reports |
| POST | `/api/connect` `{"url": …}`, `/api/disconnect` | connect/disconnect an adapter |
| POST | `/api/read` `{"profile"\|"car", "all", "battery_kwh"}` | read the state of charge |
| POST | `/api/monitor/start` `{…}`, `/api/monitor/stop`, `/api/monitor/wake` | continuous operation |
| POST | `/api/probe/start`, `/api/waketest/start`, `/api/sniff/start`, `/api/raw`, `/api/busscan` | test drive, wake test, listening in, raw commands, bus search |
