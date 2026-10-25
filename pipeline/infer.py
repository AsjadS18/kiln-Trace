"""Detect kilns in the AOI mosaic, geo-reference them and merge overlapping tiles (PDF 7.4).

Steps
1. cut mosaic.tif into 128 px tiles (stride 98), scale each exactly like training (pipeline/tiles.py)
2. YOLO-OBB predict (tiles passed as BGR, the same channel order Ultralytics used when training on PNGs)
3. tile pixels -> UTM via the mosaic's affine transform; class-agnostic rotated NMS in map space
4. size filter, keep kilns whose centre is inside the AOI, convert to lon/lat
5. sanity check against known SentinelKilnDB kilns in the AOI (2023-24 labels)

Output (data/runs/<run_id>/):
    detections.geojson   one polygon per kiln: class, confidence, areaM2, centroid
    infer.json           counts, settings, known-kiln match rate

Run from repo root:  python pipeline/infer.py [--weights models/kiln_v1.pt] [--conf 0.25]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from shapely import STRtree
from shapely.geometry import Point, Polygon, mapping
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".ultralytics"))
sys.path.insert(0, str(ROOT))
from ml.labels import CLASS_NAMES  # noqa: E402
from pipeline.baseline import baseline_kilns  # noqa: E402
from pipeline.common import load_aoi, load_config, run_dir  # noqa: E402
from pipeline.tiles import TILE, scale_patch, valid_fraction, windows  # noqa: E402


def iou(a: Polygon, b: Polygon) -> float:
    inter = a.intersection(b).area
    return inter / (a.area + b.area - inter) if inter > 0 else 0.0


def rotated_nms(dets: list[dict], thr: float) -> list[dict]:
    """Class-agnostic NMS on UTM polygons: the same kiln seen in up to 4 overlapping tiles."""
    dets = sorted(dets, key=lambda d: -d["conf"])
    polys = [d["poly"] for d in dets]
    tree = STRtree(polys)
    suppressed = np.zeros(len(dets), bool)
    keep = []
    for i, d in enumerate(dets):
        if suppressed[i]:
            continue
        keep.append(d)
        for j in tree.query(polys[i]):
            if j > i and not suppressed[j] and iou(polys[i], polys[j]) > thr:
                suppressed[j] = True
    return keep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/run.yaml")
    ap.add_argument("--weights", default=None, help="default: model.path in config")
    ap.add_argument("--conf", type=float, default=None, help="default: model.conf in config")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--min-valid", type=float, default=0.98, help="skip tiles with more no-data than this")
    args = ap.parse_args()

    from pyproj import Transformer
    from ultralytics import YOLO

    cfg = load_config(args.config)
    out_dir = run_dir(cfg)
    weights = ROOT / (args.weights or cfg["model"]["path"])
    conf = args.conf if args.conf is not None else cfg["model"]["conf"]
    imgsz = cfg["model"]["imgsz"]
    mcfg = cfg["merge"]
    aoi = load_aoi(cfg)
    t0 = time.time()

    with rasterio.open(out_dir / "mosaic.tif") as src:
        arr = src.read()                      # (3, H, W) uint16 R,G,B
        transform, crs = src.transform, src.crs
    h, w = arr.shape[1:]
    wins = windows(h, w)
    print(f"mosaic {w} x {h} px -> {len(wins)} tiles; model {weights.name}, conf {conf}, imgsz {imgsz}")

    metric = cfg["imagery"]["metric_crs"]
    grid_to_m = Transformer.from_crs(crs, metric, always_xy=True).transform
    model = YOLO(str(weights))
    raw, skipped = [], 0
    for b0 in range(0, len(wins), args.batch):
        batch, metas = [], []
        for r, c in wins[b0:b0 + args.batch]:
            sub = arr[:, r:r + TILE, c:c + TILE]
            if valid_fraction(sub) < args.min_valid:
                skipped += 1
                continue
            rgb = scale_patch(sub)
            batch.append(np.ascontiguousarray(rgb[..., ::-1]))   # RGB -> BGR for Ultralytics
            metas.append((r, c))
        if not batch:
            continue
        for (r, c), res in zip(metas, model.predict(batch, imgsz=imgsz, conf=conf, verbose=False)):
            if res.obb is None or not len(res.obb):
                continue
            for cls, cf, pts in zip(res.obb.cls.cpu().numpy(), res.obb.conf.cpu().numpy(),
                                    res.obb.xyxyxyxy.cpu().numpy()):
                utm = [grid_to_m(*(transform * (c + float(x), r + float(y)))) for x, y in pts]
                raw.append({"cls": int(cls), "conf": float(cf), "poly": Polygon(utm), "tile": f"{r}_{c}"})
        print(f"  {min(b0 + args.batch, len(wins))}/{len(wins)} tiles, {len(raw)} raw boxes", end="\r", flush=True)
    print()

    merged = rotated_nms(raw, mcfg["nms_iou"])
    to_ll = Transformer.from_crs(metric, "EPSG:4326", always_xy=True).transform
    to_utm = Transformer.from_crs("EPSG:4326", metric, always_xy=True).transform
    aoi_utm = shp_transform(to_utm, aoi)
    kept, too_small, too_big, outside = [], 0, 0, 0
    for d in merged:
        a = d["poly"].area
        if a < mcfg["min_area_m2"]:
            too_small += 1
        elif a > mcfg["max_area_m2"]:
            too_big += 1
        elif not aoi_utm.contains(d["poly"].centroid):
            outside += 1
        else:
            kept.append(d)

    feats, counts = [], {n: 0 for n in CLASS_NAMES.values()}
    for i, d in enumerate(sorted(kept, key=lambda d: -d["conf"])):
        ll = shp_transform(to_ll, d["poly"])
        cx, cy = ll.centroid.x, ll.centroid.y
        name = CLASS_NAMES[d["cls"]]
        counts[name] += 1
        feats.append({"type": "Feature", "geometry": mapping(ll), "properties": {
            "detId": i, "class": name, "classId": d["cls"], "confidence": round(d["conf"], 4),
            "areaM2": round(d["poly"].area), "centroid": [round(cx, 6), round(cy, 6)], "tile": d["tile"]}})
    (out_dir / "detections.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}),
                                                encoding="utf-8")

    # Sanity check: how many known (2023-24) kilns have a detection within 150 m?
    known = baseline_kilns(aoi)
    match = None
    if known and kept:
        cent = STRtree([shp_transform(to_utm, Point(f["properties"]["centroid"])) for f in feats])
        hits = sum(1 for k in known
                   if len(cent.query(shp_transform(to_utm, Point(k["centroid"])).buffer(150))))
        match = round(hits / len(known), 4)

    summary = {"runId": cfg["run_id"], "weights": weights.relative_to(ROOT).as_posix(), "conf": conf,
               "imgsz": imgsz, "tiles": len(wins), "tilesSkippedNoData": skipped, "rawBoxes": len(raw),
               "afterNms": len(merged), "droppedTooSmall": too_small, "droppedTooBig": too_big,
               "droppedOutsideAoi": outside, "kilns": len(kept), "byClass": counts,
               "knownKilnsInAoi": len(known), "knownKilnsMatched150m": match,
               "seconds": round(time.time() - t0)}
    (out_dir / "infer.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"-> {out_dir / 'detections.geojson'}")


if __name__ == "__main__":
    main()
