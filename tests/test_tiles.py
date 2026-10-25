import numpy as np

from pipeline.tiles import STRIDE, TILE, minmax_scale, offsets, scale_patch, windows


def authors_norm(band):   # verbatim from third_party/.../tile_processing.py
    return ((band - band.min()) / (band.max() - band.min() + 1e-5) * 255).astype(np.uint8)


def test_scaling_matches_authors_exactly():
    rng = np.random.default_rng(0)
    band = rng.integers(0, 6000, size=(128, 128)).astype(np.uint16)
    assert np.array_equal(minmax_scale(band), authors_norm(band.astype(np.float64)))
    out = minmax_scale(band)
    assert out.min() == 0 and out.max() in (254, 255)


def test_scaling_is_per_band_and_ignores_constant_offset():
    rng = np.random.default_rng(1)
    rgb = rng.integers(500, 4000, size=(3, 128, 128)).astype(np.int32)
    a = scale_patch(rgb)
    b = scale_patch(rgb + 1000)          # L2A +1000 offset must not change the PNG
    assert a.shape == (128, 128, 3) and a.dtype == np.uint8
    assert np.array_equal(a, b)
    rgb2 = rgb.copy()
    rgb2[2] *= 3                          # scaling blue does not affect red/green
    assert np.array_equal(scale_patch(rgb2)[..., :2], a[..., :2])


def test_offsets_rule():
    assert offsets(128) == [0]
    assert offsets(100) == []
    assert offsets(226) == [0, 98]                  # exact fit
    assert offsets(300) == [0, 98, 172]             # last tile flush to edge
    for n in [128, 300, 1000, 5555]:
        o = offsets(n)
        assert o[0] == 0 and o[-1] + TILE == n
        assert all(b - a <= STRIDE for a, b in zip(o, o[1:]))


def test_windows_cover_every_pixel():
    h, w = 400, 333
    cover = np.zeros((h, w), bool)
    for r, c in windows(h, w):
        cover[r:r + TILE, c:c + TILE] = True
    assert cover.all()
