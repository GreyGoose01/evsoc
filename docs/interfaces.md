# Interfaces

evsoc has two interfaces:

| | `evsoc run` (device) | `evsoc gui` (workshop) |
|---|---|---|
| for | the installed device in the car | trying things, developing, new vehicles |
| display | values and connection only, no controls | everything: adapter choice, profile choice, raw values |
| settings | once under `/setup`, PIN protected, stored | for the running session only |
| runs | permanently as a service | on demand |

The device with `evsoc run` is described in [raspberry-pi.md](raspberry-pi.md). The rest of this page covers the workshop interface.

## Workshop interface

```bash
evsoc gui              # in the browser, http://127.0.0.1:8787
evsoc gui --window     # as a window of its own (Chromium/Chrome, else the default browser)
```

The interface runs locally on your computer, without internet and without extra packages. It covers all commands, so the terminal is not needed.

### Starting without a terminal (Linux)

```bash
evsoc desktop          # once: adds evsoc to the application menu
evsoc desktop --remove
```

Afterwards "evsoc" is in the application menu (GNOME, KDE, Xfce …). The entry starts `evsoc gui --window`. With Chromium, Chrome, Brave, Edge or Vivaldi a window of its own opens without an address bar, otherwise a tab in the default browser. evsoc quits by itself when the window has been closed for three minutes and nothing is running.

For USB adapters your user must be allowed to use the serial port: `sudo usermod -aG dialout $USER`, then log out and in.

### Layout

The sections are on the left, the state (adapter, profile, running work) is at the top right. The button at the bottom left switches light and dark; next to it is the language switch (English/German, following the browser by default).

| Section | What it does |
|---|---|
| **Connection** | found USB, CAN and Bluetooth adapters, examples, test vehicles and the simulated evsoc box. After connecting it shows what the adapter can do (bus types, pins, listening). "Search buses" shows all active buses at the socket with the evsoc box. |
| **Vehicle** | search a model. A click shows the profile with its **OBD type** (bus, pins, bitrate) and which adapters fit, also whether **your** connected adapter fits. |
| **State of charge** | "Read" with the chosen profile, "Detect automatically" without a choice. All values, history, repeated reading every 10 seconds. Only the SoH on VW MEB needs the nominal capacity ([battery-health.md](battery-health.md)). |
| **Test drive** | `evsoc probe` by button: enter values read off the car, start. The result shows every value per profile with "matches" or "differs from". Profiles with an identical result are grouped. Reports are saved in `~/evsoc-reports` and can be reopened and re-evaluated later without the car ([test-drive.md](test-drive.md)). |
| **Control units & faults** | identification and fault memory of the control units from the last test drive. Read only, clearing is blocked. |
| **Tools** | single read commands and ranges (`evsoc raw`); listen in on other apps through a Y cable or evaluate a capture (`evsoc sniff`, [listening-in.md](listening-in.md)), optionally with a reference adapter. |
| **Continuous operation** | `evsoc monitor` at the press of a button: intervals, wake threshold and optional waking, plus "Read now (wakes the car)" and the wake test ([continuous-operation.md](continuous-operation.md)). |
| **Log** | what is going on right now, including error messages |

To try it without a car: under Connection choose "Test vehicle corsa-e", connect, open "Test drive", enter 80 as state of charge and start. For the box: connect "Simulated evsoc box: leaf", search "Leaf ZE0" under Vehicle, click `evsoc_nissan_leaf_evcan` and press "Read with this profile".

Test drive and listening run in the background and the page shows progress. While they run, connecting, reading and continuous operation are locked so that nothing gets in the way.

### Wired only (Raspberry Pi)

```bash
evsoc --wired-only gui --host eth0
```

Shows only wired adapters (USB, CAN, ENET), hides the Bluetooth search and refuses wireless addresses. With `--host eth0` the interface is reachable only over the Ethernet cable, and only with the link key. With `--token` or `EVSOC_GUI_TOKEN` the key stays the same across restarts. More in [raspberry-pi.md](raspberry-pi.md).

### From a phone (home network)

```bash
evsoc gui --host 0.0.0.0
```

The terminal shows a link with an access key (`…/?token=…`). The page can only be opened with this link. This is meant, for example, for a Raspberry Pi running `evsoc monitor` that you look at from your phone on the WiFi.

Note: the connection is unencrypted (HTTP). Use it only on your own network, do not expose it to the internet. For access from anywhere, Home Assistant through `--mqtt` is the better choice.

### Security

- Reachable only on this computer by default (127.0.0.1 and ::1).
- Every request to the API needs a session key embedded in the page. Foreign web pages in the browser therefore cannot reach the interface.
- The host name is checked, which prevents so-called DNS rebinding.
- For the car the same holds as everywhere in evsoc: read commands only.

### API

The interface uses a small JSON API that scripts can use too (header `X-Evsoc-Token`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/info` | version, number of profiles and makes |
| GET | `/api/devices`, `/api/devices/ble` | list adapters |
| GET | `/api/models?q=` | vehicle search |
| GET | `/api/plan?profile=` or `?car=` | OBD type and fitting adapters |
| GET | `/api/status` | connection, last value, history, continuous operation, log |
| POST | `/api/connect` `{"url": …}`, `/api/disconnect` | connect/disconnect an adapter |
| POST | `/api/read` `{"profile"\|"car", "all", "battery_kwh"}` | read the state of charge |
| POST | `/api/monitor/start` `{…}`, `/api/monitor/stop`, `/api/monitor/wake` | continuous operation, read now |
| POST | `/api/probe/start`, `/api/probe/load`; GET `/api/probe`, `/api/job`, `/api/reports` | test drive and its reports |
| POST | `/api/raw`, `/api/busscan`, `/api/waketest/start`, `/api/sniff/start`, `/api/sniff/analyze` | tools |
