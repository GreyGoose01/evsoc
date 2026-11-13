"""A fake ELM327 with recorded vehicle answers, for trying evsoc without a car.

Corsa-e: Car Scanner log (wican-fw#279). BMW i3 22DDBC: OVMS mailing list; 226335 and
22DFA0: OBDb BMW-i3 captures (2019). ID.4 battery values (1E3B, 2A0B, 2AB2, 2AB8): OBDb
Volkswagen-ID.4 captures (2023). BMW iX3 22E5CE and the all-zero 22DDBC: OBDb BMW-iX3/i5
captures. Megane E-Tech (OBD over 29 bit): OBDb Renault-Megane-E-Tech captures (2025).
Ioniq 5, the ID.4 SoC, bZ4X, ë-C3, Tesla, "hybrid", "psa-phev" and the Corsa-e temperatures are synthetic but
follow the documented layouts. smart-ed: example frames from the OVMS source.
"""

from __future__ import annotations

from .elm import isotp_segment


def _ioniq5_0101() -> str:
    data = bytearray(56)
    data[4] = 160                    # SoC BMS 80.0 % (data byte 4, OBDb bix 32 / WiCAN B10)
    data[12:14] = (7000).to_bytes(2, "big")
    return "620101" + data.hex()


def _ioniq5_0105() -> str:
    data = bytearray(44)
    data[31] = 158                   # SoC display 79.0 % (data byte 31, OBDb bix 248 / WiCAN B41)
    return "620105" + data.hex()


# vehicle -> {(request header, CAN extended address, request): (response id, payload hex)}
VEHICLES: dict[str, dict[tuple[str, int | None, str], tuple[str, str]]] = {
    "corsa-e": {
        ("6B4", None, "22D410"): ("694", "62D4109FEB"),
        ("6B4", None, "22D810"): ("694", "62D8109FEB"),
        ("6B4", None, "22D815"): ("694", "62D8151AA4"),
        ("6B4", None, "22D86F"): ("694", "62D86F0F5F"),
        ("6B4", None, "22D870"): ("694", "62D8700F6F"),
        ("6B4", None, "22D860"): ("694", "62D8600105DD"),     # SoH 93.8 %
        ("6B4", None, "22D816"): ("694", "62D81600012C00"),   # 0 A (parked)
        ("6B4", None, "22D865"): ("694", "62D8650886"),       # 34.1 kWh
        ("6B4", None, "22D87D"): ("694", "62D87D3D"),         # 21 °C min   (synthetic, PSA-RE layout)
        ("6B4", None, "22D817"): ("694", "62D8173F"),         # 23 °C max   (synthetic)
        ("6B4", None, "22D877"): ("694", "62D8773E"),         # 22 °C mean  (synthetic)
        # control unit identification and fault memory (synthetic): P0A7F-00 stored, U0111-87 active
        ("6B4", None, "22F080"): ("694", "62F080" + b"9836785380".hex()),
        ("6B4", None, "22F18C"): ("694", "62F18C" + b"BMU0012345".hex()),
        ("6B4", None, "1902FF"): ("694", "5902FF" "0A7F0008" "C1118709"),
    },
    "psa-phev": {  # same address as the Corsa-e, other scaling (PSA-RE TBMU_PHEV); no answer to 22D410
        ("6B4", None, "22D810"): ("694", "62D81000C8"),       # 50.0 %
        ("6B4", None, "22D815"): ("694", "62D8150550"),       # 340 V
        ("6B4", None, "22D816"): ("694", "62D816FFE2"),       # -12 A
        ("6B4", None, "22D860"): ("694", "62D8600180"),       # SoH 96 %
        ("6B4", None, "22D86F"): ("694", "62D86FBD"),         # 3.78 V
        ("6B4", None, "22D870"): ("694", "62D870BE"),         # 3.80 V
        ("6B4", None, "22D817"): ("694", "62D81718"),         # 24 °C
        ("6B4", None, "22D87D"): ("694", "62D87D16"),         # 22 °C
        ("7DF", None, "0902"): ("7E8", "490201" + b"VR3ATTENTKY000001".hex()),
    },
    "bmw-i3": {
        ("6F1", 0x07, "22DDBC"): ("607", "62DDBC024C03A60069"),
        ("6F1", 0x07, "226335"): ("607", "62633500000054"),         # SoH 84 %
        ("6F1", 0x07, "22DFA0"): ("607", "62DFA0" "212521BB2162959E95E295BD07CE0896081BFFFFFFFF2A33"
                                         "153015CC1560FFFFFFFFFFFF2A33"),  # cells 84.85 / 86.35 / 85.46 Ah
    },
    "ioniq5": {
        ("7E4", None, "220101"): ("7EC", _ioniq5_0101()),
        ("7E4", None, "220105"): ("7EC", _ioniq5_0105()),
        ("7DF", None, "0902"): ("7E8", "490201" + b"KMHKN81AFPU123456".hex()),
    },
    "id4": {
        ("FC0076", None, "223DEF"): ("17FE0076", "623DEF1F40"),   # 80.00 %
        ("FC007B", None, "22028C"): ("17FE007B", "62028CB4"),
        ("FC007B", None, "221E3B"): ("17FE007B", "621E3B05FF"),   # 383.75 V
        ("FC007B", None, "222A0B"): ("17FE007B", "622A0B3C"),     # -10 °C
        ("710", None, "222AB2"): ("77A", "622AB205BC0400"),         # max. energy content 73.4 kWh
        ("710", None, "222AB8"): ("77A", "622AB80000058000000000"), # energy content 35.2 kWh
    },
    "bmw-ix3": {
        ("6F1", 0x07, "22E5CE"): ("607", "62E5CE21EE21D921FD"),     # 86.86 %
        ("6F1", 0x07, "22DDBC"): ("607", "62DDBC000000000000"),     # Gen5: always zero
        ("6F1", 0x07, "22DDC0"): ("607", "62DDC00B8F0C140BCF01"),   # cells 29.59 / 30.92 °C (i5 2024)
    },
    "megane": {
        ("DB33F1", None, "015B"): ("18DAF1DA", "415B77"),           # 46.7 %
        ("DB33F1", None, "019A"): ("18DAF1DA", "419A0E005D40000D"), # 373 V
        ("DB33F1", None, "01B2"): ("18DAF1DA", "41B2FC"),           # SoH 98.8 %
    },
    "bz4x": {
        ("745", None, "221738"): ("74D", "62173850"),               # 80 %
        ("747", None, "221F5B"): ("74F", "621F5BBE"),               # 74.5 %
        ("747", None, "221D3E"): ("74F", "621D3E" + "4A38" * 8),    # 8 x 190.00 Ah
    },
    "e-c3": {
        ("7E0", None, "222002"): ("7E8", "622002CC"),               # 80 % (A/2.55)
        ("7E7", None, "224801"): ("7EF", "6248011F72"),             # 80.50 %
    },
    "hybrid": {
        ("7DF", None, "015B"): ("7E8", "415B9C"),
        ("7DF", None, "03"): ("7E8", "43010A80"),                  # one stored code: P0A80
        ("7DF", None, "07"): ("7E8", "4700"),
        ("7DF", None, "0902"): ("7E8", "490201" + b"JTDKB3U6007000001".hex()),
    },
}

