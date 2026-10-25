import pytest

from ml.obb_metrics import at_threshold, confusion, iou, match_image, pick_threshold, sweep


def sq(x, y, s=10):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]


def test_iou_basic():
    assert iou(sq(0, 0), sq(0, 0)) == pytest.approx(1.0)
    assert iou(sq(0, 0), sq(5, 0)) == pytest.approx(50 / 150)
    assert iou(sq(0, 0), sq(50, 50)) == 0.0


def test_match_and_threshold():
    gts = [(1, sq(0, 0)), (2, sq(40, 40)), (1, sq(80, 80))]
    preds = [(1, 0.9, sq(1, 0)),      # hits kiln 0, right class
             (1, 0.6, sq(40, 41)),    # hits kiln 1 (zigzag) but says FCBK
             (2, 0.3, sq(100, 0)),    # false alarm
             (1, 0.8, sq(2, 1))]      # duplicate of kiln 0 -> false alarm
    m = match_image(gts, preds)
    r = at_threshold(m, 0.5)
    assert (r["tp"], r["fp"], r["fn"]) == (2, 1, 1)
    r = at_threshold(m, 0.0)
    assert (r["tp"], r["fp"], r["fn"]) == (2, 2, 1)
    r = at_threshold(m, 0.95)
    assert (r["tp"], r["fp"], r["fn"]) == (0, 0, 3)


def test_confusion_two_class():
    gts = [(1, sq(0, 0)), (2, sq(40, 40)), (0, sq(80, 80))]
    preds = [(1, 0.9, sq(0, 0)), (1, 0.9, sq(40, 40)), (2, 0.9, sq(200, 200))]
    c = confusion(match_image(gts, preds), 0.5)
    two = c["two_class"]
    assert two["non_zigzag"]["non_zigzag"] == 1
    assert two["zigzag"]["non_zigzag"] == 1
    assert two["non_zigzag"]["missed"] == 1          # the CFCBK kiln
    assert two["false_alarm"]["zigzag"] == 1
    assert c["type_accuracy_on_detected"] == 0.5
    assert c["full"][2][1] == 1 and c["full"][0][3] == 1 and c["full"][3][2] == 1


def test_pick_threshold_prefers_recall_above_precision_floor():
    gts = [(1, sq(i * 20, 0)) for i in range(4)]
    preds = [(1, 0.9, sq(0, 0)), (1, 0.8, sq(20, 0)), (1, 0.7, sq(500, 500)),
             (1, 0.6, sq(40, 0)), (1, 0.2, sq(600, 600)), (1, 0.1, sq(700, 700))]
    rows = sweep(match_image(gts, preds), [0.1, 0.5, 0.65, 0.85])
    best = pick_threshold(rows, 0.7)
    assert best["conf"] == 0.5 and best["recall"] == 0.75
    assert "max recall" in pick_threshold(rows, 0.7)["rule"]
    assert "best F1" in pick_threshold(rows, 1.01)["rule"]   # unreachable precision floor
