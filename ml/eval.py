"""Evaluate a trained kiln detector and write ml/results.md (PDF section 7.2).

Reports:
1. Ultralytics metrics on the split: overall and per-class precision, recall, mAP50, mAP50-95
2. Class-agnostic mAP50 (comparable to the SentinelKilnDB paper benchmark)
3. Confidence-threshold sweep and the chosen threshold
   (highest recall where precision >= --min-precision; inspection triage favours recall)
4. Compliance view at that threshold: non-zigzag (FCBK + CFCBK) vs zigzag confusion, misses, false alarms
5. SHA-256 of the weights file

Run from repo root:
    python ml/eval.py --weights runs/kiln_s_256/weights/best.pt
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".ultralytics"))
sys.path.insert(0, str(ROOT))
from ml.labels import CLASS_NAMES, TILE_PX, parse_obb_line  # noqa: E402
from ml.obb_metrics import Matches, confusion, match_image, pick_threshold, sweep  # noqa: E402

DATA = ROOT / "data" / "yolo" / "kilns.yaml"
THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ultralytics_metrics(model, split: str, imgsz: int, batch: int, run_name: str) -> dict:
    m = model.val(data=str(DATA), split=split, imgsz=imgsz, batch=batch, plots=True,
                  project=str(ROOT / "runs"), name=run_name, exist_ok=True, verbose=False)
    b = m.box
    out = {"all": {"precision": float(b.mp), "recall": float(b.mr), "map50": float(b.map50), "map50_95": float(b.map)},
           "per_class": {}, "plots_dir": Path(m.save_dir).resolve().relative_to(ROOT).as_posix()}
    for i, c in enumerate(m.ap_class_index):
        out["per_class"][CLASS_NAMES[int(c)]] = {
            "precision": float(b.p[i]), "recall": float(b.r[i]),
            "map50": float(b.ap50[i]), "map50_95": float(b.ap[i])}
    return out


def class_agnostic_map50(model, split: str, imgsz: int, batch: int, run_name: str) -> float | None:
    try:
        m = model.val(data=str(DATA), split=split, imgsz=imgsz, batch=batch, single_cls=True, plots=False,
                      project=str(ROOT / "runs"), name=run_name, exist_ok=True, verbose=False)
        return float(m.box.map50)
    except Exception as e:   # keep the report even if this optional metric fails
        print(f"class-agnostic val failed: {e}")
        return None


def own_matching(model, split: str, imgsz: int, batch: int) -> Matches:
    img_dir = ROOT / "data" / "yolo" / "images" / split
    lbl_dir = ROOT / "data" / "yolo" / "labels" / split
    m = Matches()
    n = 0
    for r in model.predict(source=str(img_dir), imgsz=imgsz, conf=THRESHOLDS[0], batch=batch,
                           stream=True, verbose=False):
        stem = Path(r.path).stem
        text = (lbl_dir / f"{stem}.txt").read_text(encoding="ascii").strip()
        gts = []
        for line in text.splitlines() if text else []:
            box = parse_obb_line(line)
            gts.append((box.cls, [(x * TILE_PX, y * TILE_PX) for x, y in box.pts]))
        preds = []
        if r.obb is not None and len(r.obb):
            corners = r.obb.xyxyxyxy.cpu().numpy()
            for cls, conf, pts in zip(r.obb.cls.cpu().numpy(), r.obb.conf.cpu().numpy(), corners):
                preds.append((int(cls), float(conf), [tuple(map(float, p)) for p in pts]))
        match_image(gts, preds, 0.5, m)
        n += 1
        if n % 2000 == 0:
            print(f"  matched {n} images", flush=True)
    return m


def fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def write_report(res: dict, path: Path) -> None:
    u, thr, c = res["ultralytics"], res["threshold"], res["confusion"]
    L = [
        "# Model results", "",
        f"- Weights: `{res['weights']}`",
        f"- SHA-256: `{res['sha256']}`",
        f"- Split: **{res['split']}** ({res['n_images']:,} images, {res['n_kilns']:,} labelled kilns), imgsz {res['imgsz']}",
        f"- Evaluated: {res['created']}", "",
        "## Detection metrics (Ultralytics)", "",
        "| Class | Precision | Recall | mAP50 | mAP50-95 |", "|---|---|---|---|---|",
        f"| **all** | {fmt(u['all']['precision'])} | {fmt(u['all']['recall'])} | {fmt(u['all']['map50'])} | {fmt(u['all']['map50_95'])} |",
    ]
    for name, v in u["per_class"].items():
        L.append(f"| {name} | {fmt(v['precision'])} | {fmt(v['recall'])} | {fmt(v['map50'])} | {fmt(v['map50_95'])} |")
    L += ["", f"Class-agnostic mAP50 (any kiln, type ignored): **{fmt(res['class_agnostic_map50'])}**. "
          "For reference, the SentinelKilnDB paper reports class-agnostic mAP50 of 87.5 (RT-DETR), "
          "86.9 (TerraMind) and 86.7 (Galileo).", "",
          f"Ultralytics plots (PR curves, confusion matrix): `{u['plots_dir']}/`", "",
          "## Operating threshold", "",
          f"Chosen confidence threshold: **{thr['conf']}** ({thr['rule']}). "
          f"At this threshold: precision {thr['precision']:.3f}, recall {thr['recall']:.3f}, "
          f"{thr['tp']:,} kilns found, {thr['fn']:,} missed, {thr['fp']:,} false alarms "
          "(matching at IoU >= 0.5, class ignored).", "",
          "| conf | precision | recall | F1 | found | missed | false alarms |", "|---|---|---|---|---|---|---|"]
    for r in res["sweep"]:
        mark = " **<-**" if r["conf"] == thr["conf"] else ""
        L.append(f"| {r['conf']}{mark} | {r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} | "
                 f"{r['tp']:,} | {r['fn']:,} | {r['fp']:,} |")
    two = c["two_class"]
    L += ["", "## Compliance view (the regulator's question)", "",
          "Non-zigzag = FCBK + CFCBK (non-compliant design in Punjab). Rows = truth, columns = model, "
          f"at threshold {thr['conf']}.", "",
          "| truth \\ model | non-zigzag | zigzag | missed |", "|---|---|---|---|",
          f"| non-zigzag | {two['non_zigzag']['non_zigzag']:,} | {two['non_zigzag']['zigzag']:,} | {two['non_zigzag']['missed']:,} |",
          f"| zigzag | {two['zigzag']['non_zigzag']:,} | {two['zigzag']['zigzag']:,} | {two['zigzag']['missed']:,} |",
          f"| no kiln (false alarm) | {two['false_alarm']['non_zigzag']:,} | {two['false_alarm']['zigzag']:,} | - |", "",
          f"Type accuracy on detected kilns (non-zigzag vs zigzag): **{fmt(c['type_accuracy_on_detected'])}**", "",
          "## Full class confusion", "",
          "| truth \\ model | CFCBK | FCBK | Zigzag | missed |", "|---|---|---|---|---|"]
    names = ["CFCBK", "FCBK", "Zigzag", "no kiln"]
    for i, row in enumerate(c["full"]):
        cells = row if i < 3 else row[:3] + ["-"]
        L.append(f"| {names[i]} | " + " | ".join(f"{v:,}" if isinstance(v, int) else v for v in cells) + " |")
    L += ["", "## Notes", "",
          "- Honest numbers: these are on the held-out test split, never used for training or model selection.",
          "- The risk score shown to users is a priority for inspection, not proof; field checks confirm.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--split", default="test", choices=["val", "test"])
    ap.add_argument("--imgsz", type=int, default=256)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--min-precision", type=float, default=0.7)
    ap.add_argument("--out", default="ml/results")
    args = ap.parse_args()

    weights = (ROOT / args.weights).resolve() if not Path(args.weights).is_absolute() else Path(args.weights)
    from ultralytics import YOLO
    model = YOLO(str(weights))
    tag = weights.parent.parent.name if weights.parent.name == "weights" else weights.stem

    print("1/3 Ultralytics validation ...")
    u = ultralytics_metrics(model, args.split, args.imgsz, args.batch, f"eval_{tag}_{args.split}")
    agn = class_agnostic_map50(model, args.split, args.imgsz, args.batch, f"eval_{tag}_{args.split}_agnostic")
    print("2/3 Threshold sweep and compliance matching ...")
    m = own_matching(model, args.split, args.imgsz, args.batch)
    rows = sweep(m, THRESHOLDS)
    thr = pick_threshold(rows, args.min_precision)
    print("3/3 Writing report ...")
    res = {
        "weights": weights.relative_to(ROOT).as_posix() if weights.is_relative_to(ROOT) else str(weights),
        "sha256": sha256_file(weights), "split": args.split, "imgsz": args.imgsz,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_images": len(list((ROOT / "data" / "yolo" / "images" / args.split).glob("*.png"))),
        "n_kilns": len(m.gts), "ultralytics": u, "class_agnostic_map50": agn,
        "sweep": rows, "threshold": thr, "confusion": confusion(m, thr["conf"]),
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    write_report(res, out.with_suffix(".md"))
    a = u["all"]
    print(f"\nmAP50 {a['map50']:.3f} | mAP50-95 {a['map50_95']:.3f} | class-agnostic mAP50 {fmt(agn)}")
    for name, v in u["per_class"].items():
        print(f"  {name:<7} mAP50 {v['map50']:.3f}")
    print(f"threshold {thr['conf']}: precision {thr['precision']:.3f} recall {thr['recall']:.3f} ({thr['rule']})")
    print(f"type accuracy on detected (non-zigzag vs zigzag): {fmt(res['confusion']['type_accuracy_on_detected'])}")
    print(f"report: {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
