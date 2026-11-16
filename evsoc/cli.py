"""evsoc command line: read the state of charge of EVs and PHEVs over OBD."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, enet
from .elm import AdapterError, ElmAdapter
from .profiles import Profile, load_all
from .reader import Reading, autodetect, read, run_init
from .safety import SafetyError
from .transports import BleTransport, LoggingTransport, SerialTransport, TcpTransport, TransportError
from .vehicles import norm

LABELS = {
    "soc": "State of charge (SoC)",
    "soc_display": "State of charge (display)",
    "soc_bms": "State of charge (BMS)",
    "soc_uds": "State of charge (UDS)",
    "soc_display_max": "Display 100 % at",
    "soc_display_min": "Display 0 % at",
    "soh": "Health (SoH)",
    "soce": "Certified energy level",
    "voltage": "Voltage",
    "current": "Current",
    "power": "Power",
    "capacity": "Capacity",
    "cell_capacity_min": "Cell capacity min",
    "cell_capacity_avg": "Cell capacity mean",
    "cell_capacity_max": "Cell capacity max",
    "energy_available": "Energy available",
    "range": "Range",
    "batt_temp": "Battery temperature",
    "batt_temp_max": "Battery temp. max",
    "batt_temp_min": "Battery temp. min",
    "cell_min_voltage": "Cell min",
    "cell_max_voltage": "Cell max",
    "ext_temp": "Outside temperature",
    "odometer": "Odometer",
    "is_charging": "Charging",
    "plugged_in": "Plugged in",
}

ADAPTER_HELP = """Adapter address (-a):
  /dev/cu.OBDLinkMXPlus          USB or Bluetooth Classic (OBDLink MX+, ELM327 BT)
  serial:///dev/cu.usbserial-1?baud=115200
  tcp://192.168.0.10:35000       WiFi adapter (computer on the adapter's WiFi)
  ble://OBDLink CX               Bluetooth LE (name or address)
  enet://auto | enet://169.254.x.x   BMW/Mini ENET (cable or WiFi adapter like UCSI-3000)
  can://socketcan/can0           raw CAN interface through python-can (also pcan, kvaser,
  can://slcan//dev/cu.usbmodem1?bitrate=500000   gs_usb, vector ...; ?fd=1 for CAN FD,
                                 ?pins=12,13 if the cable taps other OBD pins)
  box:/dev/ttyACM0               evsoc box (universal adapter, USB only), switches pins/bus itself
  mock://corsa-e | mock://bmw-i3 | mock://bmw-ix3 | mock://ioniq5 | mock://id4 | mock://megane
  mock://bz4x | mock://e-c3 | mock://tesla-m3 | mock://hybrid
  box:mock://leaf | box:mock://corsa-e   simulated evsoc box"""


# Wired-only mode (--wired-only or EVSOC_WIRED_ONLY=1): no WiFi or Bluetooth adapters.
WIRED_ONLY = os.environ.get("EVSOC_WIRED_ONLY", os.environ.get("EVSOC_NUR_KABEL")) == "1"


def open_adapter(url: str, log_path: str | None, wired_check: bool = True):
    if WIRED_ONLY and wired_check:
        from .wired import check_url
        check_url(url)
    if url.startswith("enet://"):
        host = url[len("enet://"):]
        if host in ("", "auto"):
            car = enet.find_vehicle()
            if not car:
                raise AdapterError("No BMW found over ENET. Ignition on? Network set to DHCP/automatic? With a WiFi adapter: connected to its WiFi, mobile data off?")
            host, vin, how = car
            print(f"ENET: vehicle {vin} at {host} ({how})")
        return enet.EnetAdapter(host, log_path=log_path)

    if url.startswith("can://"):
        from .canbus import CanAdapter
        rest, _, query = url[len("can://"):].partition("?")
        interface, _, channel = rest.partition("/")
        q = parse_qs(query)
        return CanAdapter(
            interface, channel or "can0",
            bitrate=int(q.get("bitrate", ["500000"])[0]),
            fd=q.get("fd", ["0"])[0] in ("1", "true"),
            pad=int(q.get("pad", ["00"])[0], 16),
            listen_only=q.get("listen_only", ["0"])[0] in ("1", "true"),
            pins=tuple(int(p) for p in q.get("pins", ["6,14"])[0].split(",")),
        )

    box = url.startswith("box:")
    if box:
        url = url[len("box:"):]
    if url.startswith("mock://"):
        from .mock import MockBoxTransport, MockElmTransport
        name = url[len("mock://"):]
        transport = MockBoxTransport(name) if box else MockElmTransport(name)
    elif url.startswith("tcp://"):
        u = urlparse(url)
        transport = TcpTransport(u.hostname or "192.168.0.10", u.port or 35000)
    elif url.startswith("ble://"):
        transport = BleTransport(url[len("ble://"):])
    else:
        u = urlparse(url if "://" in url else f"serial://{url}")
        baud = int(parse_qs(u.query).get("baud", ["38400"])[0])
        transport = SerialTransport(u.path, baud)
    if log_path:
        transport = LoggingTransport(transport, log_path)
    if box:
        from .universal import UniversalAdapter
        adapter = UniversalAdapter(transport)
    else:
        adapter = ElmAdapter(transport)
    adapter.reset()
    return adapter


def fmt(value: float | None, unit: str, name: str) -> str:
    if value is None:
        return "-"
    if name.startswith("cell_capacity_"):
        return f"{value:.2f} {unit}".strip()
    if name.startswith("cell_"):
        return f"{value:.3f} {unit}".strip()
    if name in ("is_charging", "plugged_in"):
        return "yes" if value else "no"
    return f"{value:.1f} {unit}".strip() if abs(value) < 10000 else f"{value:.0f} {unit}".strip()


