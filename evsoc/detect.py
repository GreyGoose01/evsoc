"""Find the adapter by itself: evsoc box first, then USB OBD adapters, then CAN interfaces,
then a BMW/Mini ENET connection (cable or WLAN/LAN adapter such as the UCSI-3000)."""

from __future__ import annotations

from collections.abc import Callable

from .elm import AdapterError
from .transports import TransportError
from .wired import socketcan_interfaces, usb_serial_ports

Log = Callable[[str], None]


def candidate_urls(wired_only: bool = True) -> list[str]:
    ports = sorted(usb_serial_ports(), key=lambda p: ("ACM" not in p["device"] and "usbmodem" not in p["device"], p["device"]))
    urls = []
    for p in ports:  # CDC-ACM ports first: that is how the evsoc box shows up
        urls += [f"box:{p['device']}", p["device"]]
    urls += [f"can://socketcan/{name}" for name in socketcan_interfaces()]
    urls.append("enet://auto")  # last: only answers while a BMW/Mini is awake, takes a few seconds
    return urls


def find_adapter(open_adapter, wired_only: bool = True, log: Log = print, urls: list[str] | None = None):
    """Return (url, adapter) of the first adapter that answers, or raise AdapterError."""
    tried = []
    for url in urls if urls is not None else candidate_urls(wired_only):
        try:
            adapter = open_adapter(url, None)
        except (AdapterError, TransportError, OSError, ValueError) as e:
            tried.append(f"{url}: {e}")
            continue
        log(f"Adapter found: {url} ({adapter.version})")
        return url, adapter
    detail = "; ".join(tried) if tried else "no USB adapter, no CAN interface, no ENET"
    raise AdapterError(f"No adapter found ({detail}). Is the USB cable plugged in? With ENET: ignition on and connected to the adapter's network?")
