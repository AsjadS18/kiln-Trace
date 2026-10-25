"""Build one cloud-free Sentinel-2 RGB mosaic for the AOI and date window (PDF 7.3).

Mirrors the training data source: least-cloudy L2A scenes, cloud-masked, RGB = B04, B03, B02 at 10 m.
For each Sentinel-2 tile (MGRS) covering the AOI we take the N least-cloudy scenes in the window,
mask clouds/shadows with SCL, and take the per-pixel median.

Output (data/runs/<run_id>/):
    mosaic.tif      uint16 surface reflectance (offset removed), 3 bands R,G,B, nodata 0, on the
                    training grid (EPSG:4326, 10/111319.49 deg pixels)
    fetch.json      STAC item IDs, dates, cloud cover, coverage, mosaic SHA-256

Run from repo root:  python pipeline/fetch.py [--config config/run.yaml] [--per-tile 3]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import load_aoi, load_config, run_dir, sha256_file  # noqa: E402


def pick_items(items, per_tile: int):
    by_tile: dict[str, list] = {}
    for it in items:
        by_tile.setdefault(it.properties.get("s2:mgrs_tile", "?"), []).append(it)
    chosen = []
    for tile, its in sorted(by_tile.items()):
        its.sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
        chosen += its[:per_tile]
        print(f"  tile {tile}: {len(its)} scenes, using "
              + ", ".join(f"{i.datetime:%m-%d} ({i.properties.get('eo:cloud_cover', 0):.1f}% cloud)"
                          for i in its[:per_tile]))
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/run.yaml")
    ap.add_argument("--per-tile", type=int, default=1,
                    help="least-cloudy scenes per Sentinel-2 tile (1 = like the training data)")
    args = ap.parse_args()

    import odc.stac
    import planetary_computer
    import pystac_client
    from pyproj import Transformer

    cfg = load_config(args.config)
    im = cfg["imagery"]
    aoi = load_aoi(cfg)
    out_dir = run_dir(cfg)
    t0 = time.time()

    print(f"Searching {im['collection']} {im['window'][0]}..{im['window'][1]}, cloud < {im['max_cloud_pct']}%")
    cat = pystac_client.Client.open(im["stac_url"], modifier=planetary_computer.sign_inplace)
    items = cat.search(collections=[im["collection"]], intersects=mapping(aoi),
                       datetime=f"{im['window'][0]}/{im['window'][1]}",
                       query={"eo:cloud_cover": {"lt": im["max_cloud_pct"]}}).item_collection()
    if not len(items):
        raise SystemExit("no scenes found - widen the window or raise max_cloud_pct")
    chosen = pick_items(items, args.per_tile)

    old = [i.id for i in chosen if str(i.properties.get("s2:processing_baseline", "99")) < "04.00"]
    if old:
        print(f"  warning: {len(old)} scenes predate baseline 04.00 (no +1000 offset)")

    bbox = aoi.buffer(0.01).bounds   # ~1 km margin so edge kilns get full tiles
    bands = [b for b in im["bands"]] + ["SCL"]
    print(f"Loading {len(chosen)} scenes at {im['resolution']} in {im['crs']} ...")
    ds = odc.stac.load(chosen, bands=bands, crs=im["crs"], resolution=im["resolution"],
                       bbox=bbox, groupby="solar_day", chunks={"x": 2048, "y": 2048})
    bad = ds["SCL"].isin(im["scl_mask_classes"]) | (ds["SCL"] == 0)
    rgb = ds[im["bands"]].to_array("band").astype("float32")
    rgb = rgb.where(~bad & (rgb > 0)).chunk({"time": -1})   # median needs time in one chunk
    med = rgb.median("time", skipna=True).compute()
    arr = med.values                                   # (3, H, W) float, NaN = no data
    valid = np.all(np.isfinite(arr), axis=0)
    arr = np.where(valid, np.clip(np.nan_to_num(arr) - im["boa_offset"], 1, 65535), 0).astype(np.uint16)

    gbox = ds.odc.geobox
    transform = gbox.affine
    h, w = arr.shape[1:]
    to_grid = Transformer.from_crs("EPSG:4326", im["crs"], always_xy=True).transform
    aoi_grid = shp_transform(to_grid, aoi)
    inside = ~geometry_mask([mapping(aoi_grid)], out_shape=(h, w), transform=transform)
    coverage = float(valid[inside].mean())

    tif = out_dir / "mosaic.tif"
    profile = dict(driver="GTiff", width=w, height=h, count=3, dtype="uint16", crs=im["crs"],
                   transform=transform, nodata=0, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate", predictor=2, BIGTIFF="IF_SAFER")
    with rasterio.open(tif, "w", **profile) as dst:
        dst.write(arr)
        dst.descriptions = tuple(im["bands"])

    meta = {
        "runId": cfg["run_id"], "collection": im["collection"], "window": im["window"],
        "stacItems": [i.id for i in chosen],
        "scenes": [{"id": i.id, "date": f"{i.datetime:%Y-%m-%d}", "mgrs": i.properties.get("s2:mgrs_tile"),
                    "cloud": i.properties.get("eo:cloud_cover"),
                    "baseline": i.properties.get("s2:processing_baseline")} for i in chosen],
        "composite": f"median of {args.per_tile} least-cloudy scenes per MGRS tile, SCL mask {im['scl_mask_classes']}",
        "offsetRemoved": im["boa_offset"], "crs": im["crs"], "shape": [h, w],
        "transform": list(transform)[:6], "aoiCoverage": round(coverage, 4),
        "mosaicSha256": sha256_file(tif),
    }
    (out_dir / "fetch.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"mosaic {w} x {h} px, AOI coverage {coverage:.1%}, {time.time() - t0:.0f}s -> {tif}")
    if coverage < 0.95:
        print("  warning: >5% of the AOI has no cloud-free pixel; try --per-tile 5 or a wider window")


if __name__ == "__main__":
    main()
