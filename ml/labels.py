"""Label parsing shared by dataset prep, label checks and evaluation.

YOLO-OBB line:  "<cls> x1 y1 x2 y2 x3 y3 x4 y4"   corners normalised 0-1
DOTA line:      "x1 y1 x2 y2 x3 y3 x4 y4 <CLASS> <difficult>"   corners in pixels
"""
from __future__ import annotations

from dataclasses import dataclass

CLASS_NAMES = {0: "CFCBK", 1: "FCBK", 2: "Zigzag"}   # FROZEN class map
CLASS_IDS = {v: k for k, v in CLASS_NAMES.items()}
TILE_PX = 128


@dataclass
class ObbBox:
    cls: int
    pts: list[tuple[float, float]]   # 4 corners, normalised 0-1


def parse_obb_line(line: str) -> ObbBox:
    v = line.split()
    if len(v) != 9:
        raise ValueError(f"expected 9 values, got {len(v)}: {line!r}")
    cls = int(v[0])
    if cls not in CLASS_NAMES:
        raise ValueError(f"unknown class id {cls}")
    nums = [float(x) for x in v[1:]]
    return ObbBox(cls, list(zip(nums[0::2], nums[1::2])))


def parse_dota_line(line: str) -> tuple[str, list[tuple[float, float]]]:
    v = line.split()
    if len(v) < 9:
        raise ValueError(f"bad DOTA line: {line!r}")
    nums = [float(x) for x in v[:8]]
    return v[8], list(zip(nums[0::2], nums[1::2]))


def clip_box(box: ObbBox) -> tuple[ObbBox, bool]:
    """Clamp corners into [0, 1] (Ultralytics requirement). Returns (box, was_clipped)."""
    pts = [(min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)) for x, y in box.pts]
    return ObbBox(box.cls, pts), pts != box.pts


def format_obb_line(box: ObbBox) -> str:
    return f"{box.cls} " + " ".join(f"{x:.6f} {y:.6f}" for x, y in box.pts)


def matches_dota(box: ObbBox, dota_line: str, tol_px: float = 1.0) -> bool:
    """True if class name and corners (in pixels) agree with the DOTA label."""
    name, pts = parse_dota_line(dota_line)
    if CLASS_IDS.get(name) != box.cls:
        return False
    return all(abs(x * TILE_PX - dx) <= tol_px and abs(y * TILE_PX - dy) <= tol_px
               for (x, y), (dx, dy) in zip(box.pts, pts))
