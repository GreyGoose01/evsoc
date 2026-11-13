"""Value decoders for the profile formats evsoc understands.

  equation  Torque / ABRP syntax on the data bytes (A = first byte after SID + DID)
  wican     WiCAN syntax on the raw CAN bytes of all frames (B0 = first byte after the CAN id,
            ISO-TP PCI bytes included)
  bits      OBDb bit field on the data bytes (bix = bit offset, MSB first)
  dbc       DBC-style signal on one broadcast CAN frame (for passive listening, e.g. Tesla)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .equation import Equation, EquationError


@dataclass
class Response:
    data: bytes          # payload after SID + DID echo (or the broadcast frame for listening)
    raw: bytes = b""     # concatenated raw CAN frame bytes (WiCAN indexing)


class Decoder:
    text: str

    def __call__(self, resp: Response) -> float | None:
        raise NotImplementedError


class EquationDecoder(Decoder):
    def __init__(self, expr: str):
        self.text = expr
        self._eq = Equation(expr)

    def __call__(self, resp: Response) -> float | None:
        return self._eq(resp.data)


# -- WiCAN -------------------------------------------------------------------

_W_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<num>\d+\.\d*|\.\d+|\d+)"
    r"|\[(?P<rk>[BS])(?P<r1>\d+):[BS](?P<r2>\d+)\]"
    r"|(?P<bk>[BS])(?P<bi>\d+)(?::(?P<bit>\d))?"
    r"|(?P<op><<|>>|[-+*/&|^()])"
    r")"
)
_W_PREC = {"|": 1, "^": 1, "&": 2, "<<": 3, ">>": 3, "+": 4, "-": 4, "*": 5, "/": 5}


def _w_apply(op: str, a: float, b: float) -> float:
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if op == "/":
        if b == 0:
            raise EquationError("Division by zero")
        return a / b
    ia, ib = int(a), int(b)
    return float({"&": ia & ib, "|": ia | ib, "^": ia ^ ib, "<<": ia << ib, ">>": ia >> ib}[op])


class WicanDecoder(Decoder):
    def __init__(self, expr: str):
        self.text = expr
        self._tokens = []
        pos, s = 0, expr.strip()
        while pos < len(s):
            m = _W_TOKEN.match(s, pos)
            if not m or m.end() == pos:
                raise EquationError(f"WiCAN-Ausdruck {expr!r}: unerwartetes Zeichen an Position {pos}")
            self._tokens.append(m)
            pos = m.end()
        self._parse_check()

    def _parse_check(self) -> None:
        # Evaluate once against dummy bytes so syntax errors surface at load time.
        try:
            self._eval(bytes([1]) * 4096)
        except EquationError as e:
            if "Division" not in str(e):
                raise

    def __call__(self, resp: Response) -> float | None:
        return self._eval(resp.raw)

    def _byte(self, raw: bytes, i: int) -> int:
        if i >= len(raw):
            raise EquationError(f"Byte B{i} missing (only {len(raw)} bytes received)")
        return raw[i]

    def _eval(self, raw: bytes) -> float:
        out: list[float] = []
        ops: list[str] = []
        prev_operand = False

        def reduce() -> None:
            op = ops.pop()
            if op == "neg":
                out.append(-out.pop())
                return
            b, a = out.pop(), out.pop()
            out.append(_w_apply(op, a, b))

        for m in self._tokens:
            if m.group("num"):
                out.append(float(m.group("num")))
                prev_operand = True
            elif m.group("rk"):
                lo, hi = int(m.group("r1")), int(m.group("r2"))
                value = 0
                for i in range(lo, hi + 1):
                    value = (value << 8) | self._byte(raw, i)
                if m.group("rk") == "S":
                    bits = 8 * (hi - lo + 1)
                    if value >= 1 << (bits - 1):
                        value -= 1 << bits
                out.append(float(value))
                prev_operand = True
            elif m.group("bk"):
                v = self._byte(raw, int(m.group("bi")))
                if m.group("bk") == "S":
                    v = v - 256 if v > 127 else v
                elif m.group("bit") is not None:
                    v = (v >> int(m.group("bit"))) & 1
                out.append(float(v))
                prev_operand = True
            else:
                op = m.group("op")
                if op == "(":
                    ops.append(op)
                    prev_operand = False
                elif op == ")":
                    while ops and ops[-1] != "(":
                        reduce()
                    if not ops:
                        raise EquationError(f"Klammerfehler in {self.text!r}")
                    ops.pop()
                    prev_operand = True
                elif op == "-" and not prev_operand:
                    ops.append("neg")
                else:
                    while ops and ops[-1] != "(" and (ops[-1] == "neg" or _W_PREC[ops[-1]] >= _W_PREC[op]):
                        reduce()
                    ops.append(op)
                    prev_operand = False
        while ops:
            if ops[-1] == "(":
                raise EquationError(f"Klammerfehler in {self.text!r}")
            reduce()
        if len(out) != 1:
            raise EquationError(f"Invalid WiCAN expression {self.text!r}")
        return out[0]


# -- OBDb bit fields ------------------------------------------------------------

class BitsDecoder(Decoder):
    def __init__(self, spec: dict):
        self.bix = int(spec.get("bix", 0))
        self.len = int(spec["len"])
        self.blsb = bool(spec.get("blsb", False))
        self.sign = bool(spec.get("sign", False))
        self.mul = float(spec.get("mul", 1))
        self.div = float(spec.get("div", 1))
        self.add = float(spec.get("add", 0))
        self.nullmin = spec.get("nullmin")
        self.nullmax = spec.get("nullmax")
        parts = [f"bits[{self.bix}:+{self.len}]"]
        if self.mul != 1: parts.append(f"*{self.mul:g}")
        if self.div != 1: parts.append(f"/{self.div:g}")
        if self.add: parts.append(f"{self.add:+g}")
        self.text = "".join(parts) + (" signed" if self.sign else "") + (" lsb" if self.blsb else "")

    def __call__(self, resp: Response) -> float | None:
        data = bytearray(resp.data)
        end = self.bix + self.len
        if end > len(data) * 8:
            raise EquationError(f"Answer too short: {end} bits needed, {len(data) * 8} present")
        if self.blsb and self.len > 8:
            start_byte = self.bix // 8
            count = (self.len + 7) // 8
            data[start_byte : start_byte + count] = bytes(reversed(data[start_byte : start_byte + count]))
        raw = 0
        for i in range(self.bix, end):
            if data[i // 8] & (1 << (7 - i % 8)):
                raw |= 1 << (end - i - 1)
        if self.sign and raw & (1 << (self.len - 1)):
            raw -= 1 << self.len
        value = raw * self.mul / self.div + self.add
        if self.nullmin is not None and value <= float(self.nullmin):
            return None
        if self.nullmax is not None and value >= float(self.nullmax):
            return None
        return value


# -- DBC signals on broadcast frames ----------------------------------------------

class DbcDecoder(Decoder):
    def __init__(self, spec: dict):
        self.start = int(spec["start"])
        self.len = int(spec["len"])
        self.little = bool(spec.get("little", True))
        self.signed = bool(spec.get("signed", False))
        self.factor = float(spec.get("factor", 1))
        self.offset = float(spec.get("offset", 0))
        self.text = f"dbc {self.start}|{self.len}@{1 if self.little else 0} ({self.factor:g},{self.offset:g})"

    def __call__(self, resp: Response) -> float | None:
        frame = resp.data
        if self.little:
            raw = (int.from_bytes(frame, "little") >> self.start) & ((1 << self.len) - 1)
        else:  # Motorola: start = MSB position in DBC numbering
            bits = "".join(f"{b:08b}" for b in frame)
            msb = (self.start // 8) * 8 + (7 - self.start % 8)
            raw = int(bits[msb : msb + self.len], 2)
        if self.signed and raw & (1 << (self.len - 1)):
            raw -= 1 << self.len
        return raw * self.factor + self.offset


DECODERS: dict[str, Callable[[dict], Decoder]] = {
    "equation": lambda s: EquationDecoder(s["expr"]),
    "wican": lambda s: WicanDecoder(s["expr"]),
    "bits": BitsDecoder,
    "dbc": DbcDecoder,
}


def make_decoder(spec: dict) -> Decoder:
    kind = spec.get("type", "equation")
    if kind not in DECODERS:
        raise EquationError(f"Unbekannter Decoder-Typ {kind!r}")
    return DECODERS[kind](spec)
