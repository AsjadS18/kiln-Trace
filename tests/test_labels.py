import pytest

from ml.labels import ObbBox, clip_box, format_obb_line, matches_dota, parse_obb_line

# Real example from the SentinelKilnDB val split.
OBB = "1 0.124960 0.376296 0.152747 0.312352 0.124701 0.301737 0.096914 0.365682"
DOTA = "15.99 48.17 19.55 39.98 15.96 38.62 12.4 46.81 FCBK 0"


def test_parse_real_example():
    b = parse_obb_line(OBB)
    assert b.cls == 1 and len(b.pts) == 4
    assert b.pts[0] == pytest.approx((0.124960, 0.376296))


def test_class_map_agrees_with_dota():
    assert matches_dota(parse_obb_line(OBB), DOTA)


def test_dota_mismatch_detected():
    assert not matches_dota(parse_obb_line(OBB), DOTA.replace("FCBK", "Zigzag"))
    assert not matches_dota(parse_obb_line(OBB), "25.99 48.17 19.55 39.98 15.96 38.62 12.4 46.81 FCBK 0")


@pytest.mark.parametrize("bad", ["", "1 0.1 0.2", "7 0 0 0 0 0 0 0 0", "1 a b c d e f g h"])
def test_bad_lines_rejected(bad):
    with pytest.raises(ValueError):
        parse_obb_line(bad)


def test_clip_box():
    b, clipped = clip_box(ObbBox(2, [(-0.01, 0.5), (0.5, 1.02), (0.3, 0.3), (0.9, 0.1)]))
    assert clipped
    assert b.pts == [(0.0, 0.5), (0.5, 1.0), (0.3, 0.3), (0.9, 0.1)]
    _, clipped = clip_box(parse_obb_line(OBB))
    assert not clipped


def test_format_roundtrip():
    b = parse_obb_line(OBB)
    assert parse_obb_line(format_obb_line(b)).pts == pytest.approx(b.pts)
    assert format_obb_line(b).startswith("1 0.124960 0.376296")
