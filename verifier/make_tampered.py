"""Make a tampered copy of a run's manifest for the demo: flip one kiln's class.

    python verifier/make_tampered.py --run kasur-2025-12 --index 0
    python verifier/verify.py --run kasur-2025-12 --index 0 --manifest data/runs/kasur-2025-12/manifest_tampered.json
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--run", required=True)
ap.add_argument("--index", type=int, default=0)
args = ap.parse_args()

d = ROOT / "data" / "runs" / args.run
man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
rec = man["records"][args.index]
old = rec["class"]
rec["class"] = "Zigzag" if old != "Zigzag" else "FCBK"
out = d / "manifest_tampered.json"
out.write_text(json.dumps(man, indent=1), encoding="utf-8")
print(f"record {args.index} ({rec['kilnId'][:12]}...): class {old} -> {rec['class']}  -> {out}")
