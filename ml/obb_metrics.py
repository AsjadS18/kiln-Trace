"""Match oriented-box predictions to ground truth and compute threshold / compliance metrics.

Kept free of Ultralytics so it can be unit-tested. Boxes are 4 corner points in pixels.
Matching is class-agnostic (a detection counts if it overlaps a kiln); the class is then compared
separately, which is how the compliance view (non-zigzag vs zigzag) is built.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon

NON_ZIGZAG = {0, 1}   # CFCBK, FCBK
ZIGZAG = {2}


def group(cls: int) -> str:
    return "zigzag" if cls in ZIGZAG else "non_zigzag"


def _poly(pts) -> Polygon:
    p = Polygon(pts)
    return p if p.is_valid else p.buffer(0)


def iou(a, b) -> float:
    pa, pb = _poly(a), _poly(b)
    inter = pa.intersection(pb).area
    union = pa.area + pb.area - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Matches:
    preds: list[tuple[float, int, int | None]] = field(default_factory=list)   # (conf, pred_cls, gt_cls or None)
    gts: list[tuple[int, float | None, int | None]] = field(default_factory=list)  # (gt_cls, match_conf, pred_cls)


def match_image(gts, preds, iou_thr: float = 0.5, out: Matches | None = None) -> Matches:
    """gts: [(cls, pts)], preds: [(cls, conf, pts)]. Greedy by confidence, class-agnostic."""
    out = out or Matches()
    used: dict[int, tuple[float, int]] = {}
    for pcls, conf, ppts in sorted(preds, key=lambda p: -p[1]):
        best, best_iou = None, iou_thr
        for j, (_, gpts) in enumerate(gts):
            if j in used:
                continue
            v = iou(ppts, gpts)
            if v >= best_iou:
                best, best_iou = j, v
        if best is None:
            out.preds.append((conf, pcls, None))
        else:
            used[best] = (conf, pcls)
            out.preds.append((conf, pcls, gts[best][0]))
    for j, (gcls, _) in enumerate(gts):
        conf, pcls = used.get(j, (None, None))
        out.gts.append((gcls, conf, pcls))
    return out


def at_threshold(m: Matches, t: float) -> dict:
    tp = sum(1 for c, _, g in m.preds if c >= t and g is not None)
    fp = sum(1 for c, _, g in m.preds if c >= t and g is None)
    fn = len(m.gts) - tp
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"conf": round(t, 3), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def sweep(m: Matches, thresholds) -> list[dict]:
    return [at_threshold(m, t) for t in thresholds]


def pick_threshold(rows: list[dict], min_precision: float) -> dict:
    """Highest recall with precision >= min_precision (inspection triage favours recall).
    Falls back to best F1 if no threshold reaches the precision target."""
    ok = [r for r in rows if r["precision"] >= min_precision and r["tp"] > 0]
    if ok:
        best = max(ok, key=lambda r: (r["recall"], r["conf"]))
        return {**best, "rule": f"max recall with precision >= {min_precision}"}
    best = max(rows, key=lambda r: r["f1"])
    return {**best, "rule": f"no threshold reached precision {min_precision}; best F1"}


def confusion(m: Matches, t: float, n_classes: int = 3) -> dict:
    """Class confusion among detected kilns, plus misses and false alarms, at threshold t.
    Rows = ground truth, columns = prediction. 'missed' = kiln not detected; 'false_alarm' = no kiln."""
    full = [[0] * (n_classes + 1) for _ in range(n_classes + 1)]   # last row/col = background
    for gcls, conf, pcls in m.gts:
        if conf is not None and conf >= t:
            full[gcls][pcls] += 1
        else:
            full[gcls][n_classes] += 1
    for conf, pcls, gcls in m.preds:
        if conf >= t and gcls is None:
            full[n_classes][pcls] += 1

    groups = ["non_zigzag", "zigzag"]
    two = {g: {h: 0 for h in groups + ["missed"]} for g in groups}
    two["false_alarm"] = {h: 0 for h in groups}
    for gcls, conf, pcls in m.gts:
        if conf is not None and conf >= t:
            two[group(gcls)][group(pcls)] += 1
        else:
            two[group(gcls)]["missed"] += 1
    for conf, pcls, gcls in m.preds:
        if conf >= t and gcls is None:
            two["false_alarm"][group(pcls)] += 1

    detected = sum(two[g][h] for g in groups for h in groups)
    correct = sum(two[g][g] for g in groups)
    return {"full": full, "two_class": two,
            "type_accuracy_on_detected": round(correct / detected, 4) if detected else None}
