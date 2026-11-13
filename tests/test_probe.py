"""`evsoc probe`: ask everything, keep the raw answers, decide afterwards."""

import json

import pytest

from evsoc import probe
from evsoc.cli import main, open_adapter
from evsoc.profiles import load_all, parse_profile
from evsoc.reader import autodetect
from evsoc.sniff import read_log


@pytest.fixture(scope="module")
def profiles():
    return load_all()


def run(mock, profiles, **kw):
    adapter = open_adapter(f"mock://{mock}", None)
    try:
        return probe.run(adapter, profiles, adapter_url=f"mock://{mock}", log=lambda _m: None, **kw)
    finally:
        adapter.close()


def test_probe_tests_whole_profiles_and_asks_each_question_once(profiles):
    report = run("corsa-e", profiles, car="Corsa-e", notes={"soc": 80, "soh": 70})
    assert report["autodetect"] == "evsoc_stellantis_ecmp"
    ecmp = report["profiles"]["evsoc_stellantis_ecmp"]["values"]
    assert ecmp["soc"]["value"] == pytest.approx(79.96, abs=0.01) and ecmp["soh"]["value"] == pytest.approx(93.8, abs=0.1)
    assert ecmp["batt_temp_min"]["value"] == 21  # all fields, not only the state of charge
    asked = [(tuple(r["at"]), r["request"]) for r in report["requests"].values()]
    assert len(asked) == len(set(asked))
    # other profiles that understand the same answers are reported next to it, nothing is hidden
    assert sum(p["soc_plausible"] > 0 for p in report["profiles"].values()) > 1
    text = probe.summary(report)
    assert "<- 'evsoc read' would choose this" in text
    assert "matches soc=80" in text and "DIFFERS from soh=70" in text


def test_report_can_be_decoded_again_without_the_car(profiles, tmp_path):
    report = run("corsa-e", profiles, car="Corsa-e")
    path = tmp_path / "bericht.json"
    probe.save(report, str(path))
    again = probe.load(str(path), profiles, notes={"soc": 10})
    assert again["profiles"] == json.loads(json.dumps(report["profiles"]))
    assert again["autodetect"] == report["autodetect"] and again["notes"] == {"soc": 10}

    # a corrected formula shows up without going back to the car
    d = json.loads(profiles["evsoc_stellantis_ecmp"].path.read_text(encoding="utf-8"))
    d["fields"]["soc"]["decode"]["expr"] = "INT16(A,B)/1024"
    changed = {**profiles, "evsoc_stellantis_ecmp": parse_profile(d)}
    assert probe.load(str(path), changed)["profiles"]["evsoc_stellantis_ecmp"]["values"]["soc"]["value"] == pytest.approx(39.98, abs=0.01)

    path.write_text("{}")
    with pytest.raises(ValueError, match="not a report"):
        probe.load(str(path), profiles)


def test_plug_in_hybrid_is_not_mistaken_for_the_electric_car(profiles):
    """Same address and request, other scaling: 50 % would read as 0.39 % with the e-CMP formula."""
    report = run("psa-phev", profiles)
    assert report["vin"] == "VR3ATTENTKY000001"
    ecmp, phev = report["profiles"]["evsoc_stellantis_ecmp"], report["profiles"]["evsoc_stellantis_phev"]
    assert ecmp["values"]["soc_bms"]["value"] == pytest.approx(0.39, abs=0.01) and ecmp["other_unit"]
    assert phev["values"]["soc"]["value"] == 50 and phev["values"]["current"]["value"] == pytest.approx(-12)
    assert phev["values"]["soh"]["value"] == 96 and not phev["other_unit"]
    assert report["autodetect"] == "evsoc_stellantis_phev"

    adapter = open_adapter("mock://psa-phev", None)
    assert autodetect(adapter, profiles, log=lambda _m: None).profile.name == "evsoc_stellantis_phev"
    adapter = open_adapter("mock://corsa-e", None)
    assert autodetect(adapter, profiles, car="Corsa-e", log=lambda _m: None).profile.name == "evsoc_stellantis_ecmp"


def test_confirm_only_rejects_on_a_positive_answer_of_another_length(profiles):
    from evsoc.decoders import Response
    from evsoc.reader import confirm_problem
    ecmp = profiles["evsoc_stellantis_ecmp"]
    assert confirm_problem(ecmp, {"soh": Response(b"\x01\x05\xdd", b"")}) is None
    assert confirm_problem(ecmp, {"soh": "No answer: NO DATA"}) is None
    assert confirm_problem(ecmp, {}) is None
    assert "2 instead of 3" in confirm_problem(ecmp, {"soh": Response(b"\x01\x80", b"")})


def test_smart_electric_drive_451_by_listening(profiles):
    adapter = open_adapter("mock://smart-ed", None)
    det = autodetect(adapter, profiles, car="fortwo electric drive", log=lambda _m: None)
    assert det.profile.name == "evsoc_smart_ed451"
    assert det.reading.values["soc"].value == 83.5 and det.reading.values["soc_bms"].value == 83.2


