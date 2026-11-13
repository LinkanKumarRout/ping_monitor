from __future__ import annotations

import json
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
IPS_FILE = DATA_DIR / "ips.json"

_IP_RE = re.compile(
    r"^(?:"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}"
    r"|"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    r")$"
)

_lock = threading.Lock()


def _ensure_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not IPS_FILE.exists():
        IPS_FILE.write_text("[]\n", encoding="utf-8")


def validate_target(value: str) -> str:
    target = (value or "").strip()
    if not target:
        raise ValueError("IP / host is required")
    if len(target) > 253:
        raise ValueError("target too long")
    if not _IP_RE.match(target):
        raise ValueError("invalid IP or hostname")
    return target


def load_ips() -> list[str]:
    _ensure_files()
    with _lock:
        try:
            raw = json.loads(IPS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            if isinstance(item, str):
                try:
                    out.append(validate_target(item))
                except ValueError:
                    continue
        return out


def save_ips(ips: list[str]) -> list[str]:
    _ensure_files()
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in ips:
        try:
            target = validate_target(item)
        except ValueError:
            continue
        if target in seen:
            continue
        seen.add(target)
        cleaned.append(target)
    with _lock:
        IPS_FILE.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return cleaned


def add_ip(value: str) -> list[str]:
    target = validate_target(value)
    ips = load_ips()
    if target not in ips:
        ips.append(target)
    return save_ips(ips)


def remove_ip(value: str) -> list[str]:
    target = validate_target(value)
    ips = [ip for ip in load_ips() if ip != target]
    return save_ips(ips)
