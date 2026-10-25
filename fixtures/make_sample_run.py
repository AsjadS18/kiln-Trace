"""Build fake sample runs so Person B can build the UI before the model exists.

Uses real SentinelKilnDB tiles and labels from Kasur (val/test splits) as chips and kiln
positions; everything else (states, CIDs, model hash, risk) is fake and marked fixture=true.

Output: fixtures/sample_run/
    index.json                         list of runs
    chips/<h3>.png                     128x128 RGB chips
    <runId>/manifest.json              schema-valid manifest
    <runId>/proofs.json                recordHash, leaf and proof per kiln + root

Run from repo root:  python fixtures/make_sample_run.py
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import sys
from pathlib import Path

import h3
import pyarrow.parquet as pq
from PIL import Image
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import merkle  # noqa: E402
from pipeline.schema import validate_manifest, validate_record  # noqa: E402

DATA = ROOT / "data" / "skdb"
AOI = ROOT / "config" / "aoi_kasur.geojson"
OUT = ROOT / "fixtures" / "sample_run"
CLASSES = {0: "CFCBK", 1: "FCBK", 2: "Zigzag"}
N_KILNS = 21          # 20 in both runs, the 21st appears only in run 2
TILE_PX, GSD_M = 128, 10.0
M_PER_DEG = 111320.0

MODEL_SHA = hashlib.sha256(b"kilntrace-fixture-model").hexdigest()
RUNS = [
    {"runId": "kasur-fixture-2025-01", "sceneDate": "2025-01-15", "window": ["2025-01-01", "2025-01-31"],
     "createdAt": "2025-02-01T09:00:00Z"},
    {"runId": "kasur-fixture-2025-12", "sceneDate": "2025-12-15", "window": ["2025-12-01", "2025-12-31"],
     "createdAt": "2026-01-01T09:00:00Z"},
]


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pick_kilns() -> list[dict]:
    """First kiln of each labelled tile inside Kasur, deduplicated by H3 cell."""
    aoi = shape(json.loads(AOI.read_text(encoding="utf-8"))["features"][0]["geometry"])
    found, seen = [], set()
    for split in ["val", "test"]:
        f = pq.ParquetFile(DATA / split / f"{split}.parquet")
        names = f.read(columns=["image_name"]).column("image_name").to_pylist()
        wanted = []
        for i, name in enumerate(names):
            lat0, lon0 = map(float, name[:-4].split("_"))
            if aoi.contains(Point(lon0, lat0)):
                wanted.append(i)
        if not wanted:
            continue
        t = f.read(columns=["image_name", "image", "yolo_obb_label"]).take(wanted).to_pylist()
        for row in sorted(t, key=lambda r: r["image_name"]):
            if not row["yolo_obb_label"]:
                continue
            k = to_kiln(row)
            if k["h3"] in seen:
                continue
            seen.add(k["h3"])
            found.append(k)
    if len(found) < N_KILNS:
        raise SystemExit(f"only {len(found)} Kasur kilns found in val/test; need {N_KILNS}")
    step = len(found) / N_KILNS                     # spread picks across the district
    return [found[int(i * step)] for i in range(N_KILNS)]


def to_kiln(row: dict) -> dict:
    lat0, lon0 = map(float, row["image_name"][:-4].split("_"))
    v = row["yolo_obb_label"][0].split()
    cls = CLASSES[int(v[0])]
    xs = [float(x) * TILE_PX for x in v[1::2]]
    ys = [float(y) * TILE_PX for y in v[2::2]]
    # pixel -> metres from tile centre (x east, y north)
    mx = [(x - TILE_PX / 2) * GSD_M for x in xs]
    my = [(TILE_PX / 2 - y) * GSD_M for y in ys]
    cos_lat = math.cos(math.radians(lat0))

    def lonlat_e6(dx, dy):
        return [round((lon0 + dx / (M_PER_DEG * cos_lat)) * 1e6), round((lat0 + dy / M_PER_DEG) * 1e6)]

    polygon = [lonlat_e6(a, b) for a, b in zip(mx, my)]
    cx, cy = sum(mx) / 4, sum(my) / 4
    centroid = lonlat_e6(cx, cy)
    area = abs(sum(mx[i] * my[(i + 1) % 4] - mx[(i + 1) % 4] * my[i] for i in range(4))) / 2
    cell = h3.latlng_to_cell(centroid[1] / 1e6, centroid[0] / 1e6, 10)
    png = Image.open(io.BytesIO(row["image"])).convert("RGB")
    buf = io.BytesIO()
    png.save(buf, format="PNG")
    return {"class": cls, "polygon_e6": polygon, "centroid_e6": centroid, "areaM2": round(area),
            "h3": cell, "kilnId": merkle.kiln_id_from_h3(cell), "chip": buf.getvalue(),
            "source": row["image_name"]}


def fake_conf(kiln_id: str, run_idx: int) -> int:
    return 6000 + int(kiln_id[2:10], 16) % 3800 + run_idx * 37


def risk(cls: str, dt_ck, in_ban: bool) -> int:
    non_zz = 1 if cls in ("FCBK", "CFCBK") else 0
    thermal = 0.0 if dt_ck is None else 1 / (1 + math.exp(-((dt_ck / 100 - 2.0) / 1.5)))
    return round(50 * non_zz + 30 * thermal + 20 * (1 if in_ban else 0))


def record(k: dict, run: dict, run_idx: int, *, cls: str, state: str, prev, conf: int,
           dt_ck=None, in_ban=False) -> dict:
    chip_sha = sha256_hex(k["chip"])
    rec = {
        "schema": "kilntrace.record.v1",
        "runId": run["runId"],
        "kilnId": k["kilnId"],
        "h3": k["h3"],
        "centroid_e6": k["centroid_e6"],
        "polygon_e6": k["polygon_e6"],
        "areaM2": k["areaM2"],
        "class": cls,
        "confidenceBp": conf,
        "state": state,
        "prevState": prev,
        "riskScore": risk(cls, dt_ck, in_ban) if state != "NOT_SEEN" else 0,
        "thermalDtCk": dt_ck,
        "inBanWindow": in_ban,
        "sceneDate": run["sceneDate"],
        "chipSha256": chip_sha,
        "chipCID": "FIXTURE-" + chip_sha[:24],
        "modelSha256": MODEL_SHA,
    }
    validate_record(rec)
    return rec


def build_runs(kilns: list[dict]) -> list[list[dict]]:
    base, extra = kilns[:20], kilns[20]
    # Run 1: first sighting, everything NEW.
    run1 = [record(k, RUNS[0], 0, cls=k["class"], state="NEW", prev=None, conf=fake_conf(k["kilnId"], 0))
            for k in base]
    # Run 2: show every UI case.
    fcbk_idx = [i for i, k in enumerate(base) if k["class"] != "Zigzag"]
    converted, not_seen = set(fcbk_idx[:2]), {fcbk_idx[2]} if len(fcbk_idx) > 2 else set()
    hot = set(fcbk_idx[3:6])                          # thermal anomaly + ban window
    run2 = []
    for i, k in enumerate(base):
        conf = fake_conf(k["kilnId"], 1)
        if i in converted:
            run2.append(record(k, RUNS[1], 1, cls="Zigzag", state="CONVERTED", prev="NEW", conf=conf))
        elif i in not_seen:
            run2.append(record(k, RUNS[1], 1, cls=k["class"], state="NOT_SEEN", prev="NEW", conf=0))
        elif i in hot:
            run2.append(record(k, RUNS[1], 1, cls=k["class"], state="NON_ZIGZAG", prev="NEW", conf=conf,
                               dt_ck=350 + 40 * i, in_ban=True))
        else:
            st = "ZIGZAG" if k["class"] == "Zigzag" else "NON_ZIGZAG"
            run2.append(record(k, RUNS[1], 1, cls=k["class"], state=st, prev="NEW", conf=conf))
    run2.append(record(extra, RUNS[1], 1, cls=extra["class"], state="NEW", prev=None,
                       conf=fake_conf(extra["kilnId"], 1)))
    return [run1, run2]


def manifest(run: dict, records: list[dict], root_hex: str, aoi_sha: str) -> dict:
    m = {
        "schema": "kilntrace.manifest.v1",
        "runId": run["runId"],
        "createdAt": run["createdAt"],
        "fixture": True,
        "aoi": {"name": "Kasur District", "geojsonSha256": aoi_sha},
        "imagery": {
            "collection": "sentinel-2-l2a",
            "window": run["window"],
            "stacItems": ["FIXTURE-chips-from-SentinelKilnDB"],
            "composite": "FIXTURE (real dataset tiles, not a real composite)",
            "scaling": "per_tile_minmax",
            "mosaicSha256": "0" * 64,
        },
        "model": {"name": "FIXTURE model", "sha256": MODEL_SHA, "imgsz": 256, "conf": 0.35},
        "code": {"repo": "local", "commit": "0000000"},
        "thresholds": {"nmsIou": 0.3, "matchMeters": 60},
        "merkle": {
            "root": root_hex,
            "leaf": "keccak256(keccak256(abi.encode(bytes32 kilnId, bytes32 recordHash)))",
            "pairs": "sorted",
            "recordHash": "keccak256(canonical JSON, sorted keys, no spaces)",
        },
        "records": records,
    }
    validate_manifest(m)
    return m


def main() -> None:
    kilns = pick_kilns()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "chips").mkdir(parents=True)
    for k in kilns:
        (OUT / "chips" / f"{k['h3']}.png").write_bytes(k["chip"])

    aoi_sha = sha256_hex(AOI.read_bytes())
    index = []
    for run, records in zip(RUNS, build_runs(kilns)):
        tree = merkle.tree_for_records(records)
        d = OUT / run["runId"]
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps(manifest(run, records, tree["root"], aoi_sha), indent=2),
                                         encoding="utf-8")
        (d / "proofs.json").write_text(json.dumps({"runId": run["runId"], **tree}, indent=2), encoding="utf-8")
        index.append({"runId": run["runId"], "sceneDate": run["sceneDate"], "recordCount": len(records),
                      "merkleRoot": tree["root"], "manifest": f"{run['runId']}/manifest.json",
                      "proofs": f"{run['runId']}/proofs.json"})
        print(f"{run['runId']}: {len(records)} records, root {tree['root']}")
    (OUT / "index.json").write_text(json.dumps({"fixture": True, "chipsDir": "chips", "chipName": "<h3>.png",
                                                "runs": index}, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