# Broadcast frames heard in monitor mode (ATMA), per vehicle.
BROADCAST: dict[str, dict[str, str]] = {
    # Tesla Model 3 0x292: SOCmin 79.0, SOCUI 80.0, SOCmax 81.0, SOCave 80.5 (10-bit little endian fields)
    "tesla-m3": {"292": ((790 | (800 << 10) | (810 << 20) | (805 << 30)).to_bytes(8, "little")).hex().upper()},
    # smart electric drive 451: the example frames from OVMS vehicle_smarted (83.5 % shown, 83.2 % BMS)
    "smart-ed": {"518": "01240000F87FC8A7", "2D5": "00004F1403400000"},
}


class MockElmTransport:
    """`voltage` is what ATRV reports; below `awake_voltage` the simulated car sleeps (NO DATA)."""

    def __init__(self, vehicle: str, voltage: float = 13.9, awake_voltage: float = 13.0, wakeable: bool = False):
        if vehicle not in VEHICLES and vehicle not in BROADCAST:
            raise ValueError(f"Unknown test vehicle {vehicle!r}, available: {', '.join([*VEHICLES, *BROADCAST])}")
        self.table = VEHICLES.get(vehicle, {})
        self.broadcast = BROADCAST.get(vehicle, {})
        self.sent: list[str] = []
        self.voltage = voltage
        self.awake_voltage = awake_voltage
        self.wakeable = wakeable  # a sleeping car wakes from the first request and answers the next ones
        self._woken = False
        self._out = b""
        self._monitoring = False
        self._reset()

    def _reset(self) -> None:
        self.header = "7DF"
        self.cea: int | None = None
        self.cra = ""

    def write(self, data: bytes) -> None:
        if self._monitoring:
            self._monitoring = False
            self._out += b"\r>"
            return
        for raw in data.decode("ascii").split("\r"):
            cmd = raw.replace(" ", "").upper()
            if not cmd:
                continue
            self.sent.append(cmd)
            if cmd == "ATMA":
                self._monitoring = True
                for can_id, payload in self.broadcast.items():
                    if not self.cra or self.cra == can_id:
                        self._out += f"{can_id}{payload}\r".encode() * 3
                continue
            self._out += (self._handle(cmd) + "\r\r>").encode("ascii")

    def _handle(self, cmd: str) -> str:
        if cmd in ("ATZ", "ATWS", "ATD"):
            self._reset()
            return "ELM327 v2.2" if cmd != "ATD" else "OK"
        if cmd == "ATI":
            return "ELM327 v2.2 (evsoc mock)"
        if cmd == "ATRV":
            return f"{self.voltage:.1f}V"
        if cmd.startswith("ATSH"):
            self.header = cmd[4:]
            return "OK"
        if cmd.startswith("ATCEA"):
            self.cea = int(cmd[5:], 16) if len(cmd) > 5 else None
            return "OK"
        if cmd.startswith("ATCRA"):
            self.cra = cmd[5:]
            return "OK"
        if cmd.startswith("AT"):
            return "OK"
        if self.voltage < self.awake_voltage and not self._woken:
            self._woken = self.wakeable
            return "NO DATA"  # control units asleep
        hit = self.table.get((self.header, self.cea, cmd))
        if hit is None:
            return "NO DATA"
        resp_id, payload = hit
        tester = int(self.header, 16) & 0xFF if self.cea is not None else None
        frames = isotp_segment(bytes.fromhex(payload), tester)
        return "\r".join(resp_id + f.hex().upper() for f in frames)

    def read(self, timeout: float) -> bytes:
        out, self._out = self._out, b""
        return out

    def close(self) -> None:
        pass


