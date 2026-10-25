"""Draw label boxes on random images per class, for a visual check before training.

Wrong corner order or a swapped class map is the most common silent bug. Open the sheets and check:
- each box sits on a kiln (an oval/rectangular track, usually with a chimney)
- the box outline is a clean rectangle, not a twisted "bow tie"
- Zigzag sheet shows zigzag kilns, FCBK sheet shows bull's trench kilns, etc.

Output: data/yolo/label_check/<split>_<CLASS>.png   (5 x 4 grid, tiles upscaled 4x)
        The yellow dot marks corner 1 of each box.

Run from repo root:  python ml/draw_labels.py [--split train] [--n 20] [--seed 0]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ml.labels import CLASS_NAMES, TILE_PX, parse_obb_line  # noqa: E402

DST = ROOT / "data" / "yolo"
SCALE = 4
COLORS = {0: (255, 60, 200), 1: (255, 50, 50), 2: (40, 220, 90)}   # CFCBK magenta, FCBK red, Zigzag green


def load_index(split: str) -> dict[int, list[Path]]:
    by_cls: dict[int, list[Path]] = {c: [] for c in CLASS_NAMES}
    for p in sorted((DST / "labels" / split).glob("*.txt")):
        text = p.read_text(encoding="ascii").strip()
        if not text:
            continue
        for c in {int(line.split()[0]) for line in text.splitlines()}:
            by_cls[c].append(p)
    return by_cls


def draw_tile(lbl: Path, split: str, focus_cls: int) -> Image.Image:
    img = Image.open(DST / "images" / split / f"{lbl.stem}.png").convert("RGB")
    size = TILE_PX * SCALE
    img = img.resize((size, size), Image.NEAREST)
    d = ImageDraw.Draw(img)
    for line in lbl.read_text(encoding="ascii").splitlines():
        box = parse_obb_line(line)
        pts = [(x * size, y * size) for x, y in box.pts]
        d.polygon(pts, outline=COLORS[box.cls], width=3 if box.cls == focus_cls else 1)
        x0, y0 = pts[0]
        d.ellipse([x0 - 5, y0 - 5, x0 + 5, y0 + 5], fill=(255, 230, 0))
    d.rectangle([0, 0, size, 18], fill=(0, 0, 0))
    d.text((4, 3), lbl.stem, fill=(255, 255, 255))
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train", choices=["train", "val", "test"])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    by_cls = load_index(args.split)
    out_dir = DST / "label_check"
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    cols, cell = 5, TILE_PX * SCALE
    for c, name in CLASS_NAMES.items():
        files = by_cls[c]
        if not files:
            print(f"{name}: no labelled images in {args.split}")
            continue
        pick = rng.sample(files, min(args.n, len(files)))
        rows = (len(pick) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell, rows * cell), (30, 30, 30))
        for i, lbl in enumerate(pick):
            sheet.paste(draw_tile(lbl, args.split, c), ((i % cols) * cell, (i // cols) * cell))
        path = out_dir / f"{args.split}_{name}.png"
        sheet.save(path)
        print(f"{name}: {len(files)} images contain this class -> {path}")


if __name__ == "__main__":
    main()
