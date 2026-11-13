"""Download open PID collections and convert them into evsoc profiles (format v2).

Sources:
  abrp   github.com/iternio/ev-obd-pids        Apache-2.0
  wican  github.com/meatpiHQ/wican-fw          GPL-3.0  (vehicle_profiles.json)
  obdb   github.com/OBDb (one repo per model)  CC-BY-SA-4.0

Run with `evsoc update` (or `python -m evsoc.importers`).
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .elm import at_family
from .profiles import PKG, parse_profile

OUT = PKG / "profiles" / "generated"
UA = {"User-Agent": "evsoc-importer"}

# Adapter setup that ElmAdapter.reset() already takes care of.
_DROP = re.compile(r"^AT(Z|D|WS|I|RV|E[01]|L[01]|S[01]|H[01]|D[01]|M[01]|@1|SP0)$")


def fetch(url: str, retries: int = 3) -> bytes | None:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
    return None


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def norm_cmd(cmd: str) -> str:
    return cmd.replace(" ", "").upper().strip()


class StepBuilder:
    """Replays a command list and snapshots the full adapter state at every request."""

    def __init__(self):
        self.state: OrderedDict[str, str] = OrderedDict()
        self.init: list[str] = []
        self.steps: list[dict] = []
        self._ids: dict[str, str] = {}

    def at(self, cmd: str) -> None:
        cmd = norm_cmd(cmd)
        if not cmd or _DROP.match(cmd):
            return
        fam = at_family(cmd)
        if fam:
            self.state.pop(fam, None)  # keep "last set" order so dependencies stay in sequence
            self.state[fam] = cmd
        elif cmd not in self.init:
            self.init.append(cmd)

    def feed(self, cmd: str) -> str | None:
        """Process one command; returns the step id if it was a request."""
        c = norm_cmd(cmd)
        if not c:
            return None
        if c.startswith(("AT", "ST")):
            self.at(c)
            return None
        if len(c) % 2:
            c = c[:-1]  # trailing "number of responses" digit
        key = json.dumps([list(self.state.values()), c])
        if key not in self._ids:
            sid = f"s{len(self.steps) + 1}_{c}"
            self._ids[key] = sid
            self.steps.append({"id": sid, "at": list(self.state.values()), "request": c})
        return self._ids[key]


def _write(source: str, profiles: list[dict], notice: str) -> list[str]:
    out = OUT / source
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    written = []
    for d in profiles:
        try:
            parse_profile(d)  # validate before writing
        except Exception as e:  # noqa: BLE001 - report and skip broken upstream entries
            print(f"  skipped {d['name']}: {e}")
            continue
        (out / f"{d['name']}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(d["name"])
    (out / "SOURCE.md").write_text(notice, encoding="utf-8")
    return written


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# -- ABRP ---------------------------------------------------------------------------

ABRP_VEHICLES: dict[str, list[tuple[str, str, int | None, int | None]]] = {
    "hkmc/Ioniq5": [("Hyundai", "Ioniq 5", 2021, None), ("Hyundai", "Ioniq 6", 2022, None), ("Kia", "EV6", 2021, None), ("Genesis", "GV60", 2021, None)],
    "hkmc/hkmc2019": [("Hyundai", "Kona Electric", 2018, None), ("Hyundai", "Ioniq Electric", 2019, 2022), ("Kia", "e-Niro", 2018, 2022), ("Kia", "e-Soul", 2019, None)],
    "hkmc/hkmc2017": [("Hyundai", "Ioniq Electric", 2016, 2018)],
    "volkswagen/MEB": [("Volkswagen", "ID.3 / ID.4 / ID.5 / ID.7 / ID.Buzz", 2020, None), ("Skoda", "Enyaq / Elroq", 2020, None), ("Cupra", "Born / Tavascan", 2021, None), ("Audi", "Q4 e-tron", 2021, None), ("Ford", "Explorer EV / Capri", 2024, None)],
    "volkswagen/eGolf": [("Volkswagen", "e-Golf", 2014, 2020)],
    "volkswagen/eUP": [("Volkswagen", "e-up!", 2013, None), ("Skoda", "Citigo-e iV", 2019, 2020), ("Seat", "Mii electric", 2019, 2021)],
    "renault/zoe": [("Renault", "Zoe Ph1", 2012, 2019)],
    "renault/zoe2": [("Renault", "Zoe Ph2", 2019, None)],
    "ford/MachE": [("Ford", "Mustang Mach-E", 2021, None)],
    "gmc/bolt17": [("Chevrolet", "Bolt EV", 2017, 2018), ("Chevrolet", "Spark EV", 2014, 2016), ("Opel", "Ampera-e", 2017, 2019)],
    "gmc/bolt19": [("Chevrolet", "Bolt EV", 2019, None)],
    "jaguar/ipace2019": [("Jaguar", "I-Pace", 2018, 2020)],
    "jaguar/ipace2021": [("Jaguar", "I-Pace", 2021, None)],
    "mg/mgzsev": [("MG", "ZS EV", 2019, None)],
    "aiways/u5": [("Aiways", "U5", 2020, None)],
    "honda/eny1": [("Honda", "e:Ny1", 2023, None)],
    "deepal/s05/deepal_s05_abrp_submit_candidate - Clean": [("Deepal", "S05", 2025, None)],
    "Mini/MiniCooperSE": [("Mini", "Cooper SE", 2020, 2024)],
}
_ABRP_UNITS = {"soc": "%", "soh": "%", "voltage": "V", "current": "A", "batt_temp": "°C", "ext_temp": "°C",
               "odometer": "km", "kwh_charged": "kWh", "capacity": "kWh", "power": "kW", "speed": "km/h"}


def abrp_profile(rel: str, d: dict, vehicles: list[tuple[str, str, int | None, int | None]]) -> dict:
    lower = {k.lower(): v for k, v in d.items()}

    def commands(key: str) -> list[str]:
        v = lower.get(key, [])
        return list(v.get("command", []) if isinstance(v, dict) else v)

    sb = StepBuilder()
    step_for: dict[str, str] = {}
    headers = [v["header"] for v in d.values() if isinstance(v, dict) and v.get("header")]
    for c in commands("init_commands"):
        sb.feed(c)
    if headers and not any(norm_cmd(c).startswith("ATSH") for c in commands("init_commands") + commands("data_commands")):
        sb.at(f"ATSH{headers[0]}")
    for c in commands("data_commands"):
        sid = sb.feed(c)
        if sid:
            step_for.setdefault(norm_cmd(c)[: len(norm_cmd(c)) // 2 * 2], sid)
    fields = {}
    for key, v in d.items():
        if not isinstance(v, dict):
            continue
        expr = v.get("equation") or v.get("formula")
        cmd = norm_cmd(str(v.get("command", "")))
        if not expr or cmd not in step_for or re.search(r"\{[a-z_]+\}", str(expr)):
            continue  # {other_field} references are derived values, not decodable bytes
        name = key.lstrip("_").lower()
        fields[name] = {
            "step": step_for[cmd],
            "decode": {"type": "equation", "expr": str(expr)},
            "min": _num(v.get("minValue")), "max": _num(v.get("maxValue")),
            "unit": _ABRP_UNITS.get(name, "%" if name.startswith("soc") else ""),
        }
    used = {f["step"] for f in fields.values()}
    return {
        "name": "abrp_" + slug(Path(rel).name.split(" ")[0].replace("_abrp_submit_candidate", "")),
        "description": ", ".join(f"{m} {mo}" for m, mo, *_ in vehicles),
        "source": f"https://github.com/iternio/ev-obd-pids/blob/main/{rel}.json",
        "license": "Apache-2.0",
        "vehicles": [{"make": m, "model": mo, "years": [a, b]} for m, mo, a, b in vehicles],
        "init": sb.init,
        "steps": [s for s in sb.steps if s["id"] in used],
        "fields": fields,
    }


def import_abrp() -> list[str]:
    blob = fetch("https://codeload.github.com/iternio/ev-obd-pids/tar.gz/refs/heads/main")
    files: dict[str, dict] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile() and m.name.endswith(".json"):
                rel = m.name.split("/", 1)[1][: -len(".json")]
                files[rel] = json.load(tar.extractfile(m))
    profiles = [abrp_profile(rel, files[rel], vehicles) for rel, vehicles in ABRP_VEHICLES.items() if rel in files]
    return _write("abrp", profiles, "Source: https://github.com/iternio/ev-obd-pids (Apache-2.0)\n")


# -- WiCAN ---------------------------------------------------------------------------

WICAN_FIELDS = {
    "SOC": "soc", "SOC_D": "soc_display", "SOC_BMS": "soc_bms", "SOC_DISP": "soc_display",
    "SOH": "soh", "HV_V": "voltage", "HV_A": "current", "HV_W": "power",
    "BATT_TEMP": "batt_temp", "HV_T_MAX": "batt_temp_max", "HV_T_MIN": "batt_temp_min",
    "HV_C_V_MAX": "cell_max_voltage", "HV_C_V_MIN": "cell_min_voltage",
    "ODOMETER": "odometer", "RANGE": "range", "KWH_CHARGED": "kwh_charged",
    "KWH_DISCHARGED": "kwh_discharged", "CHARGING": "is_charging", "CHARGING_DC": "is_dcfc",
    "HV_CAPACITY_KWH": "capacity", "HV_KWH_R": "energy_remaining", "LV_V": "aux_voltage", "TMP_A": "ext_temp",
}
WICAN_MAKES = {"BT1": "GM", "Mini Cooper": "Mini", "KGM": "KGM (SsangYong)", "VW": "Volkswagen"}
WICAN_UNITS = {"V": "V", "A": "A", "%": "%", "°C": "°C", "km": "km", "kWh": "kWh", "kW": "kW"}


def wican_profile(car: dict) -> dict | None:
    label = car["car_model"]
    if ":" in label:
        make, _, model = label.partition(":")
    else:  # e.g. "Renault Zoe Ph2 (2020-)"
        make, _, model = label.partition(" ")
    make, model = make.strip(), model.strip()
    make = WICAN_MAKES.get(make, make)
    if make == "Audi" and "MEB" in model:
        make = "Volkswagen"  # WiCAN files the whole MEB family under Audi
    sb = StepBuilder()
    for c in (car.get("init") or "").split(";"):
        sb.feed(c)
    fields: dict[str, dict] = {}
    for pid in car.get("pids", []):
        for c in (pid.get("pid_init") or "").split(";"):
            sb.feed(c)
        sid = sb.feed(pid["pid"])
        if not sid:
            continue
        params = pid["parameters"]
        items = params if isinstance(params, list) else [{"name": k, "expression": v} for k, v in params.items()]
        for p in items:
            pname = str(p.get("name", "")).upper()
            fname = WICAN_FIELDS.get(pname)
            if fname is None and "SOC" in pname and not pname.startswith("LV"):
                fname = "soc_" + slug(pname.replace("SOC", ""))
            if not fname or fname in fields or re.search(r"\bV\b", str(p.get("expression", ""))):
                continue  # 'V' is a WiCAN runtime variable we cannot provide
            fields[fname] = {
                "step": sid,
                "decode": {"type": "wican", "expr": str(p["expression"])},
                "min": _num(p.get("min")), "max": _num(p.get("max")),
                "unit": WICAN_UNITS.get(str(p.get("unit", "")), str(p.get("unit", ""))),
            }
    if not any(n == "soc" or n.startswith("soc_") for n in fields):
        return None
    for f in fields.values():  # SoC without bounds would accept anything
        if f["unit"] == "%" and f["min"] is None:
            f["min"], f["max"] = -5.0, 105.0
    years = re.search(r"\((\d{4})\s*-\s*(\d{4})?\)", label)
    used = {f["step"] for f in fields.values()}
    return {
        "name": "wican_" + slug(label),
        "description": label,
        "source": "https://github.com/meatpiHQ/wican-fw/tree/main/vehicle_profiles",
        "license": "GPL-3.0",
        "vehicles": [{"make": make, "model": model,
                      "years": [int(years.group(1)), int(years.group(2)) if years.group(2) else None] if years else None}],
        "init": sb.init,
        "steps": [s | {"at": wican_29bit(s["at"])} for s in sb.steps if s["id"] in used],
        "fields": fields,
    }


def wican_29bit(at: list[str]) -> list[str]:
    """WiCAN firmware switches to 29-bit ids when a header is longer than 11 bit, even under
    ATSP6 (e.g. ATSHDB33F1 for OBD on 18DB33F1). An ELM327 would only use the last three digits,
    so make it explicit: ATSP7 plus the priority byte (ATCP), header without it."""
    hdr = next((c[4:] for c in at if re.fullmatch(r"ATSH[0-9A-F]{6,8}", c)), None)
    if "ATSP6" not in at or hdr is None or int(hdr, 16) <= 0x7FF:
        return at
    prio, hdr = (hdr[:2], hdr[2:]) if len(hdr) == 8 else ("18", hdr)
    out = []
    for c in at:
        if c == "ATSP6":
            out += ["ATSP7", f"ATCP{prio}"]
        elif re.fullmatch(r"ATSH[0-9A-F]{6,8}", c):
            out.append(f"ATSH{hdr}")
        else:
            out.append(c)
    return out


def import_wican() -> list[str]:
    data = json.loads(fetch("https://raw.githubusercontent.com/meatpiHQ/wican-fw/main/vehicle_profiles.json"))
    profiles = [p for p in map(wican_profile, data["cars"]) if p]
    return _write("wican", profiles, "Source: https://github.com/meatpiHQ/wican-fw vehicle_profiles (GPL-3.0)\n")


# -- OBDb ------------------------------------------------------------------------------

OBDB_METRICS = {
    "stateOfHealth": "soh", "tractionBatteryVoltage": "voltage", "tractionBatteryCurrent": "current",
    "tractionBatteryCapacity": "capacity", "electricRange": "range", "isCharging": "is_charging",
    "pluggedIn": "plugged_in", "odometer": "odometer",
}
OBDB_UNITS = {"percent": "%", "volts": "V", "amps": "A", "celsius": "°C", "kilometers": "km", "miles": "mi",
              "kilowattHours": "kWh", "kilowatts": "kW", "ampereHours": "Ah"}
_LOW_VOLTAGE = re.compile(r"12V|AUX|\bLV\b|_LV_|LOW.?VOLT|LEAD|AGM|STARTER|SUB.?BAT|12 ?volt", re.I)
_MULTI_WORD_MAKES = ["Alfa-Romeo", "Land-Rover", "Rolls-Royce", "Mercedes-Benz", "Aston-Martin"]
_PROTO = {"15765-4-11bit": "ATSP6", "15765-4-29bit": "ATSP7", "9141-2": "ATSP3", "14230": "ATSP5"}


def _is_12v_sensor(cmd: dict, sig: dict) -> bool:
    """Subaru/Scion 'Remaining battery capacity' at 7A2 also exists on the ICE-only BRZ / FR-S,
    so it is the 12 V battery sensor, not a traction battery."""
    return cmd.get("hdr", "").upper() == "7A2" and "remaining battery capacity" in sig.get("name", "").lower()


def _is_bmw_e5c7_soh(cmd: dict, metric: str | None) -> bool:
    """OBDb maps BMW 22E5C7 byte 3 (Gen5 eDrive: iX3, i5, X5 50e) to SoH, but its own captures
    show 31-52 % next to clamped values above 100 on new cars: that byte is not the SoH."""
    return metric == "stateOfHealth" and cmd.get("hdr", "").upper() == "6F1" and cmd.get("cmd", {}).get("22", "").upper() == "E5C7"


def _is_bmw_ddbc(cmd: dict) -> bool:
    """BMW 22DDBC is the SoC on Gen3 (i3, Mini SE, PHEV) but answers all zeros on Gen5 (iX3, i5).
    An exact 0 there means "no value", otherwise the Gen5 car reads as empty."""
    return cmd.get("hdr", "").upper() == "6F1" and cmd.get("cmd", {}).get("22", "").upper() == "DDBC"


def _obdb_make_model(repo: str) -> list[tuple[str, str]]:
    for mm in _MULTI_WORD_MAKES:
        if repo == mm or repo.startswith(mm + "-"):
            make, model = mm.replace("-", " "), repo[len(mm) + 1 :]
            break
    else:
        make, _, model = repo.partition("-")
    model = model.replace("-", " ")
    makes = ["Vauxhall", "Opel"] if make == "VauxhallOpel" else [make]
    return [(m, model or "all models") for m in makes]


def obdb_step(cmd: dict) -> dict:
    hdr = cmd["hdr"].upper()
    eleven = len(hdr) == 3 and cmd.get("proto") != "15765-4-29bit"
    at = [_PROTO.get(cmd.get("proto", ""), "ATSP6" if eleven else "ATSP7")]
    if eleven:
        at.append(f"ATSH{hdr}")
        rax = cmd.get("rax") or (f"{int(hdr, 16) + 8:03X}" if hdr != "7DF" else "")
        at.append(f"ATCRA{rax.upper()}")
        fc_header = hdr
    else:
        pri = cmd.get("pri", "18").upper()
        tst = cmd.get("tst", "F1").upper()
        at += [f"ATCP{pri}", f"ATSH{hdr}{tst}"]
        rax = (cmd.get("rax") or "").upper()
        if len(rax) == 8:
            filt = rax
        elif rax and len(rax) <= 2:
            filt = f"{pri}DAF1{rax.zfill(2)}" if tst == "F1" else f"{pri}DA{tst}{rax.zfill(2)}"
        elif rax:
            filt = pri + rax.zfill(6)
        elif hdr.startswith("DA"):
            filt = f"{pri}DA{tst}{hdr[2:]}"
        else:
            filt = ""
        at.append(f"ATCRA{filt}")
        fc_header = f"{pri}{hdr}{tst}"
    eax = cmd.get("eax", "").upper()
    at.append(f"ATCEA{eax}")
    if cmd.get("fcm1"):
        at += [f"ATFCSH{fc_header}", f"ATFCSD{eax}300000", "ATFCSM1"]
    else:
        at.append("ATFCSM0")
    at.append(f"ATST{cmd['tmo'].upper()}" if cmd.get("tmo") else "ATST32")
    service, pid = next(iter(cmd["cmd"].items()))
    step = {"at": at, "request": f"{service}{pid}".upper()}
    if cmd.get("din"):
        step["pre"] = [f"10{cmd['din'].upper()}"]
    if cmd.get("dout"):
        step["post"] = [f"10{cmd['dout'].upper()}"]
    flt = cmd.get("filter")
    if flt:
        years = list(flt.get("years") or [])
        lows = years + ([flt["from"]] if flt.get("from") else [])
        lo = min(lows) if lows else None
        if flt.get("from") and not flt.get("to"):
            hi = None  # open-ended
        else:
            highs = years + ([flt["to"]] if flt.get("to") else [])
            hi = max(highs) if highs else None
        if lo or hi:
            step["years"] = [lo, hi]
    return step


def obdb_profile(repo: str, signalset: dict, generations: str | None) -> dict | None:
    steps, fields = [], {}
    soc_count = 0
    for n, cmd in enumerate(signalset.get("commands", [])):
        kept = []
        for sig in cmd.get("signals", []):
            metric = sig.get("suggestedMetric")
            text = f"{sig.get('id', '')} {sig.get('name', '')}"
            if (metric == "stateOfCharge" and _is_12v_sensor(cmd, sig)) or _is_bmw_e5c7_soh(cmd, metric):
                continue
            if metric == "stateOfCharge" and not _LOW_VOLTAGE.search(text):
                sid_up = sig["id"].upper()
                if "DISP" in sid_up or "DASH" in sid_up:
                    fname = "soc_display"
                elif any(k in sid_up for k in ("BMS", "ACTUAL", "REAL", "RAW", "INTERNAL")):
                    fname = "soc_bms"
                else:
                    fname = "soc"
                if fname in fields:
                    soc_count += 1
                    fname = f"{fname}_{soc_count + 1}"
            elif metric in OBDB_METRICS and not (metric == "odometer" and fields.get("odometer")):
                fname = OBDB_METRICS[metric]
                if fname in fields:
                    continue
            else:
                continue
            kept.append((fname, sig))
        if not kept:
            continue
        step = obdb_step(cmd)
        step["id"] = f"c{n + 1}_{step['request']}"
        steps.append(step)
        for fname, sig in kept:
            fmt = sig["fmt"]
            spec = {"type": "bits"} | {k: fmt[k] for k in ("bix", "len", "blsb", "sign", "mul", "div", "add", "nullmin", "nullmax") if k in fmt}
            if fname.startswith("soc") and _is_bmw_ddbc(cmd):
                spec["nullmin"] = 0
            fields[fname] = {
                "step": step["id"], "decode": spec,
                "min": fmt.get("min", 0), "max": fmt.get("max"),
                "unit": OBDB_UNITS.get(fmt.get("unit", ""), fmt.get("unit", "")),
                "label": sig.get("name", ""),
            }
    if not any(n == "soc" or n.startswith("soc_") for n in fields):
        return None
    for f in fields.values():  # allow a little slack around the documented range
        if f["unit"] == "%" and f["max"] == 100:
            f["min"], f["max"] = -5, 105
    lo = hi = None
    if generations:
        starts = [int(y) for y in re.findall(r"start_year:\s*(\d{4})", generations)]
        ends = re.findall(r"end_year:\s*(\d{4}|null)", generations)
        lo = min(starts) if starts else None
        hi = None if (not ends or "null" in ends) else max(int(e) for e in ends)
    vehicles = [{"make": mk, "model": md, "years": [lo, hi] if lo or hi else None} for mk, md in _obdb_make_model(repo)]
    return {
        "name": "obdb_" + slug(repo),
        "description": " / ".join(f"{v['make']} {v['model']}" for v in vehicles),
        "source": f"https://github.com/OBDb/{repo}",
        "license": "CC-BY-SA-4.0",
        "vehicles": vehicles,
        "init": [],
        "steps": steps,
        "fields": fields,
    }


def _obdb_repos() -> list[str]:
    repos, page = [], 1
    while True:
        chunk = json.loads(fetch(f"https://api.github.com/orgs/OBDb/repos?per_page=100&page={page}") or b"[]")
        if not chunk:
            break
        repos += [r["name"] for r in chunk if not r["name"].startswith(".") and not r.get("archived")]
        page += 1
    return sorted(set(repos) - {"SAEJ1979", "vscode-obdb"})


def import_obdb(progress: Callable[[str], None] = print) -> list[str]:
    repos = _obdb_repos()
    progress(f"  OBDb: {len(repos)} Repositories, lade Signal-Sets ...")

    def load(repo: str):
        raw = fetch(f"https://raw.githubusercontent.com/OBDb/{repo}/main/signalsets/v3/default.json")
        if not raw or b"stateOfCharge" not in raw:
            return None
        gens = fetch(f"https://raw.githubusercontent.com/OBDb/{repo}/main/generations.yaml")
        return obdb_profile(repo, json.loads(raw), gens.decode("utf-8", "replace") if gens else None)

    with ThreadPoolExecutor(16) as pool:
        profiles = [p for p in pool.map(load, repos) if p]
    return _write("obdb", profiles, "Source: https://github.com/OBDb (CC-BY-SA-4.0)\n")


IMPORTERS: dict[str, Callable[[], list[str]]] = {"abrp": import_abrp, "wican": import_wican, "obdb": import_obdb}


def run(sources: Iterable[str] = IMPORTERS) -> dict[str, list[str]]:
    result = {}
    for name in sources:
        print(f"Importiere {name} ...")
        result[name] = IMPORTERS[name]()
        print(f"  {len(result[name])} profiles")
    return result


if __name__ == "__main__":
    run()
