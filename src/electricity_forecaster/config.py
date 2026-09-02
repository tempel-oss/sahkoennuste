from __future__ import annotations
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
DB_PATH = ROOT / "data" / "electricity_forecaster.sqlite3"
DATASET_CONFIG = ROOT / "config" / "datasets.json"
AREA_CONFIG = ROOT / "config" / "entsoe_areas.json"
RAW_DIR = ROOT / "data" / "raw" / "fingrid"
ENTSOE_RAW_DIR = ROOT / "data" / "raw" / "entsoe"
FINGRID_API_BASE = "https://data.fingrid.fi/api"
# ENTSO-E has a newer TP endpoint and a legacy production endpoint documented by ENTSO-E.
# The client tries these in order for transient gateway/service failures.
ENTSOE_API_BASES = (
    "https://web-api.tp.entsoe.eu/api",
    "https://transparency.entsoe.eu/api",
)


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_secret(name: str) -> str:
    load_env_file()
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("PASTE_"):
        raise RuntimeError(f"{name} puuttuu .env-tiedostosta.")
    return value
