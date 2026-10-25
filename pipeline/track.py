"""Match current detections to the baseline registry and assign kiln states (PDF 7.5).

Baseline = SentinelKilnDB hand labels for the AOI (imagery Nov 2023 - Feb 2024).
Current  = detections.geojson from pipeline/infer.py.

Match: centroids within match_meters, or polygon IoU >= match_iou; one-to-one, closest first.
States:
    matched, baseline non-zigzag -> now zigzag : CONVERTED
    matched otherwise                          : NON_ZIGZAG or ZIGZAG (current class)
    detection with no baseline kiln            : NEW
    baseline kiln with no detection            : NOT_SEEN (only where the mosaic has data)
prevState is the baseline state, or null for NEW kilns.

Output: data/runs/<run_id>/tracked.json
Run from repo root:  python pipeline/track.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, Polygon
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def group_state(cls: str) -> str:
    return "ZIGZAG" if cls == "Zigzag" else "NON_ZIGZAG"


def track(baseline: list[dict], detections: list[dict], to_utm, match_m: float = 60, match_iou: float = 0.2,
          has_data=lambda lon, lat: True) -> list[dict]:
    """baseline: [{class, corners, centroid}], detections: [{class, confidence, corners, centroid}] (lon/lat).
    Returns one entry per kiln with state, prevState and the observation to record."""
    b_utm = [Polygon([to_utm(*p) for p in b["corners"]]) for b in baseline]
    d_utm = [Polygon([to_utm(*p) for p in d["corners"]]) for d in detections]
    pairs = []
    if b_utm and d_utm:
        tree = STRtree([p.centroid for p in b_utm])
        for j, dp in enumerate(d_utm):
            for i in tree.query(dp.centroid.buffer(max(match_m, 400))):
                dist = dp.centroid.distance(b_utm[i].centroid)
                inter = dp.intersection(b_utm[i]).area
                iou = inter / (dp.area + b_utm[i].area - inter) if inter else 0.0
                if dist <= match_m or iou >= match_iou:
                    pairs.append((dist, int(i), j))
    pairs.sort()
    b_used, d_used, out = set(), set(), []
    for dist, i, j in pairs:
        if i in b_used or j in d_used:
            continue
        b_used.add(i)
        d_used.add(j)
        b, d = baseline[i], detections[j]
        prev, cur = group_state(b["class"]), group_state(d["class"])
        state = "CONVERTED" if prev == "NON_ZIGZAG" and cur == "ZIGZAG" else cur
        out.append({"kind": "matched", "idPoint": b["centroid"], "class": d["class"], "confidence": d["confidence"],
                    "corners": d["corners"], "centroid": d["centroid"], "state": state, "prevState": prev,
                    "baselineClass": b["class"], "matchMeters": round(dist, 1)})
    for j, d in enumerate(detections):
        if j not in d_used:
            out.append({"kind": "new", "idPoint": d["centroid"], "class": d["class"], "confidence": d["confidence"],
                        "corners": d["corners"], "centroid": d["centroid"], "state": "NEW", "prevState": None,
                        "baselineClass": None, "matchMeters": None})
    for i, b in enumerate(baseline):
        if i not in b_used and has_data(*b["centroid"]):
            out.append({"kind": "not_seen", "idPoint": b["centroid"], "class": b["class"], "confidence": 0.0,
                        "corners": b["corners"], "centroid": b["centroid"], "state": "NOT_SEEN",
                        "prevState": group_state(b["class"]), "baselineClass": b["class"], "matchMeters": None})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/run.yaml")
    args = ap.parse_args()

    import rasterio
    from pyproj import Transformer

    from pipeline.baseline import baseline_kilns
    from pipeline.common import load_aoi, load_config, run_dir

    cfg = load_config(args.config)
    out_dir = run_dir(cfg)
    aoi = load_aoi(cfg)
    gj = json.loads((out_dir / "detections.geojson").read_text(encoding="utf-8"))
    dets = [{"class": f["properties"]["class"], "confidence": f["properties"]["confidence"],
             "corners": [tuple(p) for p in f["geometry"]["coordinates"][0][:4]],
             "centroid": tuple(f["properties"]["centroid"])} for f in gj["features"]]
    base = baseline_kilns(aoi)

    src = rasterio.open(out_dir / "mosaic.tif")
    to_mosaic = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform

    def has_data(lon, lat):
        x, y = to_mosaic(lon, lat)
        return bool(next(src.sample([(x, y)]))[0] > 0)

    to_utm = Transformer.from_crs("EPSG:4326", cfg["imagery"]["metric_crs"], always_xy=True).transform
    tracked = track(base, dets, to_utm, cfg["track"]["match_meters"], cfg["track"]["match_iou"], has_data)
    src.close()

    counts: dict[str, int] = {}
    for t in tracked:
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    (out_dir / "tracked.json").write_text(json.dumps({"runId": cfg["run_id"], "baseline": "SentinelKilnDB labels "
                                          "(Nov 2023 - Feb 2024)", "counts": counts, "kilns": tracked}, indent=1),
                                          encoding="utf-8")
    print(f"baseline kilns {len(base)}, detections {len(dets)} -> {len(tracked)} tracked kilns")
    for k in ["NON_ZIGZAG", "ZIGZAG", "CONVERTED", "NEW", "NOT_SEEN"]:
        print(f"  {k:<11} {counts.get(k, 0)}")
    print(f"-> {out_dir / 'tracked.json'}")


if __name__ == "__main__":
    main()