def print_reading(reading: Reading, profile: Profile, as_json: bool, verbose: bool = False) -> None:
    if as_json:
        print(json.dumps({
            "profile": reading.profile,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "soc": reading.soc,
            "values": {k: v.value for k, v in reading.values.items() if v.plausible},
            "raw": reading.raw,
        }, ensure_ascii=False))
        return
    print(f"\nProfile: {profile.name}   ({profile.description[:90]})")
    if profile.vehicles:
        print(f"  Vehicles: {', '.join(str(v) for v in profile.vehicles[:4])}" + (" ..." if len(profile.vehicles) > 4 else ""))
    hidden = 0
    for name, v in reading.values.items():
        label = LABELS.get(name) or v.label or name
        if name.startswith("soc_") and name not in LABELS and v.label:
            label = f"SoC: {v.label}"
        from .i18n import tr
        label = tr(label)  # padded in the table, so the terminal translation would not find it
        if v.error:
            if not verbose:
                hidden += 1
                continue
            print(f"  {label[:32]:<32} -   ({v.error})")
        else:
            flag = "" if v.plausible else "   (implausible)"
            print(f"  {label[:32]:<32} {fmt(v.value, v.unit, name)}{flag}")
    if hidden:
        print(f"  ({hidden} more values without an answer, details with --all)")


def cmd_profiles(args) -> int:
    profiles = load_all()
    shown = [p for p in profiles.values() if not args.source or p.name.startswith(args.source + "_")]
    for p in shown:
        print(f"{p.name}\n    {p.description[:150]}")
        if args.verbose:
            print(f"    Platform: {p.platform or '-'}   Fields: {', '.join(p.fields)}\n    Source: {p.source} ({p.license})")
    by_source = Counter(p.name.split("_", 1)[0] for p in profiles.values())
    print(f"\n{len(shown)} profiles shown. Total: " + ", ".join(f"{k} {v}" for k, v in sorted(by_source.items())))
    return 0


def models_markdown(profiles: dict[str, Profile]) -> str:
    """Vehicle list for docs/vehicles.md, grouped by make."""
    by_make: dict[str, list[tuple[str, Profile]]] = {}
    for p in profiles.values():
        if p.generic:
            continue
        for v in p.vehicles:
            by_make.setdefault(v.make, []).append((str(v)[len(v.make):].strip(), p))
    sources = Counter(p.name.split("_", 1)[0] for p in profiles.values())
    out = [
        "# Supported vehicles",
        "",
        "Generated with `evsoc models --markdown`. Do not edit by hand.",
        "",
        f"**{len(profiles)} profiles** ({', '.join(f'{k}: {v}' for k, v in sorted(sources.items()))}), "
        f"**{len(by_make)} makes**. In addition, `evsoc_generic_obd` tries the standardised OBD values on every car "
        "(PID 5B, 9A, B2, D2 and UDS F45B/F4B2), which many hybrids and all new US electric cars from 2026/27 provide.",
        "",
        "\"all models\" means: commands that OBDb lists for all models of a make (mostly hybrids).",
        "The Platform column shows shared technology; `evsoc read --car` automatically tries all profiles of the same platform.",
        "",
    ]
    for make in sorted(by_make, key=str.lower):
        out += [f"## {make}", "", "| Model | Platform | Profiles |", "|---|---|---|"]
        rows: dict[str, tuple[str, list[str]]] = {}
        for model, p in by_make[make]:
            plat, names = rows.setdefault(model or "-", (p.platform or "", []))
            names.append(f"`{p.name}`")
        for model in sorted(rows, key=str.lower):
            plat, names = rows[model]
            out.append(f"| {model} | {plat} | {', '.join(sorted(set(names)))} |")
        out.append("")
    return "\n".join(out)


def cmd_models(args) -> int:
    profiles = load_all()
    if args.markdown:
        print(models_markdown(profiles))
        return 0
    query = " ".join(args.query)
    rows = []
    for p in profiles.values():
        if p.generic:
            continue
        if query and not p.matches_text(query):
            continue
        hits = [v for v in p.vehicles if norm(query) in norm(str(v))] if query else p.vehicles
        for v in hits or p.vehicles:  # matched via platform or profile name: show all its cars
            rows.append((v.make.lower(), str(v), p))
    if not rows:
        print(f"Nothing found for {query!r}. Tip: model name only, e.g. 'ioniq' or 'e-208'.")
        print("For unknown cars 'evsoc read' still tries all profiles (scan).")
        return 1
    for _make, label, p in sorted(rows, key=lambda r: (r[0], r[1])):
        print(f"  {label:<60} {p.name:<40} {p.platform or ''}")
    if query:
        platforms = {p.platform for *_x, p in rows if p.platform}
        siblings = {p.name for p in profiles.values() if p.platform in platforms} - {p.name for *_x, p in rows}
        if siblings:
            print(f"\n'read --car {query!r}' also tries profiles of the same platform: {', '.join(sorted(siblings)[:12])}")
    print(f"\n{len(rows)} entries")
    return 0


def cmd_devices(args) -> int:
    from .wired import socketcan_interfaces, usb_serial_ports
    usb = {p["device"] for p in usb_serial_ports()}
    try:
        from serial.tools import list_ports
        print("USB adapters (cable):")
        for port in list_ports.comports():
            if port.device in usb:
                print(f"  {port.device:<35} {port.description}")
        if not WIRED_ONLY:
            print("\nOther serial ports (e.g. paired Bluetooth adapters):")
            for port in list_ports.comports():
                if port.device not in usb:
                    print(f"  {port.device:<35} {port.description}")
    except ImportError:
        print("pyserial missing (pip install pyserial)")
    cans = socketcan_interfaces()
    if cans:
        print("\nCAN interfaces (SocketCAN, e.g. a CAN HAT on the Pi):")
        for name in cans:
            print(f"  can://socketcan/{name}")
    if args.ble and not WIRED_ONLY:
        try:
            import asyncio

            from bleak import BleakScanner
            print("\nBluetooth LE devices (5 s scan):")
            for d in asyncio.run(BleakScanner.discover(timeout=5)):
                print(f"  {d.address:<38} {d.name or ''}")
        except ImportError:
            print("\nbleak missing (pip install bleak)")
    elif args.ble:
        print("\nBluetooth scanning is off in wired-only mode.")
    if args.enet:
        print("\nBMW ENET:")
        car = enet.find_vehicle()
        if car:
            print(f"  {car[0]:<16} VIN {car[1]}  ({car[2]})  ->  -a enet://{car[0]}")
        else:
            print("  nothing found (ignition on? connected to the adapter's network?)")
    return 0


