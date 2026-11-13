import socket
import struct
import threading

import pytest

from evsoc import enet
from evsoc.cli import main
from evsoc.elm import ElmAdapter, NegativeResponse
from evsoc.mock import MockElmTransport
from evsoc.profiles import load_all
from evsoc.reader import autodetect, read, run_init


@pytest.fixture(scope="module")
def profiles():
    return load_all()


def adapter_for(vehicle: str) -> ElmAdapter:
    a = ElmAdapter(MockElmTransport(vehicle))
    a.reset()
    return a


def test_corsa_e_profile(profiles):
    adapter = adapter_for("corsa-e")
    p = profiles["evsoc_stellantis_ecmp"]
    run_init(adapter, p)
    r = read(adapter, p)
    assert r.soc == pytest.approx(79.96, abs=0.01)
    assert r.values["voltage"].value == pytest.approx(426.25)
    assert r.values["voltage"].value == pytest.approx(108 * r.values["cell_min_voltage"].value, rel=0.01)


def test_bmw_i3_display_soc(profiles):
    adapter = adapter_for("bmw-i3")
    p = profiles["evsoc_bmw_sme"]
    run_init(adapter, p)
    r = read(adapter, p, ["soc", "soc_display"])
    assert r.values["soc"].value == pytest.approx(58.8)
    assert r.values["soc_display"].value == pytest.approx((588 - 105) * 100 / (934 - 105), abs=0.01)


def test_bmw_i3_soh_and_cell_capacity(profiles):
    adapter = adapter_for("bmw-i3")
    p = profiles["evsoc_bmw_sme"]
    run_init(adapter, p)
    r = read(adapter, p, ["soh", "cell_capacity_min", "cell_capacity_max", "cell_capacity_avg"])
    assert r.values["soh"].value == 84
    assert [r.values[n].value for n in ("cell_capacity_min", "cell_capacity_max", "cell_capacity_avg")] == [84.85, 86.35, 85.46]


def test_vw_meb_soh_needs_nominal_capacity(profiles):
    adapter = adapter_for("id4")
    p = profiles["evsoc_vw_meb"]
    run_init(adapter, p)
    r = read(adapter, p)
    assert r.values["capacity"].value == pytest.approx(73.4)
    assert r.values["energy_available"].value == pytest.approx(35.2)
    assert r.values["voltage"].value == pytest.approx(383.75)
    assert r.values["batt_temp"].value == -10
    assert r.values["soh"].value is None and "--battery-kwh" in r.values["soh"].error and "77" in r.values["soh"].error
    r = read(adapter, p, ["soh"], battery_kwh=77)
    assert r.values["soh"].value == pytest.approx(73.4 / 77 * 100, abs=0.001) and r.values["soh"].plausible
    r = read(adapter, p, ["soh"], battery_kwh=58)  # wrong pack size gives > 110 %
    assert not r.values["soh"].plausible


def test_bmw_gen5_cell_temperatures(profiles):
    adapter = adapter_for("bmw-ix3")
    p = profiles["evsoc_bmw_gen5"]
    r = read(adapter, p, ["soc", "batt_temp_min", "batt_temp_max"])
    assert r.soc == pytest.approx(86.86)
    assert (r.values["batt_temp_min"].value, r.values["batt_temp_max"].value) == (29.59, 30.92)


def test_enet_finds_car_behind_wlan_adapter(monkeypatch):
    """WLAN/LAN ENET adapters (UCSI-3000 & Co.) may only forward TCP 6801 at their own address."""
    monkeypatch.setattr(enet, "default_gateways", lambda: ["192.168.1.1", "192.168.16.254"])
    monkeypatch.setattr(enet, "interface_broadcasts", lambda: ["192.168.1.255", "169.254.255.255"])
    monkeypatch.setattr(enet, "discover", lambda timeout, targets: [])
    monkeypatch.setattr(enet, "port_open", lambda host, port, timeout: host == "192.168.16.254" and port == 6801)
    assert enet.find_vehicle() == ("192.168.16.254", "?", "gateway of the WiFi/LAN adapter")
    seen = {}
    monkeypatch.setattr(enet, "discover", lambda timeout, targets: seen.setdefault("t", targets) and [("169.254.1.2", "WBY000")])
    assert enet.find_vehicle()[:2] == ("169.254.1.2", "WBY000")
    assert seen["t"] == ["255.255.255.255", "192.168.1.255", "169.254.255.255"]


