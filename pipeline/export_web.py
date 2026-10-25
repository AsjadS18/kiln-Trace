"""Export a run for the static dashboard (docs/ -> GitHub Pages).

Writes docs/data/:
    kilns.geojson   one feature per kiln (polygon, centroid point for low zoom), record fields + proof
    run.json        run summary: counts, model metrics, chain + IPFS links, imagery provenance
    manifest.json   exact copy of the committed manifest (the browser recomputes the root from it)
    chips/*.png     kiln image chips

Run from repo root:  python pipeline/export_web.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import load_config, run_dir  # noqa: E402

OUT = ROOT / "docs" / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/run.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    d = run_dir(cfg)
    man_bytes = (d / "manifest.json").read_bytes()
    man = json.loads(man_bytes)
    proofs = {i["kilnId"]: i for i in json.loads((d / "proofs.json").read_text(encoding="utf-8"))["items"]}
    ev = json.loads((d / "evidence.json").read_text(encoding="utf-8"))
    infer = json.loads((d / "infer.json").read_text(encoding="utf-8"))
    fetch = json.loads((d / "fetch.json").read_text(encoding="utf-8"))
    chain = json.loads((d / "chain.json").read_text(encoding="utf-8")) if (d / "chain.json").exists() else None
    model_meta = ROOT / "models" / f"{Path(infer['weights']).stem}.json"
    model = json.loads(model_meta.read_text(encoding="utf-8")) if model_meta.exists() else None

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "chips").mkdir(parents=True)
    chip_by_sha = {}
    for f in (d / "chips").glob("*.png"):
        import hashlib
        chip_by_sha[hashlib.sha256(f.read_bytes()).hexdigest()] = f

    feats = []
    for r in man["records"]:
        src = chip_by_sha.get(r["chipSha256"])
        chip = None
        if src:
            shutil.copy2(src, OUT / "chips" / src.name)
            chip = f"data/chips/{src.name}"
        ring = [[x / 1e6, y / 1e6] for x, y in r["polygon_e6"]]
        props = {"kilnId": r["kilnId"], "class": r["class"], "state": r["state"], "prevState": r["prevState"],
                 "confidence": r["confidenceBp"] / 100, "risk": r["riskScore"], "areaM2": r["areaM2"],
                 "lon": r["centroid_e6"][0] / 1e6, "lat": r["centroid_e6"][1] / 1e6, "chip": chip,
                 "chipCID": r["chipCID"], "proof": proofs[r["kilnId"]]["proof"]}
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
                      "properties": props})
    (OUT / "kilns.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}),
                                       encoding="utf-8")
    (OUT / "manifest.json").write_bytes(man_bytes)

    run = {"runId": cfg["run_id"], "aoi": cfg["aoi"]["name"], "sceneDate": ev["sceneDate"],
           "window": fetch["window"], "scenes": fetch["scenes"], "recordCount": ev["recordCount"],
           "byState": ev["byState"], "byClass": infer["byClass"], "merkleRoot": ev["merkleRoot"],
           "manifestCID": ev["manifestCID"], "manifestSha256": ev["manifestSha256"],
           "modelSha256": ev["modelSha256"], "codeCommit": ev["codeCommit"],
           "knownKilnsMatched150m": infer.get("knownKilnsMatched150m"), "knownKilnsInAoi": infer.get("knownKilnsInAoi"),
           "model": model, "chain": chain,
           "rpc": "https://polygon-amoy.drpc.org", "ipfsGateway": "https://gateway.pinata.cloud/ipfs/"}
    (OUT / "run.json").write_text(json.dumps(run, indent=1), encoding="utf-8")
    print(f"{len(feats)} kilns, {len(list((OUT / 'chips').glob('*.png')))} chips -> {OUT}")
    if not chain:
        print("note: no chain.json yet - the page works, the Verify button needs the on-chain commit")


if __name__ == "__main__":
    main()
