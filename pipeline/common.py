"""Small shared helpers for pipeline scripts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from shapely import union_all
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path = "config/run.yaml") -> dict:
    p = Path(path)
    p = p if p.is_absolute() else ROOT / p
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_aoi(cfg: dict):
    gj = json.loads((ROOT / cfg["aoi"]["geojson"]).read_text(encoding="utf-8"))
    return union_all([shape(f["geometry"]) for f in gj["features"]])


def run_dir(cfg: dict) -> Path:
    d = ROOT / "data" / "runs" / cfg["run_id"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
