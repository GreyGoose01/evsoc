import pytest

from evsoc.profiles import candidates, load_all
from evsoc.vehicles import make_from_vin, platform_for, related_makes, year_from_vin


@pytest.mark.parametrize("vin,year", [("VR3UHZKXZMT000001", 2021), ("WBY8P2C05M7000001", 2021), ("JTDKB3U60Y7000001", 2000), ("JTDKB3U6007000001", None)])
def test_year_from_vin(vin, year):
    assert year_from_vin(vin) == year


def test_make_from_vin():
    assert make_from_vin("VR3UHZKXZMT000001") == "Peugeot"
    assert make_from_vin("1V2WNPE8XPC000001") == "Volkswagen"  # ID.4 built in the USA
    assert make_from_vin("XXX") is None
    assert "Opel" in related_makes("Peugeot")


@pytest.mark.parametrize(
    "text,platform",
    [
        ("Opel Corsa-e", "Stellantis e-CMP / STLA Small"),
        ("Volkswagen ID.4", "VW MEB"),
        ("Kia EV6", "Hyundai/Kia E-GMP"),
        ("Ford Mustang Mach E", "Ford GE1 (Mach-E)"),
        ("Volvo XC60", "Volvo/Geely (CMA, SPA, SEA)"),
        ("Opel Corsa XC60", "Stellantis e-CMP / STLA Small"),
        ("Ford Fusion Hybrid", None),
    ],
)
def test_platform_for(text, platform):
    assert platform_for(text) == platform


def test_candidates_by_car_include_platform_siblings():
    names = [p.name for p in candidates(load_all(), car="Corsa-e")]
    assert names.index("evsoc_stellantis_ecmp") < names.index("evsoc_generic_obd")
    assert "wican_peugeot_e_208" in names  # same platform, different brand
    assert names[-1] == "evsoc_generic_obd"
    assert "evsoc_tesla_model3y" not in names  # listen-only profiles of other cars are skipped
    assert "evsoc_tesla_model3y" in [p.name for p in candidates(load_all(), car="Model 3")]


def test_candidates_by_vin_put_make_first():
    names = [p.name for p in candidates(load_all(), vin="KMHKN81AFPU123456")]
    first = load_all()[names[0]]
    assert "Hyundai" in first.makes or "Kia" in first.makes or "Genesis" in first.makes
