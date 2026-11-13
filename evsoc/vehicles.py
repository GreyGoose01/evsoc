"""Vehicle knowledge: makes from VIN, model year from VIN, shared platforms."""

from __future__ import annotations

import datetime
import re

# World Manufacturer Identifier (first 3 VIN characters) -> make.
# Only used to rank candidate profiles; an unknown WMI just means "try everything".
WMI: dict[str, str] = {}
_WMI_RAW = {
    "BMW": "WBA WBS WBY WBX 5UX 5YM 4US LBV",
    "Mini": "WMW WMZ",
    "Volkswagen": "WVW WVG WV1 WV2 1VW 1V2 3VW 3VV XW8 LFV LSV 8AW 9BW",  # 1V2: u. a. ID.4 aus Chattanooga
    "Audi": "WAU WA1 WUA TRU",
    "Porsche": "WP0 WP1",
    "Skoda": "TMB",
    "Cupra": "VSS",
    "Seat": "VSS",
    "Mercedes-Benz": "WDD WDB WDC W1K W1N W1V 4JG 55S",
    "smart": "WME",
    "Peugeot": "VF3 VR3",
    "Citroen": "VF7 VR7",
    "DS": "VR1",
    "Opel": "W0L W0V VXK",
    "Vauxhall": "W0L W0V VXK",
    "Fiat": "ZFA 3C3",
    "Jeep": "1C4 1J4 ZAC",
    "Chrysler": "2C4 1C3",
    "Dodge": "2C3 1B3",
    "Ram": "3C6 3C7",
    "Alfa Romeo": "ZAR",
    "Maserati": "ZAM",
    "Renault": "VF1 VF6",
    "Dacia": "UU1 VGA",
    "Nissan": "JN1 JN8 SJN 1N4 5N1 VSK",
    "Hyundai": "KMH TMA 5NP 5NM KM8 MAL",
    "Kia": "KNA KND KNC U5Y U6Y 5XY 3KP",
    "Genesis": "KMT",
    "Toyota": "JTD JTE JTM JTN JTK JTL JTF SB1 4T1 4T3 5TD 2T3 NMT VNK",
    "Lexus": "JTH JTJ 2T2",
    "Honda": "JHM 1HG 2HG SHH 5FN 19X",
    "Acura": "19U JH4",
    "Ford": "WF0 1FA 1FM 1FT 3FM 3FA",
    "Lincoln": "5LM",
    "Chevrolet": "1G1 1GN 3GN KL8 1GC",
    "Cadillac": "1GY",
    "GMC": "1GT 1GK",
    "Buick": "1G4",
    "Tesla": "5YJ 7SA LRW XP7",
    "Volvo": "YV1 YV4 LVY 7JR LYV",
    "Polestar": "LPS YSM",
    "Jaguar": "SAJ SAD",
    "Land Rover": "SAL",
    "MG": "LSJ SDP",
    "BYD": "LGX LC0",
    "Mitsubishi": "JA3 JA4 JMB JMY ML3",
    "Mazda": "JM1 JM3 JMZ",
    "Subaru": "JF1 JF2 4S3 4S4",
    "Rivian": "7FC 7PD",
    "Lucid": "50E",
}
for _make, _codes in _WMI_RAW.items():
    for _code in _codes.split():
        WMI.setdefault(_code, _make)

_EXTRA_MAKES = ["Infiniti", "Datsun", "Lamborghini", "Bentley", "Lotus", "Holden", "Daihatsu", "Scion", "Suzuki",
                "Tata", "Haval", "GWM", "Maxus", "Xpeng", "Zeekr", "Geely", "Deepal", "Lancia", "Aiways", "GM",
                "Rolls-Royce", "KGM (SsangYong)", "Mercedes-Benz", "Land Rover", "Alfa Romeo"]
_CANON = {m.lower().replace("-", " "): m for m in [*_WMI_RAW, *_EXTRA_MAKES]}


def canonical_make(name: str) -> str:
    """'FIAT' -> 'Fiat', 'Mercedes Benz' -> 'Mercedes-Benz', 'smart' stays 'smart'."""
    return _CANON.get(name.strip().lower().replace("-", " "), name.strip())


# Brands sold under one group share hardware, so a VIN from one lets us try the others.
GROUPS = [
    {"Peugeot", "Citroen", "DS", "Opel", "Vauxhall", "Fiat", "Jeep", "Alfa Romeo", "Lancia", "Chrysler", "Dodge", "Ram", "Maserati"},  # Stellantis
    {"Volkswagen", "Audi", "Skoda", "Seat", "Cupra", "Porsche", "Ford"},  # VW group (+ MEB Ford)
    {"Hyundai", "Kia", "Genesis"},
    {"BMW", "Mini", "Rolls-Royce"},
    {"Renault", "Dacia", "Nissan", "Mitsubishi"},
    {"Chevrolet", "Cadillac", "GMC", "Buick", "Opel", "Holden", "Honda", "Acura"},  # GM Ultium incl. Honda Prologue / Acura ZDX
    {"Volvo", "Polestar", "smart", "Geely", "Zeekr", "Lotus"},
    {"Toyota", "Lexus", "Subaru", "Mazda", "Daihatsu", "Scion"},
    {"Jaguar", "Land Rover"},
    {"Mercedes-Benz", "smart"},
]