def _leaf_2101() -> str:
    data = bytearray(40)
    data[18:20] = (36000).to_bytes(2, "big")      # 360.00 V (OBDb: bix 144, /100)
    data[29:32] = (650000).to_bytes(3, "big")     # 65.0 % (OBDb: bix 232, 24 bit, /10000)
    return "6101" + data.hex()


# Simulated cars for the evsoc box: OBD pins -> what is on that bus.
BOX_CARS: dict[str, dict[tuple[int, ...], dict]] = {
    "leaf": {
        (6, 14): {"bitrate": 500_000, "table": {("79B", None, "2101"): ("7BB", _leaf_2101())},
                  "broadcast": {"5C0": "0000000000000000"}},                     # Car-CAN
        (12, 13): {"bitrate": 500_000, "table": {},
                   "broadcast": {"55B": "A200000000000000"}},                    # EV-CAN: SoC 64.8 %
        (3, 11): {"bitrate": 500_000, "table": {}, "broadcast": {"5A9": "0000000000000000"}},  # AV-CAN
    },
    "corsa-e": {(6, 14): {"bitrate": 500_000, "table": VEHICLES["corsa-e"], "broadcast": {}}},
}


class MockBoxTransport(MockElmTransport):
    """The evsoc box: ELM327 plus EVS commands for choosing pins and bus type."""

    def __init__(self, car: str, voltage: float = 13.9):
        if car not in BOX_CARS:
            raise ValueError(f"Unknown box test vehicle {car!r}, available: {', '.join(BOX_CARS)}")
        self.buses = BOX_CARS[car]
        super().__init__("corsa-e", voltage=voltage)
        self.bus_cmds: list[str] = []
        self.listen_only = False
        self._select((6, 14))

    def _select(self, pins: tuple[int, ...]) -> None:
        self.pins = pins
        bus = self.buses.get(pins, {"table": {}, "broadcast": {}})
        self.table, self.broadcast = bus["table"], bus["broadcast"]

    def write(self, data: bytes) -> None:
        text = data.decode("ascii")
        if not self._monitoring and text.upper().startswith("EVS"):
            line = text.strip().upper()
            self.sent.append(line)
            self._out += (self._evs(line.split()) + "\r\r>").encode("ascii")
            return
        super().write(data)

    def _evs(self, words: list[str]) -> str:
        cmd = words[0]
        if cmd == "EVSI":
            return "EVSOC-BOX 0.1 KINDS=CAN,CANFD,KLINE,SWCAN,DOIP PINS=ANY LISTEN=1"
        if cmd == "EVSBUS" and len(words) >= 3:
            self.bus_cmds.append(" ".join(words))
            self._select(tuple(int(p) for p in words[2].split(",")))
            return "OK"
        if cmd == "EVSLISTEN" and len(words) == 2:
            self.listen_only = words[1] == "1"
            return "OK"
        if cmd == "EVSSCAN":
            lines = []
            for pins, bus in self.buses.items():
                ids = sorted(set(bus["broadcast"]) | {resp for resp, _ in bus["table"].values()})
                lines.append(f"BUS CAN {','.join(map(str, pins))} {bus['bitrate']} FRAMES={len(ids) * 50} IDS={','.join(ids)}")
            self._select((6, 14))
            return "\r".join(lines + ["OK"])
        return "?"

    def _handle(self, cmd: str) -> str:
        if cmd in ("ATZ", "ATD", "ATWS"):
            self._select((6, 14))
            self.listen_only = False
        if self.listen_only and not cmd.startswith("AT"):
            return "ERR LISTEN-ONLY"
        return super()._handle(cmd)