def test_probe_command_writes_the_report_and_reads_it_back(tmp_path, capsys):
    path = tmp_path / "p.json"
    assert main(["probe", "-a", "mock://corsa-e", "--car", "Corsa-e", "--notiz", "soc=79,5", "-o", str(path),
                 "--raw", "ATSH6B4", "ATCRA694", "22D80F-22D810"]) == 0
    out = capsys.readouterr().out
    assert "evsoc_stellantis_ecmp" in out and f"Report: {path}" in out
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["notes"] == {"soc": 79.5} and report["adapter"]["url"] == "mock://corsa-e"
    assert [r.get("payload") for r in report["raw"]] == [None, None, None, "62D8109FEB"]
    assert "error" in report["raw"][2]
    assert main(["probe", "-d", str(path), "--notiz", "soc=20"]) == 0
    assert "DIFFERS from soc=20" in capsys.readouterr().out


def test_probe_command_argument_errors(capsys):
    assert main(["probe"]) == 2
    assert main(["probe", "-a", "mock://corsa-e", "--notiz", "soc"]) == 2
    assert main(["probe", "-a", "mock://corsa-e", "--raw", "22D800-22D8"]) == 2
    assert "name=number" in capsys.readouterr().err


def test_cl2000_text_log_is_read(tmp_path):
    """CSS Electronics CL1000/CL2000: 'Timestamp;Type;ID;Data', comment header with '#'."""
    log = tmp_path / "00000001.TXT"
    log.write_text("# Logger type: CL2000\n# Value separator: \";\"\nTimestamp;Type;ID;Data\n"
                   "14T105959123;0;6b4;0322d81000000000\n14T105959140;0;694;0562d8109feb0000\n"
                   "14T110000140;1;18daf1db;0562d8109feb\n")
    frames, markers = read_log(str(log))
    assert [(f.id, f.ext, f.data.hex()) for f in frames] == [
        (0x6B4, False, "0322d81000000000"), (0x694, False, "0562d8109feb0000"), (0x18DAF1DB, True, "0562d8109feb")]
    assert frames[1].t - frames[0].t == pytest.approx(0.017) and frames[2].t - frames[1].t == pytest.approx(1.0)
    assert markers == []


def test_probe_reads_control_units_and_fault_memory(profiles):
    report = run("corsa-e", profiles, car="Corsa-e")
    (unit,) = report["units"]
    assert unit["unit"] == "6B4"
    assert unit["ident"] == {"Serial number": "BMU0012345", "Part number (PSA)": "9836785380"}
    assert [(d["code"], d["hex"], d["text"]) for d in unit["dtcs"]] == [
        ("P0A7F-00", "0A7F00", "confirmed"), ("U0111-87", "C11187", "active, confirmed")]
    text = probe.summary(report)
    assert "Control units (1):" in text and "U0111-87" in text

    assert run("corsa-e", profiles, car="Corsa-e", diagnose=False)["units"] == []

    hybrid = run("hybrid", profiles)  # plain OBD car: modes 03/07/0A on the functional address
    assert [(d["code"], d["text"]) for u in hybrid["units"] for d in u["dtcs"]] == [("P0A80", "stored")]


def test_fault_memory_can_be_read_but_never_cleared():
    from evsoc.safety import SafetyError, check_request
    for ok in ("03", "07", "0A", "1902FF", "190108"):
        check_request(bytes.fromhex(ok))
    for blocked in ("04", "14FFFFFF", "1906000000FF", "2E010001", "3101FF00", "1102"):
        with pytest.raises(SafetyError):
            check_request(bytes.fromhex(blocked))


def test_dtc_formats():
    from evsoc import diag
    assert diag.dtc_name(0x0A, 0x80) == "P0A80" and diag.dtc_name(0xC1, 0x11) == "U0111"
    assert diag.dtc_name(0x45, 0x12) == "C0512" and diag.dtc_name(0x9A, 0x01) == "B1A01"
    assert diag.parse_uds_dtcs(bytes.fromhex("0A7F0008" "00000000")) == [
        {"code": "P0A7F-00", "hex": "0A7F00", "status": 8, "text": "confirmed"}]
    assert diag.parse_obd_dtcs(bytes.fromhex("00"), "stored") == []
    assert diag.text_or_hex(b"BMU 1\x00\x00") == "BMU 1" and diag.text_or_hex(b"\x01\x02") == "01 02"


def test_enet_scan_asks_bmw_addresses(profiles):
    """Over ENET every control unit is asked by its address; silent ones are left out."""
    from evsoc import diag

    class Enet:
        def __init__(self):
            self.target, self.asked = None, []

        def at(self, cmd):
            self.target = int(cmd[5:], 16)

        def request(self, cmd):
            from evsoc.elm import NegativeResponse, NoResponse, UdsResponse
            self.asked.append((self.target, cmd))
            if self.target != 0x07:
                raise NoResponse("No answer")
            if cmd == "22F190":
                return UdsResponse("07", bytes.fromhex("62F190") + b"WBY71AW000F000001")
            if cmd == "1902FF":
                return UdsResponse("07", bytes.fromhex("5902FF" "21F10409"))
            raise NegativeResponse(0x22, 0x31)

    adapter = Enet()
    found = diag.scan([diag.enet_unit(adapter, a) for a in (0x01, 0x07)], log=lambda _m: None)
    assert [u["unit"] for u in found] == ["6F1/07"] and found[0]["name"] == "SME (high-voltage battery)"
    assert found[0]["ident"] == {"Vehicle identification number": "WBY71AW000F000001"}
    assert found[0]["dtcs"][0]["hex"] == "21F104"
    assert [c for t, c in adapter.asked if t == 0x01] == ["22F190", "22F187"]  # gives up on a silent address
