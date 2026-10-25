"""Turn tracked kilns into tamper-evident evidence (PDF 7.7, 8.1-8.3).

For every tracked kiln:
  - 128 px RGB chip centred on the kiln, cut from this run's mosaic (scaled like training tiles)
  - one schema-valid record (integers only), hashed as canonical JSON
All records -> Merkle tree (pipeline/merkle.py) -> manifest with imagery, model and code provenance.

With --ipfs (needs PINATA_JWT in .env): chips are pinned as one folder (chipCID = <folderCID>/<file>),
then manifest.json is pinned and its CID recorded. Without it, chipCID = LOCAL-<sha256 prefix>.

Output (data/runs/<run_id>/):
    chips/<h3>.png   manifest.json   proofs.json   evidence.json (root, CIDs, counts)

Run from repo root:  python pipeline/evidence.py [--ipfs]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import h3
import numpy as np
import rasterio
import yaml
from PIL import Image
from rasterio.windows import Window
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import merkle  # noqa: E402
from pipeline.common import load_config, run_dir, sha256_file  # noqa: E402
from pipeline.schema import validate_manifest, validate_record  # noqa: E402
from pipeline.tiles import TILE, scale_patch  # noqa: E402


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def in_ban_window(date: str, district: str) -> bool:
    bans = yaml.safe_load((ROOT / "config" / "bans.yaml").read_text(encoding="utf-8")).get("bans") or []
    return any(b["start"] <= date <= b["end"] and district in b.get("districts", [district]) for b in bans)


def chip_png(src, to_px, lon: float, lat: float) -> bytes:
    row, col = to_px(lon, lat)
    win = Window(col - TILE // 2, row - TILE // 2, TILE, TILE)
    sub = src.read(window=win, boundless=True, fill_value=0)
    if not (sub > 0).any():
        sub = sub + 1
    buf = io.BytesIO()
    Image.fromarray(scale_patch(sub)).save(buf, format="PNG")
    return buf.getvalue()


def risk(cfg: dict, state: str, cls: str, in_ban: bool, dt_ck=None) -> int:
    if state == "NOT_SEEN":
        return 0
    r = cfg["risk"]
    non_zz = 1 if cls in ("FCBK", "CFCBK") else 0
    thermal = 0.0
    if dt_ck is not None:
        thermal = 1 / (1 + np.exp(-((dt_ck / 100 - r["thermal_dt_center_k"]) / r["thermal_dt_scale_k"])))
    return int(round(r["w_non_zigzag"] * non_zz + r["w_thermal"] * thermal + r["w_ban_window"] * in_ban))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/run.yaml")
    ap.add_argument("--ipfs", action="store_true", help="pin chips and manifest to Pinata (PINATA_JWT in .env)")
    args = ap.parse_args()

    from pyproj import Transformer

    cfg = load_config(args.config)
    out_dir = run_dir(cfg)
    tracked = json.loads((out_dir / "tracked.json").read_text(encoding="utf-8"))["kilns"]
    fetch = json.loads((out_dir / "fetch.json").read_text(encoding="utf-8"))
    infer = json.loads((out_dir / "infer.json").read_text(encoding="utf-8"))
    weights = ROOT / infer["weights"]
    model_sha = sha256_file(weights)
    scene_date = max(s["date"] for s in fetch["scenes"])
    district = cfg["aoi"]["name"].replace(" District", "")
    in_ban = in_ban_window(scene_date, district)
    to_utm = Transformer.from_crs("EPSG:4326", cfg["imagery"]["metric_crs"], always_xy=True).transform

    # 1) stable kiln IDs and chips
    chips_dir = out_dir / "chips"
    chips_dir.mkdir(exist_ok=True)
    src = rasterio.open(out_dir / "mosaic.tif")
    to_m = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform

    def to_px(lon, lat):
        return src.index(*to_m(lon, lat))

    used, items = set(), []
    for t in tracked:
        cell = h3.latlng_to_cell(t["idPoint"][1], t["idPoint"][0], cfg["track"]["h3_resolution"])
        key, n = cell, 1
        while key in used:              # two kilns in one ~70 m H3 cell: disambiguate, keep cell in record
            n += 1
            key = f"{cell}:{n}"
        used.add(key)
        png = chip_png(src, to_px, *t["centroid"])
        name = f"{key.replace(':', '-')}.png"
        (chips_dir / name).write_bytes(png)
        items.append({"t": t, "cell": cell, "idKey": key, "chip": name, "chipSha": hashlib.sha256(png).hexdigest()})
    src.close()

    # 2) optional IPFS upload of chips
    chips_cid = None
    if args.ipfs:
        from pipeline.ipfs import pin_files
        chips_cid = pin_files([(f"chips/{i['chip']}", (chips_dir / i["chip"]).read_bytes()) for i in items],
                              name=f"{cfg['run_id']}-chips")
        print(f"chips pinned: {chips_cid}")

    # 3) records
    records = []
    for i in items:
        t = i["t"]
        poly_utm = Polygon([to_utm(*p) for p in t["corners"]])
        rec = {
            "schema": "kilntrace.record.v1",
            "runId": cfg["run_id"],
            "kilnId": merkle.to_hex(merkle.k256(("KT1:" + i["idKey"]).encode("ascii"))),
            "h3": i["cell"],
            "centroid_e6": [round(t["centroid"][0] * 1e6), round(t["centroid"][1] * 1e6)],
            "polygon_e6": [[round(x * 1e6), round(y * 1e6)] for x, y in t["corners"]],
            "areaM2": round(poly_utm.area),
            "class": t["class"],
            "confidenceBp": int(round(t["confidence"] * 10000)),
            "state": t["state"],
            "prevState": t["prevState"],
            "riskScore": risk(cfg, t["state"], t["class"], in_ban),
            "thermalDtCk": None,
            "inBanWindow": in_ban,
            "sceneDate": scene_date,
            "chipSha256": i["chipSha"],
            "chipCID": f"{chips_cid}/{i['chip']}" if chips_cid else "LOCAL-" + i["chipSha"][:24],
            "modelSha256": model_sha,
        }
        validate_record(rec)
        records.append(rec)
    records.sort(key=lambda r: r["kilnId"])
    tree = merkle.tree_for_records(records)

    # 4) manifest
    commit = git("rev-parse", "HEAD") or "0000000"
    repo = git("config", "--get", "remote.origin.url") or "local"
    manifest = {
        "schema": "kilntrace.manifest.v1",
        "runId": cfg["run_id"],
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aoi": {"name": cfg["aoi"]["name"], "geojsonSha256": sha256_file(ROOT / cfg["aoi"]["geojson"])},
        "imagery": {"collection": fetch["collection"], "window": fetch["window"], "stacItems": fetch["stacItems"],
                    "composite": fetch["composite"], "scaling": "per-tile per-band min-max to 0-255 (as training)",
                    "mosaicSha256": fetch["mosaicSha256"]},
        "model": {"name": f"yolo-obb {weights.stem}", "sha256": model_sha, "imgsz": infer["imgsz"],
                  "conf": infer["conf"]},
        "code": {"repo": repo, "commit": commit},
        "thresholds": {"nmsIou": cfg["merge"]["nms_iou"], "matchMeters": cfg["track"]["match_meters"]},
        "merkle": {"root": tree["root"],
                   "leaf": "keccak256(keccak256(abi.encode(bytes32 kilnId, bytes32 recordHash)))",
                   "pairs": "sorted", "recordHash": "keccak256(canonical JSON, sorted keys, no spaces)"},
        "records": records,
    }
    validate_manifest(manifest)
    man_bytes = json.dumps(manifest, indent=1).encode("utf-8")
    (out_dir / "manifest.json").write_bytes(man_bytes)
    (out_dir / "proofs.json").write_text(json.dumps({"runId": cfg["run_id"], **tree}, indent=1), encoding="utf-8")

    manifest_cid = None
    if args.ipfs:
        from pipeline.ipfs import pin_files
        manifest_cid = pin_files([("manifest.json", man_bytes)], name=f"{cfg['run_id']}-manifest", folder=False)
        print(f"manifest pinned: {manifest_cid}")

    counts: dict[str, int] = {}
    for r in records:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    ev = {"runId": cfg["run_id"], "merkleRoot": tree["root"], "recordCount": len(records),
          "manifestSha256": hashlib.sha256(man_bytes).hexdigest(), "manifestCID": manifest_cid,
          "chipsCID": chips_cid, "modelSha256": model_sha, "codeCommit": commit, "sceneDate": scene_date,
          "inBanWindow": in_ban, "byState": counts}
    (out_dir / "evidence.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
    print(json.dumps(ev, indent=2))
    if commit == "0000000":
        print("note: no git commit found - commit the code before the final run so the manifest names it")


if __name__ == "__main__":
    main()