def cmd_read(args) -> int:
    profiles = load_all()
    log = (lambda _m: None) if args.json else print
    adapter = open_adapter(args.adapter, args.log)
    try:
        year = args.year
        if args.profile == "auto":
            det = autodetect(adapter, profiles, vin=args.vin, car=args.car, year=year, log=log)
            if not det:
                print("No profile returned a plausible state of charge. Ignition on? Record with --log and analyse the file (see docs/own-profiles.md).", file=sys.stderr)
                return 1
            profile, year = det.profile, det.year
            log(f"Detected after {det.seconds:.1f} s: {profile.name}  ->  -p {profile.name} saves time next time")
            if det.also_plausible:
                log(f"  also plausible: {', '.join(det.also_plausible[:6])}")
        else:
            if args.profile not in profiles:
                print(f"Unknown profile {args.profile!r}. List: evsoc profiles / evsoc models", file=sys.stderr)
                return 2
            profile = profiles[args.profile]
            from .connection import capabilities_of, check, recommend, soc_problems
            caps = capabilities_of(adapter)
            problems = check(profile, caps, year) if args.all else soc_problems(profile, caps, year)
            if problems:
                ok = [c.name for c, pr in recommend(profile) if not pr]
                car_label = f"{profile.vehicles[0].make} {profile.vehicles[0].model}" if profile.vehicles else profile.name
                print(f"Profile {profile.name} needs a different adapter: {'; '.join(problems)}.\nSuitable: {', '.join(ok) or '-'}  (details: evsoc plan \"{car_label}\")",
                      file=sys.stderr)
                return 2
            run_init(adapter, profile, log)
        names = None if args.all else [f.name for f in profile.soc_fields]
        while True:
            print_reading(read(adapter, profile, names, year, args.battery_kwh), profile, args.json, verbose=args.all)
            if not args.watch:
                return 0
            time.sleep(args.watch)
    finally:
        adapter.close()


def expand_commands(commands: list[str]) -> list[str]:
    """'22DD00-22DDFF' -> 22DD00, 22DD01, ... (same length, read-only requests only)."""
    out = []
    for cmd in commands:
        lo, sep, hi = cmd.upper().partition("-")
        if not sep:
            out.append(cmd)
            continue
        if len(lo) != len(hi) or not (lo + hi).isalnum() or lo.startswith(("AT", "ST")):
            raise ValueError(f"Range {cmd!r}: start and end must have the same length, e.g. 22DD00-22DDFF")
        a, b = int(lo, 16), int(hi, 16)
        if b < a or b - a > 4095:
            raise ValueError(f"Range {cmd!r}: at most 4096 requests")
        out += [f"{v:0{len(lo)}X}" for v in range(a, b + 1)]
    return out


def cmd_raw(args) -> int:
    """Send single read-only requests, e.g. to explore DIDs like apps such as BimmerLink do."""
    profiles = load_all()
    try:
        commands = expand_commands(args.commands)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    adapter = open_adapter(args.adapter, args.log)
    try:
        if args.profile:
            run_init(adapter, profiles[args.profile], print)
        for cmd in commands:
            try:
                if cmd.upper().startswith(("AT", "ST")):
                    adapter.at(cmd)
                    if not args.hits:
                        print(f"{cmd}: OK")
                else:
                    r = adapter.request(cmd)
                    print(f"{cmd}: {r.ecu}  {r.payload.hex(' ').upper()}", flush=True)
            except (AdapterError, SafetyError) as e:
                if not args.hits:
                    print(f"{cmd}: {e}")
    finally:
        adapter.close()
    return 0


def cmd_probe(args) -> int:
    """Test drive: try every candidate profile completely, keep all raw answers, judge afterwards."""
    from . import probe
    profiles = load_all()
    try:
        notes = probe.parse_notes(args.note)
        raw = expand_commands(args.raw or [])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if args.file:
        report = probe.load(args.file, profiles, notes, args.battery_kwh)
        print(probe.summary(report))
        return 0
    if not args.adapter:
        print("Give an adapter (-a …) or evaluate a report (-d report.json).", file=sys.stderr)
        return 2
    adapter = open_adapter(args.adapter, args.log)
    try:
        report = probe.run(adapter, profiles, adapter_url=args.adapter, vin=args.vin, car=args.car, year=args.year,
                           everything=args.all_profiles, raw_commands=raw, notes=notes, battery_kwh=args.battery_kwh,
                           diagnose=not args.no_diagnosis)
    finally:
        adapter.close()
    path = args.output or probe.default_path(report)
    probe.save(report, path)
    print("\n" + probe.summary(report))
    print(f"\nReport: {path}\nThis file holds all raw answers. Re-evaluate later: evsoc probe -d {path}")
    return 0


def cmd_wake(args) -> int:
    """Wake test: does the parked car answer through the OBD socket, and does it go back to sleep?"""
    from . import waketest
    profiles = load_all()
    if args.profile and args.profile not in profiles:
        print(f"Unknown profile {args.profile!r}", file=sys.stderr)
        return 2
    report = waketest.run(lambda: open_adapter(args.adapter, args.log), profiles, adapter_url=args.adapter,
                          profile=profiles.get(args.profile) if args.profile else None, car=args.car,
                          awake_voltage=args.awake_voltage, min_voltage=args.min_voltage,
                          watch_minutes=args.duration, step=args.interval)
    path = args.output or waketest.default_path()
    waketest.save(report, path)
    print("\n" + waketest.summary(report) + f"\n\nReport: {path}")
    return 0 if report["wake"].get("woke") else 1


def cmd_monitor(args) -> int:
    from .monitor import FileSink, Monitor, MqttSink, StdoutSink, WebhookSink, load_state, parse_times
    profiles = load_all()
    if args.profile and args.profile not in profiles:
        print(f"Unknown profile {args.profile!r}", file=sys.stderr)
        return 2
    sinks = [StdoutSink(args.json)]
    if args.state:
        sinks.append(FileSink(args.state))
    if args.mqtt:
        sinks.append(MqttSink(args.mqtt, print))
    if args.webhook:
        sinks.append(WebhookSink(args.webhook, print))
    monitor = Monitor(
        connect=lambda: open_adapter(args.adapter, args.log),
        profiles=profiles,
        sinks=sinks,
        profile=profiles.get(args.profile) if args.profile else None,
        car=args.car,
        year=args.year,
        battery_kwh=args.battery_kwh,
        interval=args.interval,
        sleep_interval=args.sleep_interval,
        awake_voltage=args.awake_voltage,
        wake_every=args.wake_every,
        wake_at=parse_times(args.wake_at),
        min_voltage=args.min_voltage,
        wake_gap=args.wake_gap,
        state=load_state(args.state),
        log=(lambda _m: None) if args.json else print,
    )
    monitor.run(once=args.once)
    return 0


