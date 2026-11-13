"""Wired-only operation: no WLAN, no Bluetooth, between car, adapter and computer.

- adapters: USB serial (OBDLink SX/EX, ELM327 USB), CAN interfaces / Pi CAN HATs
  (SocketCAN), BMW ENET (Ethernet cable). Bluetooth serial ports look like
  serial ports too, so a serial port only counts as wired if it is a USB device.
- GUI: can be bound to one network interface (e.g. eth0), so it is only
  reachable over that cable.
"""

from __future__ import annotations

import ipaddress
import platform
import re
import subprocess
from pathlib import Path

WIRELESS_SCHEMES = ("ble://", "tcp://")


class WiredOnlyError(ValueError):
    pass


def usb_serial_ports() -> list[dict]:
    """Serial ports that belong to a USB device (Bluetooth/debug ports have no USB vendor id)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [{"device": p.device, "description": p.description, "vid": p.vid, "pid": p.pid}
            for p in list_ports.comports() if p.vid is not None]


def is_wired_serial(path: str) -> bool:
    if re.search(r"rfcomm|bluetooth", path, re.I):
        return False
    return any(p["device"] == path for p in usb_serial_ports())


def socketcan_interfaces() -> list[str]:
    """CAN network interfaces on Linux (Pi CAN HATs, USB-CAN with gs_usb/socketcan driver)."""
    base = Path("/sys/class/net")
    if not base.exists():
        return []
    found = []
    for iface in sorted(base.iterdir()):
        try:
            if (iface / "type").read_text().strip() == "280":  # ARPHRD_CAN
                found.append(iface.name)
        except OSError:
            continue
    return found


def check_url(url: str) -> None:
    """Raise if the adapter address would use a radio link."""
    inner = url[len("box:"):] if url.startswith("box:") else url
    if inner.startswith(WIRELESS_SCHEMES):
        raise WiredOnlyError(f"Wired-only mode: {url} is a wireless connection (WiFi/Bluetooth).")
    if inner.startswith(("mock://", "can://", "enet://")):
        return
    path = inner[len("serial://"):].split("?")[0] if inner.startswith("serial://") else inner
    if not is_wired_serial(path):
        raise WiredOnlyError(
            f"Wired-only mode: {path} is not a USB device (probably a paired Bluetooth adapter). Allowed are USB adapters, CAN interfaces (can://) and ENET (enet://).")


def interface_ipv4(name: str) -> str | None:
    """IPv4 address of a network interface such as eth0, usb0 or en0."""
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["ipconfig", "getifaddr", name], capture_output=True, text=True, timeout=5).stdout.strip()
            return out or None
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", name], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_host(value: str) -> str:
    """Accept an IP, a host name or an interface name (eth0) for --host."""
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if value == "localhost" or "." in value:
        return value
    ip = interface_ipv4(value)
    if ip is None:
        raise WiredOnlyError(f"Interface {value!r} has no IPv4 address (cable plugged in?).")
    return ip
