"""Tiling and scaling - MUST match how the SentinelKilnDB training PNGs were made.

Reference: third_party/SENTINELKILNDB/data_scripts/tile_processing.py
- 128 x 128 px patches, stride 98 (30 px overlap), plus a last patch flush to the right/bottom edge
- each band of each patch min-max scaled to 0-255 on its own
- channel order R, G, B = B04, B03, B02
"""
from __future__ import annotations

import numpy as np

TILE = 128
STRIDE = 98


def minmax_scale(band: np.ndarray) -> np.ndarray:
    """Exact copy of the dataset authors' norm()."""
    band = band.astype(np.float64)
    return ((band - band.min()) / (band.max() - band.min() + 1e-5) * 255).astype(np.uint8)


def scale_patch(rgb: np.ndarray) -> np.ndarray:
    """(3, H, W) reflectance -> (H, W, 3) uint8 RGB, per-band min-max."""
    return np.dstack([minmax_scale(rgb[i]) for i in range(3)])


def offsets(length: int, tile: int = TILE, stride: int = STRIDE) -> list[int]:
    """Top-left offsets along one axis, same rule as the authors' script."""
    if length < tile:
        return []
    out = list(range(0, length - tile + 1, stride))
    if out[-1] + tile < length:
        out.append(length - tile)
    return out


def windows(height: int, width: int, tile: int = TILE, stride: int = STRIDE) -> list[tuple[int, int]]:
    """(row_off, col_off) of every tile."""
    return [(r, c) for r in offsets(height, tile, stride) for c in offsets(width, tile, stride)]


def valid_fraction(rgb: np.ndarray, nodata: int = 0) -> float:
    """Share of pixels with data in all three bands."""
    return float(np.all(rgb != nodata, axis=0).mean())