def test_route_and_interface_parsers():
    linux = "Iface\tDestination\tGateway\nwlan0\t00000000\t0101A8C0\neth0\t00000000\tFE10A8C0\n"
    assert enet.parse_linux_routes(linux) == ["192.168.1.1", "192.168.16.254"]
    assert enet.parse_bsd_routes("default            192.168.16.254     UGScg   en5\ndefault  link#18  UCSIg  bridge0\n") == ["192.168.16.254"]
    ip_addr = ("1: lo    inet 127.0.0.1/8 scope host lo\n"
               "2: eth0    inet 169.254.12.7/16 brd 169.254.255.255 scope link eth0\n"
               "3: wlan0    inet 192.168.1.20/24 brd 192.168.1.255 scope global wlan0\n")
    assert enet.parse_broadcasts(ip_addr) == ["169.254.255.255", "192.168.1.255"]
    mac = "en5: flags\n\tinet 169.254.3.4 netmask 0xffff0000 broadcast 169.254.255.255\n\tinet 10.0.0.5 netmask 0xffffff00\n"
    assert enet.parse_broadcasts(mac) == ["169.254.255.255", "10.0.0.255"]


def test_raw_ranges():
    from evsoc.cli import expand_commands
    assert expand_commands(["ATCEA07", "22E5C6-22E5C8"]) == ["ATCEA07", "22E5C6", "22E5C7", "22E5C8"]
    with pytest.raises(ValueError):
        expand_commands(["22DD00-22E000F"])


