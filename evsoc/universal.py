"""Backend for the evsoc box (universal adapter, USB only, no radio), see docs/box-protocol.md.

The box speaks the ELM327 command set (so every OBD app works with it) plus a
few EVS* commands that select the physical bus: transceiver type, OBD pins,
bitrate and listen-only mode. evsoc derives the bus for every profile step
(connection.py) and switches the box before sending the step's requests.
"""

from __future__ import annotations

import re

from .connection import Bus, Capabilities
from .elm import AdapterError, ElmAdapter

_KIND_WORD = {"can": "CAN", "canfd": "CANFD", "kline": "KLINE", "j1850": "J1850", "swcan": "SWCAN", "doip": "DOIP"}


def bus_command(bus: Bus) -> str:
    """EVSBUS command for a bus, e.g. 'EVSBUS CAN 12,13 500000'."""
    parts = ["EVSBUS", _KIND_WORD[bus.kind], ",".join(map(str, bus.pins))]
    if bus.kind == "doip":
        parts[2] = "1" if bus.pins[0] == 3 else "2"  # ISO 13400-4 option 1 or 2
    elif bus.bitrate:
        parts.append(str(bus.bitrate))
        if bus.data_bitrate:
            parts.append(str(bus.data_bitrate))
    return " ".join(parts)


class UniversalAdapter(ElmAdapter):
    def __init__(self, transport, timeout: float = 5.0):
        super().__init__(transport, timeout)
        self.capabilities: Capabilities | None = None
        self._bus: Bus | None = None

    def reset(self) -> None:
        super().reset()
        lines = self._send("EVSI")
        info = " ".join(lines)
        if not info.startswith("EVSOC-BOX"):
            raise AdapterError(f"Not an evsoc box (answer to EVSI: {info or 'nothing'}). Connect normal adapters without 'box:'.")
        kinds = re.search(r"KINDS=([A-Z,]+)", info)
        listen = re.search(r"LISTEN=(\d)", info)
        word_to_kind = {v: k for k, v in _KIND_WORD.items()}
        self.capabilities = Capabilities(
            "evsoc-Box",
            {word_to_kind[w] for w in kinds.group(1).split(",") if w in word_to_kind} if kinds else {"can"},
            None,
            listen=not listen or listen.group(1) == "1",
        )
        self.version = info
        self._bus = None

    def reset_fast(self) -> None:
        super().reset_fast()
        self._bus = None  # ATD puts the box back to CAN on 6/14

    def select_bus(self, bus: Bus) -> None:
        """Switch transceiver, pins and mode; nothing is sent if the bus is already active."""
        if bus == self._bus:
            return
        if bus.kind == "doip":
            raise AdapterError("DoIP over the evsoc box is planned in the protocol but not yet in evsoc (use enet:// for BMW/Mini)")
        for cmd in (bus_command(bus), f"EVSLISTEN {1 if bus.listen_only else 0}"):
            lines = self._send(cmd)
            if any(l.startswith(("ERR", "?")) for l in lines):
                raise AdapterError(f"The box refuses {cmd!r}: {' '.join(lines)}")
        self._bus = bus

    def scan(self, timeout: float = 30.0) -> list[dict]:
        """Ask the box to look for active buses (listen-only on every pin pair and bitrate)."""
        lines = self._send("EVSSCAN", timeout=timeout)
        found = []
        for line in lines:
            m = re.match(r"BUS (\w+) ([\d,]+) (\d+)(?: FRAMES=(\d+))?(?: IDS=([\dA-F,]+))?", line)
            if m:
                found.append({
                    "kind": m.group(1).lower(), "pins": tuple(int(p) for p in m.group(2).split(",")),
                    "bitrate": int(m.group(3)), "frames": int(m.group(4) or 0),
                    "ids": m.group(5).split(",") if m.group(5) else [],
                })
        self._bus = None
        return found
