from __future__ import annotations

import json
from pathlib import Path

import yaml
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "src" / "config"
RESORTS_YAML = CONFIG_DIR / "resorts.yaml"
DISCOVERED_JSON = CONFIG_DIR / "discovered.json"

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 "
    "CIP-HS26-208-HSLU-student project"
)

SEASON_START = '2026-11-01'
SEASON_END = '2027-04-30'

def load_resorts() -> dict:
    with RESORTS_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

def load_discovered() -> dict:
    if not DISCOVERED_JSON.exists():
        return {}
    with DISCOVERED_JSON.open(encoding="utf-8") as fh:
        return json.load(fh)

def save_discovered(data: dict) -> Path:
    DISCOVERED_JSON.parent.mkdir(parents=True, exist_ok=True)
    with DISCOVERED_JSON.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return DISCOVERED_JSON
