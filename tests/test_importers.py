from evsoc.importers import StepBuilder, abrp_profile, obdb_profile, obdb_step, wican_29bit, wican_profile
from evsoc.profiles import parse_profile


def test_stepbuilder_snapshots_cumulative_state():
    sb = StepBuilder()
    for c in ["ATZ", "ATE0", "ATSP6", "ATAL", "ATSH7E4", "ATCRA7EC", "220101", "ATCRA7EB", "220100"]:
        sb.feed(c)
    assert sb.init == []  # ATAL is a remembered setting, so it travels with every step
    assert sb.steps[0]["at"] == ["ATSP6", "ATAL", "ATSH7E4", "ATCRA7EC"]
    assert sb.steps[1]["at"] == ["ATSP6", "ATAL", "ATSH7E4", "ATCRA7EB"]


def test_obdb_step_11bit_with_extended_address():
    s = obdb_step({"hdr": "6F1", "rax": "607", "eax": "07", "fcm1": True, "cmd": {"22": "DDBC"}})
    assert s["request"] == "22DDBC"
    assert {"ATSP6", "ATSH6F1", "ATCRA607", "ATCEA07", "ATFCSH6F1", "ATFCSD07300000", "ATFCSM1"} <= set(s["at"])


def test_obdb_step_29bit_vw_style():
    s = obdb_step({"hdr": "FC00", "rax": "FE0076", "pri": "17", "tst": "76", "cmd": {"22": "3DEF"}})
    assert {"ATSP7", "ATCP17", "ATSHFC0076", "ATCRA17FE0076", "ATCEA", "ATFCSM0"} <= set(s["at"])


def test_obdb_step_29bit_normal_fixed():
    s = obdb_step({"hdr": "DA60", "cmd": {"22": "9002"}, "filter": {"from": 2020, "years": [2019]}})
    assert "ATSHDA60F1" in s["at"] and "ATCRA18DAF160" in s["at"]
    assert s["years"] == [2019, None]


def test_obdb_profile_skips_12v_battery():
    signalset = {"commands": [
        {"hdr": "7E4", "cmd": {"22": "0101"}, "signals": [
            {"id": "X_SOC", "name": "HV battery charge", "suggestedMetric": "stateOfCharge", "fmt": {"bix": 32, "len": 8, "div": 2, "max": 100, "unit": "percent"}}]},
        {"hdr": "7E2", "cmd": {"22": "0102"}, "signals": [
            {"id": "X_12V_SOC", "name": "12V battery charge", "suggestedMetric": "stateOfCharge", "fmt": {"len": 8, "max": 100, "unit": "percent"}}]},
    ]}
    d = obdb_profile("Kia-EV6", signalset, "generations:\n  - start_year: 2021\n    end_year: null\n")
    p = parse_profile(d)
    assert list(p.fields) == ["soc"]
    assert p.vehicles[0].make == "Kia" and p.vehicles[0].years == (2021, None)
    assert p.platform == "Hyundai/Kia E-GMP"


def test_obdb_profile_skips_bmw_e5c7_soh():
    signalset = {"commands": [
        {"hdr": "6F1", "rax": "607", "eax": "07", "cmd": {"22": "E5CE"}, "signals": [
            {"id": "X_SOC", "name": "HV battery charge", "suggestedMetric": "stateOfCharge", "fmt": {"len": 16, "div": 100, "max": 100, "unit": "percent"}}]},
        {"hdr": "6F1", "rax": "607", "eax": "07", "cmd": {"22": "E5C7"}, "signals": [
            {"id": "X_SOH", "name": "HV battery health", "suggestedMetric": "stateOfHealth", "fmt": {"bix": 24, "len": 8, "max": 100, "unit": "percent"}}]},
    ]}
    p = parse_profile(obdb_profile("BMW-iX3", signalset, None))
    assert list(p.fields) == ["soc"] and len(p.steps) == 1


def test_wican_profile_conversion():
    car = {"car_model": "Peugeot: e-208", "init": "ATSP6;ATST96;",
           "pids": [{"pid": "22D4101", "pid_init": "ATSH6B4;ATCRA694;",
                     "parameters": [{"name": "SOC", "expression": "[B4:B5]/512", "unit": "%"}]}]}
    p = parse_profile(wican_profile(car))
    step = p.steps[p.fields["soc"].step]
    assert step.request == "22D410"
    assert step.at == ["ATSP6", "ATST96", "ATSH6B4", "ATCRA694"]
    assert p.fields["soc"].min == -5


def test_wican_29bit_header_under_atsp6():
    assert wican_29bit(["ATSP6", "ATST96", "ATSHDB33F1", "ATCRA18DAF1DB"]) == ["ATSP7", "ATCP18", "ATST96", "ATSHDB33F1", "ATCRA18DAF1DB"]
    assert wican_29bit(["ATSP6", "ATSH14DACBF1"]) == ["ATSP7", "ATCP14", "ATSHDACBF1"]
    assert wican_29bit(["ATSP6", "ATSH000726"]) == ["ATSP6", "ATSH000726"]  # still 11 bit


def test_abrp_profile_conversion():
    d = {"init_commands": {"command": ["ATZ", "ATSP6", "ATSH7E4"]}, "data_commands": {"command": ["ATCRA7EC", "220105"]},
         "soc": {"equation": "af/2", "command": "220105", "minValue": "-5", "maxValue": "105"}}
    p = parse_profile(abrp_profile("hkmc/test", d, [("Kia", "e-Niro", 2018, None)]))
    assert p.steps[p.fields["soc"].step].at == ["ATSP6", "ATSH7E4", "ATCRA7EC"]
