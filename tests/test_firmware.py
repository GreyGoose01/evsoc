"""The firmware core of the evsoc box (firmware/core), compiled for the PC and run behind a
pseudo terminal with simulated control units (firmware/sim). evsoc talks to it exactly like
to the real box, so these tests cover the C code: ELM327 commands, ISO-TP with flow control,
extended (BMW) and 29-bit (VW) addressing, read-only filter, listen-only mode and bus scan."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import serial

from evsoc.cli import open_adapter
from evsoc.connection import Bus
from evsoc.profiles import load_all
from evsoc.reader import autodetect, read, run_init

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"

pytestmark = pytest.mark.skipif(not (shutil.which("make") and shutil.which("cc")) or os.name != "posix",
                                reason="needs a C compiler and pseudo terminals")


@pytest.fixture(scope="module")
def sim_binary():
    subprocess.run(["make", "-s", "-C", str(FIRMWARE)], check=True)
    return FIRMWARE / "evsoc-box-sim"


@pytest.fixture
def box(sim_binary, request):
    proc = subprocess.Popen([str(sim_binary), request.param], stdout=subprocess.PIPE, text=True)
    device = proc.stdout.readline().strip()
    yield device
    proc.terminate()
    proc.wait(5)
    assert proc.returncode in (-15, 0), "the simulator reports an error (e.g. transmitting in listen-only mode)"


def send(port, cmd: str) -> str:
    port.write(cmd.encode() + b"\r")
    buf, end = b"", time.monotonic() + 5
    while b">" not in buf and time.monotonic() < end:
        buf += port.read(64)
    return buf.decode()


@pytest.mark.parametrize("box", ["corsa-e"], indirect=True)
def test_corsa_e_through_firmware(box):
    adapter = open_adapter(f"box:{box}", None)
    assert adapter.version.startswith("EVSOC-BOX 0.1")
    det = autodetect(adapter, load_all(), car="Corsa-e", log=lambda _m: None)
    assert det.profile.name == "evsoc_stellantis_ecmp"
    assert det.reading.soc == pytest.approx(79.96, abs=0.01)
    adapter.close()


@pytest.mark.parametrize("box", ["bmw-i3"], indirect=True)
def test_bmw_extended_addressing_multi_frame(box):
    """22DDBC answers with 9 bytes: first frame, flow control with ext. address 07, consecutive frame."""
    adapter = open_adapter(f"box:{box}", None)
    p = load_all()["evsoc_bmw_sme"]
    run_init(adapter, p)
    r = read(adapter, p, ["soc", "soc_display", "soh"])
    assert r.values["soc"].value == pytest.approx(58.8)
    assert r.values["soc_display"].value == pytest.approx(58.263, abs=0.01)
    assert r.values["soh"].value == 84
    adapter.close()


@pytest.mark.parametrize("box", ["id4"], indirect=True)
def test_vw_29_bit_and_gateway_flow_control(box):
    adapter = open_adapter(f"box:{box}", None)
    p = load_all()["evsoc_vw_meb"]
    run_init(adapter, p)
    r = read(adapter, p, ["soc_display", "soc", "capacity", "energy_available", "soh"], battery_kwh=77)
    assert r.soc == pytest.approx(73.43, abs=0.01)
    assert r.values["soc"].value == 80.0
    assert r.values["capacity"].value == pytest.approx(73.4)
    assert r.values["energy_available"].value == pytest.approx(35.2)  # 11 bytes: needs flow control
    assert r.values["soh"].value == pytest.approx(95.325)
    adapter.close()


@pytest.mark.parametrize("box", ["corsa-e"], indirect=True)
def test_firmware_blocks_writing_services(box):
    with serial.Serial(box, timeout=0.2) as port:
        send(port, "ATZ")
        send(port, "ATE0")
        send(port, "ATSH6B4")
        assert "ERR BLOCKED" in send(port, "2EF19000")      # WriteDataByIdentifier
        assert "ERR BLOCKED" in send(port, "1101")          # ECU reset
        assert "ERR BLOCKED" in send(port, "1002")          # programming session
        send(port, "ATCAF0")
        assert "ERR BLOCKED" in send(port, "032EF190")      # also with own ISO-TP header
        send(port, "ATCAF1")
        send(port, "ATH1")
        send(port, "ATCRA694")  # like a real ELM327: answers from 694 need a receive filter
        assert "69405" + "62D4109FEB" in send(port, "22D410").replace(" ", "")


@pytest.mark.parametrize("box", ["leaf"], indirect=True)
def test_listen_only_scan_and_passive_leaf(box):
    adapter = open_adapter(f"box:{box}", None)
    found = adapter.scan()
    assert found == [{"kind": "can", "pins": (12, 13), "bitrate": 500000, "frames": found[0]["frames"],
                      "ids": ["55B"]}]
    adapter.select_bus(Bus("can", (12, 13), 500000, listen_only=True))
    with pytest.raises(Exception, match="LISTEN-ONLY"):
        adapter.request("22D410")
    p = load_all()["evsoc_nissan_leaf_evcan"]
    run_init(adapter, p)
    r = read(adapter, p)
    assert r.soc == pytest.approx(64.8, abs=0.1)
    adapter.close()
