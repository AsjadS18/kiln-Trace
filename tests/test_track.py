from pyproj import Transformer

from pipeline.track import track

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True).transform
D = 0.0009   # ~90-100 m in degrees near Kasur


def kiln(lon, lat, cls, conf=0.9):
    s = 0.0002
    corners = [(lon - s, lat - s), (lon + s, lat - s), (lon + s, lat + s), (lon - s, lat + s)]
    return {"class": cls, "confidence": conf, "corners": corners, "centroid": (lon, lat)}


def by_state(out):
    return {o["state"]: o for o in out}


def test_states():
    base = [kiln(74.0, 31.0, "FCBK"), kiln(74.1, 31.0, "FCBK"), kiln(74.2, 31.0, "Zigzag"), kiln(74.3, 31.0, "FCBK")]
    dets = [kiln(74.0 + 0.0001, 31.0, "FCBK"),      # same kiln, ~10 m shift
            kiln(74.1, 31.0, "Zigzag"),             # converted
            kiln(74.2, 31.0, "Zigzag"),             # still zigzag
            kiln(74.5, 31.0, "FCBK")]               # new
    out = track(base, dets, TO_UTM)
    assert len(out) == 5
    s = {(o["kind"], o["state"]) for o in out}
    assert s == {("matched", "NON_ZIGZAG"), ("matched", "CONVERTED"), ("matched", "ZIGZAG"),
                 ("new", "NEW"), ("not_seen", "NOT_SEEN")}
    st = by_state(out)
    assert st["CONVERTED"]["prevState"] == "NON_ZIGZAG"
    assert st["NEW"]["prevState"] is None
    assert st["NOT_SEEN"]["centroid"] == (74.3, 31.0) and st["NOT_SEEN"]["confidence"] == 0.0
    # kiln IDs come from the baseline position for matched kilns (stable across runs)
    assert st["NON_ZIGZAG"]["idPoint"] == (74.0, 31.0)


def test_far_detection_does_not_match():
    out = track([kiln(74.0, 31.0, "FCBK")], [kiln(74.0 + 2 * D, 31.0, "FCBK")], TO_UTM)
    assert sorted(o["state"] for o in out) == ["NEW", "NOT_SEEN"]


def test_one_to_one_and_no_data_skips_not_seen():
    base = [kiln(74.0, 31.0, "FCBK")]
    dets = [kiln(74.0, 31.0, "FCBK"), kiln(74.0 + 0.0002, 31.0, "FCBK", 0.5)]
    out = track(base, dets, TO_UTM)
    assert sorted(o["state"] for o in out) == ["NEW", "NON_ZIGZAG"]
    out = track([kiln(75.0, 31.0, "FCBK")], [], TO_UTM, has_data=lambda lon, lat: False)
    assert out == []
