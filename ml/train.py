"""Train the YOLO-OBB kiln detector (PDF section 7.2).

Run from repo root (activated kilntrace env):
    # 1) smoke test: 10% of data, 2 epochs, a few minutes - checks the whole setup works
    python ml/train.py --name smoke --fraction 0.1 --epochs 2
    # 2) full run (several hours on an RTX 3060)
    python ml/train.py --name kiln_s_256
    # resume an interrupted run
    python ml/train.py --resume runs/kiln_s_256/weights/last.pt

Outputs go to runs/<name>/ (weights/best.pt, results.csv, plots).
Pretrained weights are downloaded once to models/pretrained/.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Keep Ultralytics settings/fonts inside the project instead of the user profile.
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".ultralytics"))

DATA = ROOT / "data" / "yolo" / "kilns.yaml"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo11s-obb.pt", help="e.g. yolo11s-obb.pt, yolo11m-obb.pt, yolo26s-obb.pt")
    ap.add_argument("--name", default="kiln_s_256")
    ap.add_argument("--imgsz", type=int, default=256, help="128 px tiles upsampled; small kilns detect better")
    # Smoke test on an RTX 3060: ~15 min per full epoch, so 50 epochs is ~12 h worst case
    # (early stopping usually ends sooner). 72k training tiles per epoch is plenty of signal.
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--patience", type=int, default=15)
    ap.add_argument("--batch", type=int, default=64, help="lower to 32 or 16 if CUDA out of memory")
    ap.add_argument("--workers", type=int, default=8, help="lower if the PC becomes unresponsive")
    ap.add_argument("--fraction", type=float, default=1.0, help="share of training images to use")
    ap.add_argument("--cache", default="false", choices=["false", "ram", "disk"],
                    help="ram needs ~15 GB at imgsz 256; tiles are tiny so false is usually fine")
    ap.add_argument("--resume", default=None, help="path to last.pt to resume")
    args = ap.parse_args()

    if not DATA.exists():
        raise SystemExit(f"{DATA} not found - run python ml/prepare_dataset.py first")

    from ultralytics import YOLO

    if args.resume:
        YOLO(args.resume).train(resume=True)
        return

    model = YOLO(str(ROOT / "models" / "pretrained" / args.model))
    model.train(
        data=str(DATA),
        imgsz=args.imgsz,
        epochs=args.epochs,
        patience=args.patience,
        batch=args.batch,
        workers=args.workers,
        fraction=args.fraction,
        cache=False if args.cache == "false" else args.cache,
        amp=True,
        # Kilns have no "up": full rotation and both flips.
        degrees=180, fliplr=0.5, flipud=0.5,
        mosaic=1.0, close_mosaic=10,
        # Mild colour jitter for season/haze; no hue shift (colour carries kiln-type cues).
        hsv_h=0.0, hsv_s=0.3, hsv_v=0.3,
        # Kilns are only ~10x4 px; strong down-scaling would make them vanish.
        scale=0.25,
        project=str(ROOT / "runs"), name=args.name, exist_ok=False,
        seed=42, plots=True,
    )


if __name__ == "__main__":   # required on Windows (dataloader worker processes)
    main()
