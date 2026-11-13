"""The commands of `evsoc` as a user types them, against the simulated adapters."""

import json

import pytest

from evsoc import cli, enet
from evsoc.cli import main


@pytest.fixture(autouse=True)
def reset_wired_only():
    yield
    cli.WIRED_ONLY = False


# -- lists -------------------------------------------------------------------------------------

def test_profiles_lists_one_source_with_details(capsys):
    assert main(["profiles", "--source", "evsoc", "-v"]) == 0
    out = capsys.readouterr().out
    assert "evsoc_stellantis_ecmp" in out and "obdb_" not in out.split("profiles shown")[0]
    assert "Platform:" in out and "Source:" in out
    assert "Total:" in out and "obdb" in out.split("Total:")[1]


def test_models_markdown_is_what_the_docs_contain(capsys):
    """docs/vehicles.md is generated; a profile change without regenerating it fails here."""
    from pathlib import Path
    assert main(["models", "--markdown"]) == 0
    doc = Path(__file__).resolve().parent.parent / "docs" / "vehicles.md"
    assert capsys.readouterr().out.strip() == doc.read_text(encoding="utf-8").strip()


def test_models_unknown_car(capsys):
    assert main(["models", "gibtesnicht"]) == 1
    assert "Nothing found" in capsys.readouterr().out


def test_models_names_sibling_profiles_of_the_platform(capsys):
    assert main(["models", "enyaq"]) == 0
    out = capsys.readouterr().out
    assert "Enyaq" in out and "entries" in out


def test_devices_with_enet(monkeypatch, capsys):
    monkeypatch.setattr(enet, "find_vehicle", lambda *a, **k: ("169.254.1.2", "WBY00000000000001", "Broadcast"))
    assert main(["devices", "--enet"]) == 0
    out = capsys.readouterr().out
    assert "USB adapters (cable):" in out and "-a enet://169.254.1.2" in out
    monkeypatch.setattr(enet, "find_vehicle", lambda *a, **k: None)
    assert main(["--wired-only", "devices", "--enet", "--ble"]) == 0
    out = capsys.readouterr().out
    assert "nothing found" in out and "off in wired-only mode" in out
    assert "Other serial ports" not in out


# -- read --------------------------------------------------------------------------------------

def test_read_detects_the_car_by_itself(capsys):
    assert main(["read", "-a", "mock://corsa-e"]) == 0
    out = capsys.readouterr().out
    assert "evsoc_stellantis_ecmp" in out and "State of charge" in out


def test_read_unknown_profile(capsys):
    assert main(["read", "-a", "mock://corsa-e", "-p", "gibt_es_nicht"]) == 2
    assert "Unknown profile" in capsys.readouterr().err


def test_read_watch_repeats_until_interrupted(monkeypatch, capsys):
    naps = []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", nap)
    assert main(["read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--json", "--watch", "7"]) == 130
    readings = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert len(readings) == 2 and naps == [7, 7]


def test_read_writes_the_traffic_log(tmp_path):
    log = tmp_path / "verkehr.log"
    assert main(["read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--json", "--log", str(log)]) == 0
    text = log.read_text()
    assert "> ATZ" in text and "< " in text


def test_adapter_errors_end_with_a_message_not_a_traceback(capsys):
    assert main(["read", "-a", "tcp://127.0.0.1:1", "-p", "evsoc_stellantis_ecmp"]) == 1
    assert "Error: No connection to 127.0.0.1:1" in capsys.readouterr().err


def test_adapter_urls_reach_the_right_transport(monkeypatch):
    opened = []

    class Stop(Exception):
        pass

    def record(kind):
        def make(*args):
            opened.append((kind, *args))
            raise Stop
        return make

    monkeypatch.setattr(cli, "TcpTransport", record("tcp"))
    monkeypatch.setattr(cli, "BleTransport", record("ble"))
    monkeypatch.setattr(cli, "SerialTransport", record("serial"))
    for url in ("tcp://", "tcp://10.0.0.5:23", "ble://OBDLink CX", "/dev/ttyUSB0", "serial:///dev/ttyACM0?baud=115200",
                "box:/dev/ttyACM1"):
        with pytest.raises(Stop):
            cli.open_adapter(url, None)
    assert opened == [("tcp", "192.168.0.10", 35000), ("tcp", "10.0.0.5", 23), ("ble", "OBDLink CX"),
                      ("serial", "/dev/ttyUSB0", 38400), ("serial", "/dev/ttyACM0", 115200), ("serial", "/dev/ttyACM1", 38400)]


def test_enet_auto_without_a_car(monkeypatch, capsys):
    monkeypatch.setattr(enet, "find_vehicle", lambda *a, **k: None)
    assert main(["read", "-a", "enet://auto"]) == 1
    assert "No BMW found over ENET" in capsys.readouterr().err


# -- plan, scan --------------------------------------------------------------------------------

def test_plan_checks_the_own_adapter(capsys):
    assert main(["plan", "Leaf ZE0", "-a", "mock://corsa-e", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "OBD type:" in out and "does not fit" in out
    assert main(["plan", "Leaf ZE0", "-a", "box:mock://leaf", "--limit", "1"]) == 0
    assert "): fits\n" in capsys.readouterr().out


def test_plan_unknown_car(capsys):
    assert main(["plan", "gibtesnicht"]) == 1
    assert "No profile" in capsys.readouterr().out


def test_scan_lists_the_buses_the_box_sees(capsys):
    assert main(["scan", "-a", "box:mock://leaf"]) == 0
    out = capsys.readouterr().out
    assert "pins 12/13" in out and "kbit/s" in out


def test_scan_needs_the_box(capsys):
    assert main(["scan", "-a", "mock://corsa-e"]) == 2
    assert "needs the evsoc box" in capsys.readouterr().err


# -- monitor, pin, update ----------------------------------------------------------------------

def test_monitor_once_saves_the_state(tmp_path, capsys):
    state = tmp_path / "stand.json"
    assert main(["monitor", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--once", "--json",
                 "--state", str(state)]) == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    saved = json.loads(state.read_text())
    assert line["soc"] == pytest.approx(saved["soc"]) and 0 < saved["soc"] <= 100


def test_monitor_unknown_profile(capsys):
    assert main(["monitor", "-a", "mock://corsa-e", "-p", "gibt_es_nicht", "--once"]) == 2
    assert "Unknown profile" in capsys.readouterr().err


def test_pin_is_stored_hashed(tmp_path, capsys):
    from evsoc import config
    path = tmp_path / "config.json"
    assert main(["pin", "--config", str(path), "--pin", "12"]) == 2
    assert main(["pin", "--config", str(path), "--pin", "abcd"]) == 2
    assert not path.exists()
    assert main(["pin", "--config", str(path), "--pin", "4711"]) == 0
    assert "4711" not in path.read_text()
    assert config.check_pin("4711", config.load(str(path))["pin_hash"])
    assert not config.check_pin("4712", config.load(str(path))["pin_hash"])


def test_update_unknown_source(capsys):
    assert main(["update", "gibtesnicht"]) == 2
    assert "Unknown source" in capsys.readouterr().err