def cmd_plan(args) -> int:
    """Pick the car, get the OBD type: bus, pins, bitrate and which adapters can do it."""
    from .connection import alternatives, buses, capabilities_of, check, recommend
    from .profiles import candidates
    profiles = load_all()
    hits = [p for p in candidates(profiles, car=args.car) if p.matches_text(args.car) and not p.generic]
    if not hits:
        print(f"No profile for {args.car!r}. 'evsoc models' lists all vehicles; for unknown cars 'evsoc read' tries the standard profile (CAN, pins 6/14).")
        return 1
    adapter_caps = None
    if args.adapter:
        adapter = open_adapter(args.adapter, None)
        adapter_caps = capabilities_of(adapter)
        adapter.close()
    for p in hits[: args.limit]:
        vehicles = ", ".join(str(v) for v in p.vehicles if p.matches_text(args.car) and args.car.lower()[:3] in str(v).lower()) \
            or ", ".join(str(v) for v in p.vehicles[:3])
        print(f"\n{p.name}  ({vehicles})")
        for bus in buses(p):
            print(f"  OBD type:  {bus.describe()}")
        for bus in alternatives(p):
            print(f"  or:        {bus.describe()} (BMW ENET)")
        ok = [c.name for c, problems in recommend(p) if not problems]
        print(f"  Adapters:  {', '.join(ok) if ok else 'none of the known adapters'}")
        if adapter_caps is not None:
            problems = check(p, adapter_caps, args.year)
            print(f"  Your adapter ({adapter_caps.name}): " + ("fits" if not problems else "does not fit: " + "; ".join(problems)))
    if len(hits) > args.limit:
        print(f"\n… {len(hits) - args.limit} more profiles (raise --limit)")
    return 0


def cmd_scan(args) -> int:
    """List the buses that are active on the OBD socket (evsoc box, listen-only)."""
    adapter = open_adapter(args.adapter, args.log)
    try:
        if not hasattr(adapter, "scan"):
            if hasattr(adapter, "bus_active"):
                print("CAN-Interface: " + ("traffic on the bus" if adapter.bus_active(2.0) else "no traffic"))
                return 0
            print("Bus scanning needs the evsoc box (box:…). Normal adapters only see pins 6/14.", file=sys.stderr)
            return 2
        found = adapter.scan()
        if not found:
            print("No active buses found. Ignition on?")
        for b in found:
            ids = ", ".join(b["ids"][:8]) + (" …" if len(b["ids"]) > 8 else "")
            print(f"  {b['kind'].upper():<6} pins {'/'.join(map(str, b['pins'])):<8} {b['bitrate'] // 1000:>4} kbit/s  {b['frames']:>5} frames  IDs {ids}")
        return 0
    finally:
        adapter.close()