def test_raw_range_shows_only_hits(capsys):
    assert main(["raw", "-a", "mock://bmw-ix3", "--treffer", "ATSH6F1", "ATCEA07", "22E5CC-22E5CF"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["22E5CE: 607  62 E5 CE 21 EE 21 D9 21 FD"]


def test_obd_over_29_bit(profiles):
    """Renault Megane E-Tech answers the standard PIDs only on 29-bit ids (OBDb captures),
    so the generic profile also asks there; other 29-bit-only cars benefit the same way."""
    adapter = adapter_for("megane")
    p = profiles["evsoc_generic_obd"]
    run_init(adapter, p)
    r = read(adapter, p, ["soc_29bit", "voltage_29bit", "soh_29bit"])
    assert r.values["soc_29bit"].value == pytest.approx(46.667, abs=0.01)
    assert r.values["voltage_29bit"].value == pytest.approx(373)
    assert r.values["soh_29bit"].value == pytest.approx(98.824, abs=0.01)


def test_toyota_etnga_soh(profiles):
    adapter = adapter_for("bz4x")
    p = profiles["evsoc_toyota_etnga"]
    run_init(adapter, p)
    r = read(adapter, p, year=2023)
    assert r.soc == 80 and r.values["soc_bms"].value == pytest.approx(74.51, abs=0.01)
    assert r.values["capacity"].value == pytest.approx(190.0)
    assert r.values["soh"].value == pytest.approx(190 / 201.1 * 100, abs=0.01)
    assert read(adapter, p, ["soh"], year=2025).values["soh"].value is None  # other pack, nominal unknown


@pytest.mark.parametrize(
    "vehicle,expected,soc",
    [
        ("corsa-e", "evsoc_stellantis_ecmp", 79.96),
        ("bmw-i3", "evsoc_bmw_sme", 58.26),
        ("ioniq5", "obdb_hyundai_ioniq_5", 79.0),
        ("id4", "evsoc_vw_meb", 73.4),
        ("tesla-m3", "evsoc_tesla_model3y", 80.0),
        ("bmw-ix3", "evsoc_bmw_gen5", 86.86),   # 22DDBC = 0 must not win
        ("megane", "wican_renault_ariya_scenic_ev_e_tech_renault_5_e_tech_renault_4_e_tech_megane_e_tech_gsr2_2024_master_ev_e_tech", 46.67),
        ("bz4x", "evsoc_toyota_etnga", 80.0),
        ("e-c3", "evsoc_stellantis_smartcar", 80.0),
    ],
)
def test_autodetect(profiles, vehicle, expected, soc):
    det = autodetect(adapter_for(vehicle), profiles, log=lambda _m: None)
    assert det and det.profile.name == expected
    assert det.reading.soc == pytest.approx(soc, abs=0.05)


def test_autodetect_with_car_hint_is_targeted(profiles):
    det = autodetect(adapter_for("corsa-e"), profiles, car="Corsa-e", log=lambda _m: None)
    assert det.profile.platform == "Stellantis e-CMP / STLA Small"
    assert det.tried < 20


def test_sources_agree_on_same_car(profiles):
    """Every E-GMP profile reading 220101/220105 must decode the same SoC from one response.

    ABRP's Ioniq 5 list is known to be one byte off (see docs/sources.md) and is excluded."""
    adapter = adapter_for("ioniq5")
    seen = {}
    for p in profiles.values():
        if p.platform != "Hyundai/Kia E-GMP" or p.name == "abrp_ioniq5":
            continue
        run_init(adapter, p)
        r = read(adapter, p, [f.name for f in p.soc_fields])
        for name, v in r.values.items():
            step = p.steps[p.fields[name].step]
            if v.plausible and step.request in ("220101", "220105"):
                seen.setdefault(step.request, set()).add(v.value)
    assert seen["220105"] == {79.0}
    assert seen["220101"] == {80.0}


def test_cli_json(capsys):
    assert main(["read", "-a", "mock://corsa-e", "-p", "evsoc_stellantis_ecmp", "--json"]) == 0
    assert '"soc": 79.959' in capsys.readouterr().out


def test_cli_soh_with_nominal_capacity(capsys):
    assert main(["read", "-a", "mock://id4", "-p", "evsoc_vw_meb", "--all", "--akku-kwh", "77"]) == 0
    out = capsys.readouterr().out
    assert "Health (SoH)" in out and "95.3" in out and "73.4" in out


def test_cli_models(capsys):
    assert main(["models", "corsa"]) == 0
    out = capsys.readouterr().out
    assert "evsoc_stellantis_ecmp" in out and "obdb_vauxhallopel_corsa_e" in out


class FakeGateway(threading.Thread):
    """Minimal HSFZ server: acks each request, answers 22DDBC from ECU 0x07."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.requests = []
        self.alive_replies = []

    def run(self):
        conn, _ = self.srv.accept()
        with conn:
            while True:
                hdr = conn.recv(6)
                if len(hdr) < 6:
                    return
                length, ctrl = struct.unpack(">IH", hdr)
                body = conn.recv(length)
                if ctrl == 0x0013:
                    self.alive_replies.append(body)
                    continue
                self.requests.append(body)
                src, dst, uds = body[0], body[1], body[2:]
                conn.sendall(struct.pack(">IH", len(body), 0x0002) + body)  # ack
                if dst == 0x07 and uds == bytes.fromhex("22DDBC"):
                    conn.sendall(struct.pack(">IH", 2, 0x0012) + bytes([0x00, 0xF4]))  # alive check
                    pending = bytes.fromhex("7F2278")
                    conn.sendall(struct.pack(">IH", len(pending) + 2, 1) + bytes([dst, src]) + pending)
                    resp = bytes.fromhex("62DDBC024C03A60069")
                else:
                    resp = bytes([0x7F, uds[0], 0x31])
                conn.sendall(struct.pack(">IH", len(resp) + 2, 1) + bytes([dst, src]) + resp)


def test_enet_runs_bmw_profile(monkeypatch, profiles):
    gw = FakeGateway()
    gw.start()
    monkeypatch.setattr(enet, "HSFZ_PORT", gw.port)
    adapter = enet.EnetAdapter("127.0.0.1")
    p = profiles["evsoc_bmw_sme"]
    run_init(adapter, p)
    r = read(adapter, p, ["soc", "soc_display"])
    assert r.values["soc"].value == pytest.approx(58.8)
    assert gw.requests[0][:2] == bytes([0xF4, 0x07])
    with pytest.raises(NegativeResponse):
        adapter.request("22DD68")
    adapter.close()
    gw.join(2)
    assert gw.alive_replies and set(gw.alive_replies) == {bytes([0x00, 0xF4])}  # alive checks get answered


def test_enet_log_records_hsfz_frames(monkeypatch, profiles, tmp_path):
    """--log with enet:// must record the HSFZ traffic (docs/test-bmw-i4.md relies on it)."""
    gw = FakeGateway()
    gw.start()
    monkeypatch.setattr(enet, "HSFZ_PORT", gw.port)
    log = tmp_path / "enet.log"
    adapter = enet.EnetAdapter("127.0.0.1", log_path=str(log))
    p = profiles["evsoc_bmw_sme"]
    run_init(adapter, p)
    read(adapter, p, ["soc"])
    adapter.close()
    lines = log.read_text().splitlines()
    assert lines[0].endswith(f"# ENET 127.0.0.1:{gw.port}")
    assert any(" > 0001 F4 07 22 DD BC" in line for line in lines)
    assert any(" < 0001 07 F4 62 DD BC" in line for line in lines)
