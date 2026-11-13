import pytest

from evsoc.cli import main
from evsoc.connection import CATALOG, PINS, Bus, bus_for_step, buses, capabilities_of, check, recommend
from evsoc.elm import AdapterError, ElmAdapter
from evsoc.mock import MockBoxTransport, MockElmTransport
from evsoc.profiles import load_all, parse_profile
from evsoc.reader import autodetect, read, run_init
from evsoc.universal import UniversalAdapter, bus_command


@pytest.fixture(scope="module")
def profiles():
    return load_all()


def by_name(name):
    return next(c for c in CATALOG if c.name.startswith(name))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("evsoc_stellantis_ecmp", Bus("can", (6, 14), 500_000, 11)),
        ("evsoc_bmw_sme", Bus("can", (6, 14), 500_000, 11)),           # ATPBE101 + ATSPB
        ("abrp_meb", Bus("can", (6, 14), 500_000, 29)),
        ("evsoc_nissan_leaf_evcan", Bus("can", (12, 13), 500_000, 11, listen_only=True)),
    ],
)
def test_bus_derivation(profiles, name, expected):
    assert buses(profiles[name]) == [expected]


def test_cable_and_fd_overrides():
    tesla = load_all()["evsoc_tesla_model3y"]
    assert "Tesla" in buses(tesla)[0].cable
    d = {"name": "x", "connection": {"fd": True, "data_bitrate": 2_000_000},
         "steps": [{"id": "s", "at": ["ATSP6"], "request": "220101"}],
         "fields": {"soc": {"step": "s", "decode": {"type": "equation", "expr": "A"}}}}
    p = parse_profile(d)
    bus = bus_for_step(p, p.steps["s"])
    assert bus.kind == "canfd" and bus.data_bitrate == 2_000_000 and bus.pins == PINS["can"]
    assert "CAN-FD" in bus.describe()


def test_adapter_compatibility(profiles):
    leaf = profiles["evsoc_nissan_leaf_evcan"]
    assert check(leaf, by_name("ELM327")) and check(leaf, by_name("OBDLink MX"))
    assert check(leaf, by_name("evsoc box")) == []
    enet = by_name("BMW ENET")
    assert check(profiles["evsoc_bmw_sme"], enet) == []
    assert check(profiles["obdb_lexus"], enet)                 # extended addressing, but not BMW
    assert check(profiles["evsoc_stellantis_ecmp"], enet)
    ok = [c.name for c, problems in recommend(profiles["evsoc_stellantis_ecmp"]) if not problems]
    assert "OBDLink CX (BLE)" in ok and "BMW ENET cable" not in ok


def test_can_interface_with_leaf_cable(profiles):
    can = pytest.importorskip("can")
    from evsoc.canbus import CanAdapter
    a = CanAdapter("virtual", "evsoc-pins", bus=can.Bus(interface="virtual", channel="evsoc-pins"), pins=(12, 13))
    assert check(profiles["evsoc_nissan_leaf_evcan"], capabilities_of(a)) == []
    assert check(profiles["evsoc_stellantis_ecmp"], capabilities_of(a))  # that cable no longer reaches 6/14
    a.close()


def test_bus_commands():
    assert bus_command(Bus("can", (12, 13), 500_000, 11)) == "EVSBUS CAN 12,13 500000"
    assert bus_command(Bus("canfd", (6, 14), 500_000, 11, 2_000_000)) == "EVSBUS CANFD 6,14 500000 2000000"
    assert bus_command(Bus("doip", PINS["doip2"])) == "EVSBUS DOIP 2"


def box(car="leaf"):
    t = MockBoxTransport(car)
    a = UniversalAdapter(t)
    a.reset()
    return t, a


def test_box_switches_pins_per_profile(profiles):
    t, a = box()
    p = profiles["evsoc_nissan_leaf_evcan"]
    run_init(a, p)
    assert read(a, p).values["soc_bms"].value == pytest.approx(64.8)
    assert t.bus_cmds[-1] == "EVSBUS CAN 12,13 500000" and t.listen_only
    p = profiles["obdb_nissan_leaf"]
    run_init(a, p)
    assert read(a, p, ["soc"], year=2015).values["soc"].value == pytest.approx(65.0)
    assert t.bus_cmds[-1] == "EVSBUS CAN 6,14 500000" and not t.listen_only


def test_box_does_not_resend_same_bus(profiles):
    t, a = box()
    bus = Bus("can", (6, 14), 500_000, 11)
    a.select_bus(bus)
    a.select_bus(bus)
    assert t.bus_cmds == ["EVSBUS CAN 6,14 500000"]


def test_box_scan():
    _t, a = box()
    found = {b["pins"]: b for b in a.scan()}
    assert set(found) == {(6, 14), (12, 13), (3, 11)}
    assert "55B" in found[(12, 13)]["ids"]


def test_box_refuses_unsupported_doip():
    _t, a = box()
    with pytest.raises(AdapterError, match="DoIP"):
        a.select_bus(Bus("doip", PINS["doip1"]))


def test_plain_elm_is_not_a_box():
    with pytest.raises(AdapterError, match="Not an evsoc box"):
        UniversalAdapter(MockElmTransport("corsa-e")).reset()


def test_autodetect_skips_profiles_the_adapter_cannot_run(profiles):
    a = ElmAdapter(MockElmTransport("corsa-e"))
    a.reset()
    logs = []
    det = autodetect(a, profiles, car="Leaf ZE0", log=logs.append)
    assert det is None
    assert any("do not fit the adapter" in line for line in logs)


def test_cli_plan(capsys):
    assert main(["plan", "Leaf ZE0"]) == 0
    out = capsys.readouterr().out
    assert "pins 12/13" in out and "evsoc box" in out


def test_cli_refuses_wrong_adapter(capsys):
    assert main(["read", "-a", "mock://corsa-e", "-p", "evsoc_nissan_leaf_evcan"]) == 2
    assert "pins 12/13" in capsys.readouterr().err
