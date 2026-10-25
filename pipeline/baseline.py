"""Baseline kiln registry from SentinelKilnDB hand labels (imagery Nov 2023 - Feb 2024).

Used as the "before" observation for change tracking and as a sanity check for detections.
Tiles overlap by 30 px, so the same kiln appears in several label files; duplicates are merged.
"""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import Point

from ml.labels import CLASS_NAMES

ROOT = Path(__file__).resolve().parent.parent
TILE_PX = 128


DEG_PER_PX = 10 / 111319.49   # GEE scale=10 in EPSG:4326: square pixels in degrees (not metres)


def label_to_lonlat(lat0: float, lon0: float, line: str) -> tuple[str, list[tuple[float, float]]]:
    """One YOLO-OBB label line of tile centred at (lat0, lon0) -> (class name, 4 lon/lat corners).
    Dataset tiles are on a lon/lat grid with DEG_PER_PX pixels in both directions."""
    v = line.split()
    pts = []
    for x, y in zip(v[1::2], v[2::2]):
        pts.append((lon0 + (float(x) - 0.5) * TILE_PX * DEG_PER_PX,
                    lat0 + (0.5 - float(y)) * TILE_PX * DEG_PER_PX))
    return CLASS_NAMES[int(v[0])], pts


def baseline_kilns(aoi, labels_root: Path | None = None) -> list[dict]:
    """[{class, corners [(lon, lat)] x4, centroid (lon, lat), source}] for kilns inside the AOI."""
    root = labels_root or ROOT / "data" / "yolo" / "labels"
    minx, miny, maxx, maxy = aoi.bounds
    out, seen = [], set()
    for p in sorted(root.glob("*/*.txt")):
        try:
            lat0, lon0 = map(float, p.stem.split("_"))
        except ValueError:
            continue
        if not (miny - 0.01 < lat0 < maxy + 0.01 and minx - 0.01 < lon0 < maxx + 0.01):
            continue
        for line in p.read_text(encoding="ascii").splitlines():
            if not line.strip():
                continue
            cls, pts = label_to_lonlat(lat0, lon0, line)
            cx, cy = sum(x for x, _ in pts) / 4, sum(y for _, y in pts) / 4
            key = (round(cy / 0.0015), round(cx / 0.0015))     # ~150 m bins merge overlap duplicates
            if key in seen or not aoi.contains(Point(cx, cy)):
                continue
            seen.add(key)
            out.append({"class": cls, "corners": pts, "centroid": (cx, cy), "source": f"{p.parent.name}/{p.stem}"})
    return out