def cmd_gui(args) -> int:
    from .gui import serve
    from .wired import resolve_host
    host = resolve_host(args.host)
    token = args.token or os.environ.get("EVSOC_GUI_TOKEN") or None
    port = 0 if args.window and args.port == 8787 else args.port  # own window: any free port, several may run
    server = serve(open_adapter, host=host, port=port, open_browser=not (args.no_browser or args.window),
                   wired_only=WIRED_ONLY, token=token)
    print(f"evsoc interface: {server.url}")
    local = host in ("127.0.0.1", "localhost", "::1")
    if args.window:
        from .gui import open_window
        print(f"Window: {open_window(server.url)}.")
    if args.window or (local and not args.no_browser and not args.keep_running):
        import threading

        from .gui import page_gone
        print("evsoc quits when the page is closed (not while continuous operation or a test is running; --keep-running to stay).")

        def watch() -> None:
            while not page_gone(server):
                time.sleep(2)
            print("Page closed, quitting.")
            server.shutdown()

        threading.Thread(target=watch, daemon=True).start()
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Reachable via {args.host} ({host}).")
        print("Note: reachable on the network. Access only with the link above (it contains the key), without encryption (HTTP). Use only on your own network.")
    print("Quit with Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.session.stop_monitor()
        server.session.disconnect()
        for extra in server.extra:
            extra.shutdown()
            extra.server_close()
        server.server_close()
    return 0


def cmd_desktop(args) -> int:
    """Linux desktop: put evsoc into the application menu, so that no terminal is needed."""
    import shutil

    from .gui import install_desktop, remove_desktop
    if args.remove:
        removed = remove_desktop()
        print("Removed: " + ", ".join(map(str, removed)) if removed else "No launcher was installed.")
        return 0
    exe = shutil.which("evsoc") if not sys.argv[0].endswith("evsoc") else os.path.abspath(sys.argv[0])
    command = exe if exe and os.path.exists(exe) else f"{sys.executable} -m evsoc"
    entry, _icon = install_desktop(command)
    print(f"Launcher installed: {entry}\nevsoc is now in the application menu (log out and in if needed). Remove: evsoc desktop --remove")
    return 0


def cmd_run(args) -> int:
    """The installed device: monitoring, passing values on, display and setup in one process."""
    from . import appliance, config
    from .wired import resolve_host
    global WIRED_ONLY
    sys.stdout.reconfigure(line_buffering=True)  # show up in journalctl right away
    cfg = config.load(args.config)
    WIRED_ONLY = WIRED_ONLY or bool(cfg.get("wired_only", True))
    app = appliance.Appliance(args.config, open_adapter)
    host = resolve_host(args.host or cfg["web"]["host"])
    port = args.port or int(cfg["web"]["port"])
    server = appliance.serve(app, host, port)
    shown = host if ":" not in host else f"[{host}]"
    print(f"evsoc is running: display http://{shown}:{server.server_address[1]}/  ·  setup …/setup")
    if app.setup_code:
        print(f"First setup: setup code {app.setup_code} (valid until a PIN is set)")
    app.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        for extra in server.extra:
            extra.shutdown()
            extra.server_close()
        server.server_close()
    return 0


def cmd_pin(args) -> int:
    """Set the setup PIN on the device itself (e.g. when it was forgotten)."""
    import getpass

    from . import config
    pin = args.pin or getpass.getpass("New PIN (at least 4 digits): ")
    if len(pin) < 4 or not pin.isdigit():
        print("The PIN must have at least 4 digits.", file=sys.stderr)
        return 2
    cfg = config.load(args.config)
    cfg["pin_hash"] = config.hash_pin(pin)
    config.save(cfg, args.config)
    print(f"PIN saved in {args.config}. Restart the service: sudo systemctl restart evsoc")
    return 0


def cmd_update(args) -> int:
    from . import importers
    unknown = set(args.sources) - set(importers.IMPORTERS)
    if unknown:
        print(f"Unknown source: {', '.join(unknown)}. Possible: {', '.join(importers.IMPORTERS)}", file=sys.stderr)
        return 2
    importers.run(args.sources or list(importers.IMPORTERS))
    load_all.cache_clear()
    print(f"Done: {len(load_all())} profiles available.")
    return 0


def open_sniff_source(url: str, protocol: str, pins: tuple[int, ...]):
    """Second adapter on the Y cable (listen only), or evsoc between an ENET app and the car.

    The wired-only rule does not apply: sniffing is a workshop job next to apps on phones."""
    from . import sniff
    if url.startswith("enet://"):
        raise AdapterError("ENET cannot be overheard with a Y cable (Ethernet is point to point). Put evsoc in between instead: -a enet-proxy://auto (see docs/listening-in.md)")
    if url.startswith("enet-proxy://"):
        from .enet_sniff import EnetProxySource
        rest, _, query = url[len("enet-proxy://"):].partition("?")
        q = parse_qs(query)
        return EnetProxySource(rest or "auto", listen=q.get("listen", ["0.0.0.0"])[0],
                               port=int(q["port"][0]) if "port" in q else None,
                               discovery=q.get("discovery", q.get("suche", ["1"]))[0] not in ("0", "false"),
                               vin=q.get("vin", [None])[0])
    if url.startswith("mock://"):
        return sniff.MockAppSource(url[len("mock://"):])
    if url.startswith("can://"):
        rest, _, query = url[len("can://"):].partition("?")
        interface, _, channel = rest.partition("/")
        q = parse_qs(query)
        return sniff.CanSource(interface, channel or "can0", bitrate=int(q.get("bitrate", ["500000"])[0]),
                               fd=q.get("fd", ["0"])[0] in ("1", "true"),
                               listen_only=q.get("listen_only", ["1"])[0] in ("1", "true"))
    return sniff.ElmMonitorSource(open_adapter(url, None, wired_check=False), protocol, pins)


def cmd_sniff(args) -> int:
    """Listen in on another OBD app through a Y cable: what it asks, what evsoc knows, which formula fits."""
    from . import sniff
    if bool(args.adapter) == bool(args.file):
        print("Give either -a ADAPTER (listen live) or -d FILE (evaluate a capture).", file=sys.stderr)
        return 2
    out = (lambda _m: None) if args.json else print
    sniffer = sniff.Sniffer(sniff.KnownIndex(load_all()))
    bitrate = 250_000 if args.protocol in ("8", "9") else 500_000
    if args.reference and args.reference_profile and args.reference_profile not in load_all():
        print(f"Unknown profile {args.reference_profile!r}", file=sys.stderr)
        return 2
    if args.file:
        frames, markers = sniff.read_log(args.file)
        for f in frames:
            sniffer.feed(f)
        sniffer.tick(float("inf"))
        sniffer.markers += markers
    else:
        source = open_sniff_source(args.adapter, args.protocol, tuple(int(p) for p in args.pins.split(",")))
        bitrate = getattr(source, "bitrate", bitrate)
        path = args.output or time.strftime("capture-%Y%m%d-%H%M%S.log")
        writer = sniff.LogWriter(path, source.description)
        out(f"Listening: {source.description}. evsoc sends nothing.\nCapture: {path}\nNow open the wanted values in the app. Type the values shown here, e.g. \"soc 80.5\" + Enter.\nQuit with Ctrl+C.\n")
        feed = ref = None
        if args.reference:
            import threading

            from . import broadcast
            profiles = load_all()
            feed = broadcast.Feed()
            if sys.stdin is not None and sys.stdin.isatty():  # typed values still work next to the reference
                threading.Thread(target=lambda: [feed.put(line) for line in sys.stdin], daemon=True).start()
            ref = broadcast.Reference(lambda: open_adapter(args.reference, None), profiles, feed,
                                      profile=profiles.get(args.reference_profile or ""), car=args.car,
                                      interval=args.reference_interval, log=out)
            ref.start()
        try:
            sniff.run_live(source, sniffer, writer, duration=args.duration, show_all=args.show_all, out=out, stdin=feed)
        finally:
            if ref is not None:
                ref.finish()
                feed.close()
        sniffer.tick(float("inf"))
    day = sniffer.first_t
    for text in args.value or []:
        sniffer.markers.append(sniff.parse_marker(text, day))
    formulas = sniff.find_formulas(sniffer.conversations, sniffer.markers, args.tolerance)
    if args.json:
        print(json.dumps(sniff.report_json(sniffer, formulas), ensure_ascii=False, indent=1))
    else:
        sniff.report(sniffer, formulas)
    if args.write_profile:
        name = Path(args.write_profile).stem
        if not sniff.write_profile(args.write_profile, name, formulas, args.car, bitrate, out=out):
            return 1
    return 0


def cmd_analyse(args) -> int:
    """Record everything (CAN through a Y cable, Ethernet through a TAP) and boil it down to a report."""
    from . import analyse, sniff
    if bool(args.adapter) == bool(args.file):
        print("Give either -a ADAPTER (record and evaluate) or -d FILE (evaluate a capture).",
              file=sys.stderr)
        return 2
    known = sniff.KnownIndex(load_all())
    path, bitrate = args.file, args.bitrate
    if args.adapter:
        notes: list[tuple[float, str]] = []
        if args.adapter.startswith("eth://"):
            from .pcap import EthSource
            path = args.capture or time.strftime("capture-%Y%m%d-%H%M%S.pcap")
            try:
                source = EthSource(args.adapter[len("eth://"):], path)
            except OSError as e:
                raise AdapterError(str(e)) from e
            writer = sniff.LogWriter(path + ".notes", source.description)
            status = lambda: f"{source.packets} Pakete"  # noqa: E731
        else:
            source = open_sniff_source(args.adapter, args.protocol, tuple(int(p) for p in args.pins.split(",")))
            bitrate = bitrate or getattr(source, "bitrate", None)
            path = args.capture or time.strftime("capture-%Y%m%d-%H%M%S.log")
            writer = sniff.LogWriter(path, source.description)
            status = None
        print(f"Recording: {source.description}. evsoc sends nothing.\nCapture: {path}\nType what you are doing + Enter (e.g. \"door open\", \"charging started\", \"soc 80.5\"). It goes into the report with the time.\nQuit with Ctrl+C.\n")
        sniff.run_live(source, sniff.Sniffer(known), writer, duration=args.duration, notes=notes, status=status)
    a = analyse.load(path, known, bitrate or 500_000)
    text = analyse.report(a, args.id, points=args.points, max_streams=args.max_ids)
    if args.output == "-":
        print(text, end="")
        return 0
    target = args.output or str(Path(path).with_suffix(".analyse.md"))
    Path(target).write_text(text, encoding="utf-8")
    parts = [f"{a.can_frames} CAN frames, {len(a.can)} IDs"] if a.can_frames else []
    parts += [f"{a.packets} Ethernet packets"] if a.packets else []
    parts += [f"{len(a.sniffer.convs)} diagnostic requests"] if a.sniffer.convs else []
    if not parts:
        print(f"\nNothing recorded. Ignition on, right bus, right bitrate? Report anyway: {target}")
        return 1
    print(f"\n{', '.join(parts)} in {a.seconds:.0f} s")
    print(f"Report: {target} ({text.count(chr(10))} lines, {len(text.encode()) // 1024 + 1} kB)")
    print(f"Give this file to Claude (upload or paste it) and say what you want to know.\nA single frame in full length: evsoc analyse -d {path} --id 3D2 -o -")
    return 0


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Lists only the first long option; the German ones from earlier versions keep working as aliases."""

    def _format_action_invocation(self, action):
        if action.option_strings:
            longs = [o for o in action.option_strings if o.startswith("--")]
            keep = [o for o in action.option_strings if not o.startswith("--")] + longs[:1]
            action = argparse.Action(keep, action.dest, nargs=action.nargs, metavar=action.metavar,
                                     choices=action.choices) if keep != action.option_strings else action
        return super()._format_action_invocation(action)


def _use_formatter(parser) -> None:
    parser.formatter_class = _HelpFormatter
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                _use_formatter(sub)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evsoc",
        description="Read the state of charge (SoC) of EVs and plug-in hybrids through an OBD adapter. Read access only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ADAPTER_HELP,
    )
    parser.add_argument("--wired-only", "--nur-kabel", action="store_true",
                        help="wired adapters only (USB, CAN, ENET), no WiFi/Bluetooth; also via EVSOC_WIRED_ONLY=1")
    parser.add_argument("--version", action="version", version=f"evsoc {__version__}")
    parser.add_argument("--lang", choices=["en", "de"],
                        help="output language: en or de (default: system language; also via EVSOC_LANG)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profiles", help="list all profiles")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--source", choices=["evsoc", "obdb", "abrp", "wican"])
    p.set_defaults(fn=cmd_profiles)

    p = sub.add_parser("models", help="search vehicles, e.g. 'evsoc models ioniq'")
    p.add_argument("query", nargs="*")
    p.add_argument("--markdown", action="store_true", help="complete list as Markdown (docs/vehicles.md)")
    p.set_defaults(fn=cmd_models)

    p = sub.add_parser("devices", help="find adapters")
    p.add_argument("--ble", action="store_true", help="also scan Bluetooth LE")
    p.add_argument("--enet", action="store_true", help="also look for BMW ENET")
    p.set_defaults(fn=cmd_devices)

    p = sub.add_parser("plan", help="choose a vehicle: which OBD type (bus, pins) and which adapter fits")
    p.add_argument("car", help="model, e.g. 'Nissan Leaf' or 'e-208'")
    p.add_argument("-a", "--adapter", help="also check your own adapter")
    p.add_argument("--year", type=int)
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("probe", help="test drive at the car: test all fitting profiles completely, write a report",
                       epilog=ADAPTER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-a", "--adapter", help="see below")
    p.add_argument("-d", "--file", "--datei", metavar="REPORT", help="instead of at the car: re-evaluate a report with the current profiles")
    p.add_argument("-o", "--output", metavar="FILE", help="report name (default evsoc-probe-VIN-DATE.json)")
    p.add_argument("--car", help="give the model, e.g. 'i4' (default: by VIN)")
    p.add_argument("--vin", help="give the VIN (default: read from the car)")
    p.add_argument("--year", type=int, help="model year (default: from the VIN)")
    p.add_argument("--all-profiles", "--alle", action="store_true", help="test all profiles, not only those fitting the car (takes a while)")
    p.add_argument("--note", "--notiz", action="append", metavar="NAME=VALUE",
                   help="value read off the car for comparison, e.g. --note soc=54 --note soh=93 (repeatable)")
    p.add_argument("--battery-kwh", "--akku-kwh", type=float, metavar="KWH", help="net nominal capacity, for SoH from the energy content")
    p.add_argument("--no-diagnosis", "--ohne-diagnose", action="store_true",
                   help="do not read identification and fault memory of the control units (default: read, never clear)")
    p.add_argument("--raw", nargs="+", metavar="COMMAND",
                   help="afterwards additional read commands as with 'evsoc raw', e.g. ATSH6F1 ATCEA07 22E500-22E5FF")
    p.add_argument("--log", metavar="FILE", help="log all adapter traffic")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("wake", help="wake test: can the parked car be woken, does it fall asleep again?",
                       epilog=ADAPTER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-a", "--adapter", required=True, help="see below")
    p.add_argument("-p", "--profile", help="profile name (default: automatic detection, which means more requests)")
    p.add_argument("--car", help="give the model, e.g. 'i4'")
    p.add_argument("--duration", "--dauer", type=float, default=20, metavar="MIN", help="watch this long whether it falls asleep again (20)")
    p.add_argument("--interval", "--abstand", type=float, default=30, metavar="SEC", help="interval between observations (30)")
    p.add_argument("--awake-voltage", type=float, default=13.0, metavar="V", help="from this 12 V voltage the car counts as awake")
    p.add_argument("--min-voltage", type=float, default=12.2, metavar="V", help="below this, no waking")
    p.add_argument("-o", "--output", metavar="FILE", help="report name (default evsoc-waketest-DATE.json)")
    p.add_argument("--log", metavar="FILE", help="log all adapter traffic")
    p.set_defaults(fn=cmd_wake)

    p = sub.add_parser("scan", help="find active buses at the OBD socket (evsoc box)")
    p.add_argument("-a", "--adapter", required=True)
    p.add_argument("--log", metavar="FILE")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("gui", help="start the interface in the browser")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--host", default="127.0.0.1",
                   help="127.0.0.1 = this computer only (default); interface name like eth0 = only over this cable; 0.0.0.0 = all networks")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    p.add_argument("--token", help="fixed access key (default: new on every start); also via EVSOC_GUI_TOKEN")
    p.add_argument("--keep-running", action="store_true", help="keep running when the page is closed")
    p.add_argument("--window", "--fenster", action="store_true",
                   help="open as a window of its own (Chromium/Chrome, else the default browser) and quit when it is closed")
    p.set_defaults(fn=cmd_gui)

    p = sub.add_parser("desktop", help="Linux: add evsoc to the application menu (start without a terminal)")
    p.add_argument("--remove", "--entfernen", action="store_true", help="remove the entry again")
    p.set_defaults(fn=cmd_desktop)

    from .config import DEFAULT_PATH
    p = sub.add_parser("run", help="run as an installed device: continuous operation, outputs, display, setup")
    p.add_argument("--config", default=str(DEFAULT_PATH), help=f"configuration file (default {DEFAULT_PATH})")
    p.add_argument("--host", help="overrides web.host from the configuration, e.g. eth0")
    p.add_argument("--port", type=int, help="overrides web.port")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("pin", help="set the setup PIN on the device")
    p.add_argument("--config", default=str(DEFAULT_PATH))
    p.add_argument("--pin", help="(default: asked for)")
    p.set_defaults(fn=cmd_pin)

    p = sub.add_parser("update", help="re-import profiles from ABRP, WiCAN and OBDb (internet)")
    p.add_argument("sources", nargs="*", metavar="SOURCE", help="abrp, wican, obdb (default: all)")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser(
        "sniff", help="listen in on other OBD apps through a Y cable (listen only) and build profiles from it",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Setup: car ── Y cable ──┬── the app's adapter (Car Scanner, BimmerLink, …)\n"
               "                        └── second adapter for evsoc (-a)\n\n"
               "  can://slcan//dev/cu.usbmodem1   CAN interface (CANable), listens without ACK (best)\n"
               "  can://socketcan/can0            Pi with a CAN HAT\n"
               "  /dev/cu.usbserial-X             ELM327/OBDLink over USB in listen mode (ATMA)\n"
               "  box:/dev/ttyACM0                evsoc box (listen-only)\n"
               "  enet-proxy://auto               BMW/Mini ENET (UCSI-3000, ENET cable): the app connects to evsoc,\n"
               "                                  evsoc passes everything on to the car (no Y cable)\n"
               "  mock://corsa-e                  try without a car\n\n"
               "Examples:\n"
               "  evsoc sniff -a can://slcan//dev/cu.usbmodem1\n"
               "  evsoc sniff -d capture.log --value soc=54.8@21:03:10 --value soc=79.9@21:40:00 --write-profile my_car.json")
    p.add_argument("-a", "--adapter", help="second adapter on the Y cable")
    p.add_argument("-d", "--file", "--datei", help="evaluate a capture (candump log, .asc, .blf, .trc, ATMA text)")
    p.add_argument("-o", "--output", "--ausgabe", metavar="FILE", help="capture goes here (default capture-DATE.log)")
    p.add_argument("--protocol", "--protokoll", default="6", choices=["6", "7", "8", "9"],
                   help="ELM/OBDLink/box: 6 = 11 bit 500 kbit/s (default), 7 = 29 bit (VW ID., Renault), 8/9 = 250 kbit/s")
    p.add_argument("--pins", default="6,14", help="evsoc box: OBD pins, e.g. 12,13 (Leaf EV-CAN)")
    p.add_argument("--duration", "--dauer", type=float, metavar="SEC", help="stop after SEC seconds")
    p.add_argument("--show-all", "--alles", action="store_true", help="show every answer, changed bytes in [ ]")
    p.add_argument("--value", "--wert", action="append", metavar="NAME=VALUE[@HH:MM:SS]",
                   help="value read off the app, e.g. soc=80.5 (repeatable, best with the time)")
    p.add_argument("--tolerance", "--toleranz", type=float, help="allowed deviation of the formula (default 1 %%, at least 0.06)")
    p.add_argument("--reference", "--referenz", metavar="ADAPTER",
                   help="second adapter through which evsoc reads the car meanwhile (e.g. enet://auto); its values are the yardstick for the search in broadcast frames")
    p.add_argument("--reference-profile", "--referenz-profil", metavar="PROFILE", help="profile for the reference (default: automatic or by --car)")
    p.add_argument("--reference-interval", "--referenz-abstand", type=float, default=10, metavar="SEC", help="interval of the reference values (10)")
    p.add_argument("--write-profile", "--profil", metavar="FILE.json", help="write an evsoc profile from the formulas found")
    p.add_argument("--car", help="vehicle for the profile, e.g. 'Opel Corsa-e'")
    p.add_argument("--json", action="store_true", help="evaluation as JSON")
    p.set_defaults(fn=cmd_sniff)

    p = sub.add_parser(
        "analyse", help="record complete CAN or Ethernet traffic and condense it into a report for Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Record (-a):\n"
               "  can://slcan//dev/ttyACM0     CAN interface on the Y cable (as with 'sniff', also gs_usb, socketcan, ?fd=1)\n"
               "  /dev/ttyUSB0, box:/dev/…     ELM327/OBDLink/evsoc box in listen mode\n"
               "  enet-proxy://auto            BMW ENET: evsoc between app and car\n"
               "  eth://eth0                   Ethernet interface (Linux, root), e.g. behind a TAP or media converter\n"
               "  mock://tesla-m3              try without a car\n"
               "Evaluate (-d): candump log, .asc, .blf, .trc, .csv, ATMA text, .pcap, .pcapng\n"
               "Examples:\n"
               "  evsoc analyse -a \"can://slcan//dev/ttyACM0?bitrate=500000\" --duration 120\n"
               "  evsoc analyse -d drive.pcapng\n"
               "  evsoc analyse -d capture.log --id 3D2 --id 22D410 -o -")
    p.add_argument("-a", "--adapter", help="record, then evaluate")
    p.add_argument("-d", "--file", "--datei", help="evaluate an existing capture")
    p.add_argument("-o", "--output", "--ausgabe", metavar="FILE", help="report goes here (default CAPTURE.analyse.md, '-' = terminal)")
    p.add_argument("--capture", "--mitschnitt", metavar="FILE", help="raw data while recording goes here (default capture-DATE.log/.pcap)")
    p.add_argument("--duration", "--dauer", type=float, metavar="SEC", help="stop after SEC seconds")
    p.add_argument("--id", action="append", metavar="ID", help="only this CAN ID, request (22D410) or stream, but in full length; repeatable")
    p.add_argument("--points", "--punkte", type=int, default=12, help="history lines per frame (12)")
    p.add_argument("--max-ids", type=int, default=60, help="show this many frames individually (60)")
    p.add_argument("--bitrate", type=int, help="CAN bitrate for the bus load (default 500000)")
    p.add_argument("--protocol", "--protokoll", default="6", choices=["6", "7", "8", "9"], help="ELM/OBDLink/box only, as with 'sniff'")
    p.add_argument("--pins", default="6,14", help="evsoc box: OBD pins, e.g. 12,13")
    p.set_defaults(fn=cmd_analyse)

    for name, fn, helptext in (("read", cmd_read, "read the state of charge"), ("raw", cmd_raw, "send single read commands"),
                               ("monitor", cmd_monitor, "monitor continuously (adapter stays in the car)")):
        p = sub.add_parser(name, help=helptext, epilog=ADAPTER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument("-a", "--adapter", required=True, help="see below")
        p.add_argument("--log", metavar="FILE", help="log all adapter traffic")
        p.set_defaults(fn=fn)
    read_p = sub.choices["read"]
    read_p.add_argument("-p", "--profile", default="auto", help="profile name or 'auto' (default)")
    read_p.add_argument("--car", help="give the model, e.g. 'e-208' or 'Ioniq 5' (faster)")
    read_p.add_argument("--vin", help="give the VIN (default: read from the car)")
    read_p.add_argument("--year", type=int, help="model year (default: from the VIN)")
    read_p.add_argument("--battery-kwh", "--akku-kwh", type=float, metavar="KWH",
                        help="net nominal capacity, for SoH from the energy content (e.g. VW MEB: 58 or 77)")
    read_p.add_argument("--all", action="store_true", help="all values of the profile, not only SoC")
    read_p.add_argument("--watch", type=float, metavar="SEC", help="repeat every SEC seconds")
    read_p.add_argument("--json", action="store_true", help="JSON output")
    mon = sub.choices["monitor"]
    mon.add_argument("-p", "--profile", help="profile name (default: one-off detection, remembered in --state)")
    mon.add_argument("--car", help="give the model, e.g. 'e-208'")
    mon.add_argument("--year", type=int, help="model year")
    mon.add_argument("--battery-kwh", "--akku-kwh", type=float, metavar="KWH", help="net nominal capacity, for SoH (see read)")
    mon.add_argument("--interval", type=float, default=60, metavar="SEC", help="interval while the car is awake (60)")
    mon.add_argument("--sleep-interval", type=float, default=300, metavar="SEC", help="interval while it is asleep (300)")
    mon.add_argument("--awake-voltage", type=float, default=13.0, metavar="V",
                     help="from this 12 V voltage the car counts as awake (13.0; higher with a 12 V lithium battery)")
    mon.add_argument("--wake-every", type=float, metavar="HOURS",
                     help="wake a sleeping car when the last value is older than HOURS hours (e.g. 24)")
    mon.add_argument("--wake-at", action="append", metavar="HH:MM",
                     help="wake a sleeping car daily at this time (repeatable)")
    mon.add_argument("--min-voltage", type=float, default=12.2, metavar="V",
                     help="never wake when the 12 V battery is below this (12.2)")
    mon.add_argument("--wake-gap", type=float, default=10, metavar="MIN",
                     help="minimum gap between two wake-ups on request (MQTT command, button), in minutes (10)")
    mon.add_argument("--state", metavar="FILE", help="save the last state as JSON (and load it at start)")
    mon.add_argument("--mqtt", metavar="URL",
                     help="mqtt://user:pass@host:1883/evsoc/auto, with Home Assistant discovery; 'wake' to …/cmd reads at once")
    mon.add_argument("--webhook", metavar="URL", help="send the state with every check by HTTP POST")
    mon.add_argument("--json", action="store_true", help="JSON lines instead of text")
    mon.add_argument("--once", action="store_true", help="a single check only (e.g. from cron)")
    raw_p = sub.choices["raw"]
    raw_p.add_argument("-p", "--profile", help="send this profile's init commands first")
    raw_p.add_argument("commands", nargs="+", help="e.g. ATSH7E4 220105, ranges like 22DD00-22DDFF")
    raw_p.add_argument("--hits", "--treffer", action="store_true", help="show positive answers only (for ranges)")

    _use_formatter(parser)
    from . import i18n
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--lang" in argv[:-1]:  # decide the language before argparse prints help or errors
        i18n.set_lang(argv[argv.index("--lang") + 1] if argv[argv.index("--lang") + 1] in i18n.LANGS else None)
    german = i18n.lang() == "de"
    if german:
        i18n.translate_parser(parser)
    saved = sys.stdout, sys.stderr
    if german:
        sys.stdout, sys.stderr = i18n.TranslatingStream(sys.stdout), i18n.TranslatingStream(sys.stderr)
    try:
        args = parser.parse_args(argv)
        global WIRED_ONLY
        WIRED_ONLY = args.wired_only or os.environ.get("EVSOC_WIRED_ONLY", os.environ.get("EVSOC_NUR_KABEL")) == "1"
        try:
            return args.fn(args)
        except (AdapterError, TransportError, SafetyError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130
    finally:
        if german:
            sys.stdout.flush()
            sys.stderr.flush()
            sys.stdout, sys.stderr = saved
        i18n.set_lang(None)


if __name__ == "__main__":
    sys.exit(main())
