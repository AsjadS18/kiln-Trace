"""Freeze a trained model: copy weights to models/kiln_<version>.pt and record its SHA-256.

The SHA-256 goes on-chain with every batch, so any later model change is visible (PDF 7.2).
Run after ml/eval.py has written ml/results.json for the same weights:
    python ml/freeze.py --weights runs/kiln_s_256/weights/best.pt --version v1
Writes models/kiln_v1.pt (git-ignored) and models/kiln_v1.json (public metadata).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--results", default="ml/results.json")
    ap.add_argument("--conf", type=float, default=None,
                    help="operating threshold to record (must be a row of the eval sweep); default: eval's choice")
    args = ap.parse_args()

    src = (ROOT / args.weights).resolve()
    dst = ROOT / "models" / f"kiln_{args.version}.pt"
    meta_path = dst.with_suffix(".json")
    if dst.exists():
        raise SystemExit(f"{dst} already exists - frozen models are never overwritten; use a new --version")

    sha = sha256_file(src)
    results = json.loads((ROOT / args.results).read_text(encoding="utf-8"))
    if results["sha256"] != sha:
        raise SystemExit(f"{args.results} was produced for different weights; run ml/eval.py on {args.weights} first")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    assert sha256_file(dst) == sha
    thr = results["threshold"]
    if args.conf is not None:
        row = next((r for r in results["sweep"] if abs(r["conf"] - args.conf) < 1e-9), None)
        if row is None:
            raise SystemExit(f"conf {args.conf} not in the eval sweep: {[r['conf'] for r in results['sweep']]}")
        thr = {**row, "rule": f"chosen manually: precision/recall trade-off for real imagery (eval suggested {thr['conf']})"}
    meta = {
        "name": f"kiln_{args.version}",
        "sha256": sha,
        "source": src.relative_to(ROOT).as_posix(),
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "imgsz": results["imgsz"],
        "conf": thr["conf"],
        "conf_rule": thr["rule"],
        "classes": {"0": "CFCBK", "1": "FCBK", "2": "Zigzag"},
        "test_metrics": {
            "map50": round(results["ultralytics"]["all"]["map50"], 4),
            "map50_95": round(results["ultralytics"]["all"]["map50_95"], 4),
            "class_agnostic_map50": results["class_agnostic_map50"],
            "precision_at_conf": thr["precision"], "recall_at_conf": thr["recall"],
            "type_accuracy_on_detected": results["confusion"]["type_accuracy_on_detected"],
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"frozen {dst}\nsha256 {sha}\nconf {thr['conf']}\nmetadata {meta_path}")
    print("Next: set model.path and model.conf in config/run.yaml to these values.")


if __name__ == "__main__":
    main()
