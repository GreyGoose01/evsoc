"""Safe evaluator for Torque / ABRP style PID equations.

Variables name response bytes: A..Z, AA..ZZ, AAA..ZZZ (case-insensitive),
where A is the first data byte after the positive-response SID and the DID
echo. Supported: + - * / << >> < > <= >= == != && || !, parentheses,
Signed(x), Int16(a,b), Int24(a,b,c), Int32(a,b,c,d) (',' or ':' as
separator) and bit access {A:n}.

Equations are compiled to closures once; nothing is passed to eval().
"""

from __future__ import annotations

import re
from collections.abc import Callable

Data = bytes
Node = Callable[[Data], float]


class EquationError(ValueError):
    pass


_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<num>\d+\.\d*|\.\d+|\d+)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op><<|>>|<=|>=|==|!=|&&|\|\||[-+*/()<>!:,{}])"
    r")"
)


def _div(a: float, b: float) -> float:
    if b == 0:
        raise EquationError("Division by zero")
    return a / b


# Binary operators by precedence (C-like, loosest first).
_LEVELS: list[dict[str, Callable[[float, float], float]]] = [
    {"||": lambda a, b: float(bool(a) or bool(b))},
    {"&&": lambda a, b: float(bool(a) and bool(b))},
    {"==": lambda a, b: float(a == b), "!=": lambda a, b: float(a != b)},
    {
        "<": lambda a, b: float(a < b),
        ">": lambda a, b: float(a > b),
        "<=": lambda a, b: float(a <= b),
        ">=": lambda a, b: float(a >= b),
    },
    {"<<": lambda a, b: float(int(a) << int(b)), ">>": lambda a, b: float(int(a) >> int(b))},
    {"+": lambda a, b: a + b, "-": lambda a, b: a - b},
    {"*": lambda a, b: a * b, "/": _div},
]


def _signed(x: float) -> float:
    x = int(x) & 0xFF
    return float(x - 256 if x > 127 else x)


def _joiner(n: int) -> Callable[..., float]:
    def join(*parts: float) -> float:
        if len(parts) != n:
            raise EquationError(f"Int{8 * n} expects {n} arguments")
        value = 0
        for p in parts:
            value = (value << 8) | (int(p) & 0xFF)
        return float(value)

    return join


_FUNCS: dict[str, Callable[..., float]] = {
    "signed": _signed,
    "int16": _joiner(2),
    "int24": _joiner(3),
    "int32": _joiner(4),
}


def byte_index(name: str) -> int | None:
    """A -> 0, Z -> 25, AA -> 26, ZZ -> 701, AAA -> 702 (bijective base 26)."""
    if not (1 <= len(name) <= 3 and name.isalpha()):
        return None
    value = 0
    for ch in name.upper():
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value - 1


def _var(idx: int, name: str) -> Node:
    def get(data: Data) -> float:
        if idx >= len(data):
            raise EquationError(f"Byte {name} missing (the answer has only {len(data)} bytes)")
        return float(data[idx])

    return get


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens: list[tuple[str, str]] = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m or m.end() == pos:
                raise EquationError(f"Unerwartetes Zeichen in {text!r} an Position {pos}")
            kind = m.lastgroup
            assert kind is not None
            self.tokens.append((kind, m.group(kind)))
            pos = m.end()
            while pos < len(text) and text[pos].isspace():
                pos += 1
        self.i = 0

    def peek(self) -> str | None:
        return self.tokens[self.i][1] if self.i < len(self.tokens) else None

    def take(self, expected: str | None = None) -> tuple[str, str]:
        if self.i >= len(self.tokens):
            raise EquationError(f"Unexpected end in {self.text!r}")
        tok = self.tokens[self.i]
        if expected is not None and tok[1] != expected:
            raise EquationError(f"{expected!r} expected, {tok[1]!r} found in {self.text!r}")
        self.i += 1
        return tok

    def parse(self) -> Node:
        node = self.binary(0)
        if self.i != len(self.tokens):
            raise EquationError(f"Extra characters from {self.peek()!r} in {self.text!r}")
        return node

    def binary(self, level: int) -> Node:
        if level == len(_LEVELS):
            return self.unary()
        ops = _LEVELS[level]
        left = self.binary(level + 1)
        while self.peek() in ops:
            fn = ops[self.take()[1]]
            right = self.binary(level + 1)
            left = (lambda f, l, r: lambda d: f(l(d), r(d)))(fn, left, right)
        return left

    def unary(self) -> Node:
        tok = self.peek()
        if tok == "-":
            self.take()
            inner = self.unary()
            return lambda d: -inner(d)
        if tok == "+":
            self.take()
            return self.unary()
        if tok == "!":
            self.take()
            inner = self.unary()
            return lambda d: float(not inner(d))
        return self.primary()

    def primary(self) -> Node:
        kind, tok = self.take()
        if kind == "num":
            value = float(tok)
            return lambda d: value
        if tok == "(":
            node = self.binary(0)
            self.take(")")
            return node
        if tok == "{":
            byte = self.primary()
            self.take(":")
            _, bit_tok = self.take()
            bit = int(bit_tok)
            self.take("}")
            return lambda d: float((int(byte(d)) >> bit) & 1)
        if kind == "name":
            if self.peek() == "(":
                fn = _FUNCS.get(tok.lower())
                if fn is None:
                    raise EquationError(f"Unknown function {tok!r}")
                self.take("(")
                args = [self.binary(0)]
                while self.peek() in (",", ":"):
                    self.take()
                    args.append(self.binary(0))
                self.take(")")
                return lambda d: fn(*(a(d) for a in args))
            idx = byte_index(tok)
            if idx is None:
                raise EquationError(f"Unknown variable {tok!r}")
            return _var(idx, tok)
        raise EquationError(f"Unerwartetes {tok!r} in {self.text!r}")


class Equation:
    def __init__(self, text: str):
        self.text = text
        self._node = _Parser(text).parse()

    def __call__(self, data: bytes) -> float:
        return self._node(data)

    def __repr__(self) -> str:
        return f"Equation({self.text!r})"
