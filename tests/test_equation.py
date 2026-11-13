import pytest

from evsoc.equation import Equation, EquationError, byte_index
from evsoc.profiles import load_all


@pytest.mark.parametrize("name,idx", [("A", 0), ("Z", 25), ("AA", 26), ("af", 31), ("AZ", 51), ("BA", 52), ("ZZ", 701), ("AAA", 702)])
def test_byte_index(name, idx):
    assert byte_index(name) == idx


@pytest.mark.parametrize(
    "eq,data,expected",
    [
        ("INT16(A:B)*0.1", bytes([0x02, 0x4C]), 58.8),
        ("INT16(A,B)/512", bytes([0x6D, 0x9D]), 28061 / 512),
        ("A*100/255", bytes([255]), 100),
        ("-0.01*((signed(C)*256)+D)", bytes([0, 0, 0xFF, 0x9C]), 1.0),
        ("{A:2}", bytes([0b100]), 1),
        ("{A:1}&&{A:2}", bytes([0b010]), 0),
        ("(!{A:2}&&{A:3})", bytes([0b1000]), 1),
        ("(A==6)&&((B==11)||(B==12))", bytes([6, 12]), 1),
        ("((A<<8)+B)", bytes([1, 2]), 258),
        ("1+2*3", b"", 7),
        ("(1+2)*3", b"", 9),
        ("A<<1+1", bytes([1]), 4),  # C precedence: + binds tighter than <<
        ("1.12*A/2.5-7.16", bytes([200]), 1.12 * 200 / 2.5 - 7.16),
    ],
)
def test_evaluate(eq, data, expected):
    assert Equation(eq)(data) == pytest.approx(expected)


def test_missing_byte():
    with pytest.raises(EquationError, match="missing"):
        Equation("C")(bytes([1, 2]))


@pytest.mark.parametrize("bad", ["__import__('os')", "A +", "foo(A)", "A ; B", "{A}"])
def test_rejects_garbage(bad):
    with pytest.raises(EquationError):
        Equation(bad)


def test_all_profiles_load():
    profiles = load_all()
    assert len(profiles) > 200
    assert {"evsoc_stellantis_ecmp", "evsoc_bmw_sme", "evsoc_generic_obd", "evsoc_tesla_model3y"} <= set(profiles)
    for p in profiles.values():
        assert p.soc_fields, p.name
        for f in p.fields.values():
            assert f.step in p.steps
