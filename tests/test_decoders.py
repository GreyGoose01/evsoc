import pytest

from evsoc.decoders import BitsDecoder, DbcDecoder, Response, WicanDecoder, make_decoder
from evsoc.elm import isotp_segment
from evsoc.equation import EquationError


def wican(expr, raw):
    return WicanDecoder(expr)(Response(b"", raw))


def test_wican_counts_pci_bytes():
    # Corsa-e single frame "05 62 D4 10 6D 9D": B0 is the ISO-TP length byte
    raw = bytes.fromhex("0562D4106D9D")
    assert wican("[B4:B5]/512", raw) == pytest.approx(28061 / 512)


def test_wican_and_obdb_agree_on_multiframe():
    # data byte 31 after "62 01 05" sits at WiCAN B41 (PCI bytes of 5 frames in between)
    data = bytearray(44)
    data[31] = 158
    raw = b"".join(isotp_segment(bytes.fromhex("620105") + bytes(data)))
    assert wican("B41/2", raw) == 79.0
    assert BitsDecoder({"bix": 248, "len": 8, "div": 2})(Response(bytes(data))) == 79.0


@pytest.mark.parametrize(
    "expr,raw,expected",
    [
        ("B3:2", bytes([0, 0, 0, 0b100]), 1),
        ("S1", bytes([0, 0xFF]), -1),
        ("[S0:S1]/10", bytes([0xFF, 0x9C]), -10.0),
        ("(65536-([B0:B1]))/10", bytes([0xFF, 0x9C]), 10.0),
        ("B0+B1*2", bytes([1, 2]), 5),          # * before +
        ("B0<<8|B1", bytes([1, 2]), 258),        # WiCAN: << before |
        ("-B0+3", bytes([1]), 2),
    ],
)
def test_wican_expressions(expr, raw, expected):
    assert wican(expr, raw) == pytest.approx(expected)


def test_wican_missing_byte():
    with pytest.raises(EquationError, match="missing"):
        wican("B9", bytes(3))


def test_wican_syntax_error_at_load():
    with pytest.raises(EquationError):
        WicanDecoder("B1 $ 2")


@pytest.mark.parametrize(
    "spec,data,expected",
    [
        ({"len": 16, "div": 512}, bytes.fromhex("6D9D"), 28061 / 512),
        ({"bix": 4, "len": 4}, bytes([0xAB]), 0xB),
        ({"len": 16, "sign": True, "div": 100}, bytes.fromhex("FF38"), -2.0),
        ({"len": 16, "blsb": True}, bytes.fromhex("3412"), 0x1234),
        ({"len": 8, "mul": 20.4, "div": 46, "add": -6.4}, bytes([180]), 180 * 20.4 / 46 - 6.4),
    ],
)
def test_bits(spec, data, expected):
    assert BitsDecoder(spec)(Response(data)) == pytest.approx(expected)


def test_bits_null_values():
    assert BitsDecoder({"len": 8, "nullmax": 255})(Response(bytes([255]))) is None


def test_dbc_little_endian_tesla():
    frame = (790 | (800 << 10) | (810 << 20) | (805 << 30)).to_bytes(8, "little")
    soc_ui = DbcDecoder({"start": 10, "len": 10, "little": True, "factor": 0.1})
    assert soc_ui(Response(frame)) == pytest.approx(80.0)


def test_unknown_decoder_type():
    with pytest.raises(EquationError):
        make_decoder({"type": "magic"})