# Shared EV platforms: (name, regex over "make model").
PLATFORMS: list[tuple[str, str]] = [
    ("Stellantis e-CMP / STLA Small", r"e[- ]?208|\b208\b|e[- ]?2008|\b2008\b|corsa|mokka|e[- ]?c4|ds ?3|avenger|600e|ypsilon|junior"),
    ("Stellantis Smart Car", r"[eë][- ]?c3\b|frontera|grande panda"),
    ("Stellantis EMP2 Van (eK9)", r"e[- ]?traveller|e[- ]?expert|vivaro|zafira|jumpy|spacetourer|ulysse|scudo|proace"),
    ("VW MEB", r"\bid\.? ?\d|id\.? ?buzz|enyaq|elroq|born|tavascan|q4|explorer ev|capri|\bmeb\b|(vw|volkswagen):? id\b"),
    ("VW MEB small (e-up)", r"e[- ]?up|citigo|\bmii\b"),
    ("VW e-Golf", r"e[- ]?golf"),
    ("Porsche/Audi PPE", r"macan.*(ev|electric)|q6 e[- ]?tron"),
    ("Porsche/Audi J1", r"taycan|e[- ]?tron gt"),
    ("Audi MLB evo e-tron", r"audi.*\be[- ]?tron\b(?! gt)|q8 e[- ]?tron"),
    ("Hyundai/Kia E-GMP", r"ioniq ?5|ioniq ?6|ioniq ?9|\bev6\b|\bev9\b|gv60|gv70|g80"),
    ("Hyundai/Kia gen 1", r"kona|niro|soul|ioniq(?! ?\d)|\bev3\b"),
    ("GM Ultium / BEV3", r"lyriq|celestiq|blazer ev|equinox ev|silverado ev|sierra ev|hummer|prologue|zdx|bt1|bev3"),
    ("GM Bolt / Ampera-e", r"bolt|ampera-?e|ampere-?e|spark"),
    ("GM Voltec", r"\bvolt\b|ampera\b(?!-?e)"),
    ("BMW i3", r"\bi3s?\b"),
    ("BMW Gen5 eDrive", r"\bix3\b|\bi4\b|\bix\b|\bi7\b|\bi5\b"),
    ("Mini F56 SE", r"mini.*(\bse\b|electric)|cooper se"),
    ("Renault/Nissan CMF-EV / AmpR", r"ariya|megane e[- ]?tech|scenic|renault 5|renault 4|\br5\b|\br4\b|master ev"),
    ("Renault Zoe / Kangoo Z.E.", r"zoe|kangoo|twizy"),
    ("Dacia Spring", r"spring|k-?ze"),
    ("Nissan Leaf", r"leaf"),
    ("Volvo/Geely (CMA, SPA, SEA)", r"xc40|c40|ex40|ec40|ex30|ex90|es90|polestar|zeekr|lynk|eletre|emeya|lotus|smart ?#|smart:? ?#?1\b|\bex5\b|geely|volvo.*(xc60|xc90|s60|v60|s90|v90)"),
    ("BYD e-Platform 3.0", r"byd|atto|dolphin|\bseal|yuan|denza"),
    ("Mitsubishi i-MiEV family", r"i-?miev|c-?zero|peugeot:? i-?on\b"),
    ("Mitsubishi Outlander PHEV", r"outlander"),
    ("Toyota/Subaru e-TNGA", r"bz4x|solterra"),
    ("Ford GE1 (Mach-E)", r"mach[- ]?e\b|f[- ]?150 lightning"),
    ("Jaguar I-Pace", r"i-?pace"),
    ("MG / SAIC EV", r"\bmg\b.*(zs|mg4|mg5|marvel)|mg ?4|mg ?5"),
    ("Tesla Model 3/Y", r"tesla.*model ?[3y]"),
]

_PLATFORM_RE = [(name, re.compile(rx, re.I)) for name, rx in PLATFORMS]


def platform_for(text: str) -> str | None:
    for name, rx in _PLATFORM_RE:
        if rx.search(text):
            return name
    return None


def make_from_vin(vin: str | None) -> str | None:
    return WMI.get(vin[:3].upper()) if vin and len(vin) >= 3 else None


_YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"


def year_from_vin(vin: str | None) -> int | None:
    """Model year from VIN position 10 (30-year cycle, newest plausible year wins)."""
    if not vin or len(vin) < 10:
        return None
    code = vin[9].upper()
    if code not in _YEAR_CODES:
        return None
    base = 1980 + _YEAR_CODES.index(code)
    limit = datetime.date.today().year + 1
    year = base
    while year + 30 <= limit:
        year += 30
    return year


def related_makes(make: str) -> set[str]:
    out = {make}
    for group in GROUPS:
        if make in group:
            out |= group
    return out


def norm(text: str) -> str:
    """'Hyundai IONIQ-5' -> 'hyundaiioniq5' for forgiving searches."""
    return re.sub(r"[^a-z0-9#]", "", text.lower().replace("ë", "e").replace("é", "e"))
