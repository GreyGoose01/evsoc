"""Persistent configuration of an installed evsoc device (set up once, then left in the car).

Stored as JSON (default /var/lib/evsoc/config.json, or $EVSOC_CONFIG). Written
atomically with mode 0600 because it holds the setup PIN hash and MQTT
credentials.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("EVSOC_CONFIG", "/var/lib/evsoc/config.json"))

DEFAULTS: dict = {
    "adapter": "auto",            # "auto" = find the evsoc box / USB adapter / CAN interface by itself
    "wired_only": True,
    "vehicle": {"profile": None, "car": None, "year": None, "label": None,
                "battery_kwh": None},  # nominal net capacity, needed for SoH on e.g. VW MEB
    "outputs": {
        "mqtt": {"enabled": False, "url": "", "discovery": True},
        "webhook": {"enabled": False, "url": ""},
    },
    "monitor": {"interval": 60, "sleep_interval": 300, "awake_voltage": 13.0,
                "wake_every": None, "wake_at": None, "min_voltage": 12.2},
    "web": {"host": "127.0.0.1", "port": 8080},
    "state_file": "/var/lib/evsoc/state.json",
    "pin_hash": None,             # pbkdf2 hash of the setup PIN
}


def merged(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merged(out[key], value)
        else:
            out[key] = value
    return out


def load(path: Path | str = DEFAULT_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    return merged(DEFAULTS, json.loads(path.read_text(encoding="utf-8")))


def save(cfg: dict, path: Path | str = DEFAULT_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def check_pin(pin: str, stored: str | None) -> bool:
    if not stored or not pin:
        return False
    try:
        _algo, salt, digest = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_pin(pin, bytes.fromhex(salt)).split("$")[2], digest)


def public(cfg: dict) -> dict:
    """Config without secrets, for the setup page."""
    out = copy.deepcopy(cfg)
    out.pop("pin_hash", None)
    url = out["outputs"]["mqtt"].get("url") or ""
    if "@" in url:  # hide the password: mqtt://user:secret@host -> mqtt://user:***@host
        creds, _, rest = url.partition("@")
        scheme, _, userpass = creds.partition("://")
        user = userpass.split(":")[0]
        out["outputs"]["mqtt"]["url"] = f"{scheme}://{user}:***@{rest}"
    return out


def apply_public(cfg: dict, update: dict) -> dict:
    """Merge settings from the setup page; a masked MQTT password keeps the stored one."""
    new = merged(cfg, {k: v for k, v in update.items() if k in ("vehicle", "outputs", "monitor")})
    url = new["outputs"]["mqtt"].get("url") or ""
    if ":***@" in url:
        old = cfg["outputs"]["mqtt"].get("url") or ""
        old_pw = old.split("://", 1)[-1].split("@", 1)[0].partition(":")[2] if "@" in old else ""
        new["outputs"]["mqtt"]["url"] = url.replace(":***@", f":{old_pw}@", 1)
    return new
