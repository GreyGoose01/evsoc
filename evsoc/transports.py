"""Byte pipes to ELM327-compatible adapters: USB/Bluetooth serial, WiFi (TCP), BLE."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from typing import Protocol


class TransportError(RuntimeError):
    pass


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> bytes: ...
    def close(self) -> None: ...


class SerialTransport:
    """USB adapters and Bluetooth-classic adapters (show up as /dev/cu.* on macOS)."""

    def __init__(self, port: str, baud: int = 38400):
        try:
            import serial
        except ImportError as e:
            raise TransportError("pyserial missing: pip install pyserial") from e
        try:
            self._s = serial.Serial(port, baud, timeout=0.05)
        except serial.SerialException as e:
            raise TransportError(f"Cannot open {port}: {e}") from e

    def write(self, data: bytes) -> None:
        self._s.write(data)

    def read(self, timeout: float) -> bytes:
        self._s.timeout = timeout
        first = self._s.read(1)
        return first + self._s.read(self._s.in_waiting) if first else b""

    def close(self) -> None:
        self._s.close()


class TcpTransport:
    """WiFi adapters, usually at 192.168.0.10:35000."""

    def __init__(self, host: str, port: int = 35000, connect_timeout: float = 5.0):
        try:
            self._s = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            raise TransportError(
                f"No connection to {host}:{port}: {e}. Is the computer on the adapter's WiFi?"
            ) from e

    def write(self, data: bytes) -> None:
        self._s.sendall(data)

    def read(self, timeout: float) -> bytes:
        self._s.settimeout(timeout)
        try:
            data = self._s.recv(4096)
        except TimeoutError:
            return b""
        if not data:
            raise TransportError("The adapter closed the connection")
        return data

    def close(self) -> None:
        self._s.close()


# (service, notify characteristic, write characteristic) seen on common BLE dongles.
_BLE_KNOWN = [
    ("0000fff0-0000-1000-8000-00805f9b34fb", "0000fff1-0000-1000-8000-00805f9b34fb",
     "0000fff2-0000-1000-8000-00805f9b34fb"),  # Veepeak, Vgate, many clones, OBDLink CX
    ("0000ffe0-0000-1000-8000-00805f9b34fb", "0000ffe1-0000-1000-8000-00805f9b34fb",
     "0000ffe1-0000-1000-8000-00805f9b34fb"),  # HM-10 style, LELink
    ("e7810a71-73ae-499d-8c15-faa9aef0c3f2", "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
     "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"),  # vLinker
]


class BleTransport:
    """Bluetooth-LE adapters (the ones that also work with iPhones). Needs `bleak`."""

    def __init__(self, target: str, scan_timeout: float = 8.0):
        try:
            import bleak  # noqa: F401
        except ImportError as e:
            raise TransportError("bleak missing: pip install bleak") from e
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._run(self._connect(target, scan_timeout), scan_timeout + 15)

    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _connect(self, target: str, scan_timeout: float) -> None:
        from bleak import BleakClient, BleakScanner

        device = await BleakScanner.find_device_by_address(target, timeout=scan_timeout)
        if device is None:
            device = await BleakScanner.find_device_by_filter(
                lambda d, _adv: bool(d.name) and target.lower() in d.name.lower(),
                timeout=scan_timeout,
            )
        if device is None:
            raise TransportError(f"BLE device {target!r} not found")
        self._client = BleakClient(device)
        await self._client.connect()
        notify_uuid, self._write_uuid = self._pick_characteristics()
        await self._client.start_notify(notify_uuid, self._on_data)

    def _pick_characteristics(self) -> tuple[str, str]:
        services = self._client.services
        for svc, notify, write in _BLE_KNOWN:
            if services.get_service(svc) and services.get_characteristic(notify):
                return notify, write
        # Unknown dongle: first service that has both a notify and a write characteristic.
        for svc in services:
            n = [c for c in svc.characteristics if {"notify", "indicate"} & set(c.properties)]
            w = [c for c in svc.characteristics
                 if {"write", "write-without-response"} & set(c.properties)]
            if n and w:
                return n[0].uuid, w[0].uuid
        raise TransportError("No serial BLE interface found on the device")

    def _on_data(self, _char, data: bytearray) -> None:
        with self._cond:
            self._buf.extend(data)
            self._cond.notify_all()

    def write(self, data: bytes) -> None:
        async def send():
            for i in range(0, len(data), 20):
                await self._client.write_gatt_char(self._write_uuid, data[i : i + 20], response=False)

        self._run(send(), 5)

    def read(self, timeout: float) -> bytes:
        with self._cond:
            if not self._buf:
                self._cond.wait(timeout)
            data = bytes(self._buf)
            self._buf.clear()
            return data

    def close(self) -> None:
        try:
            self._run(self._client.disconnect(), 5)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)


class LoggingTransport:
    """Wraps a transport and writes all traffic to a text file (for reverse engineering)."""

    def __init__(self, inner: Transport, path: str):
        self._inner = inner
        self._f = open(path, "a", encoding="utf-8")

    def _log(self, direction: str, data: bytes) -> None:
        text = data.decode("ascii", "replace").replace("\r", "\\r").replace("\n", "\\n")
        self._f.write(f"{time.strftime('%H:%M:%S')} {direction} {text}\n")
        self._f.flush()

    def write(self, data: bytes) -> None:
        self._log(">", data)
        self._inner.write(data)

    def read(self, timeout: float) -> bytes:
        data = self._inner.read(timeout)
        if data:
            self._log("<", data)
        return data

    def close(self) -> None:
        self._inner.close()
        self._f.close()
