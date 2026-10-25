"""Shared test data."""
import copy

from pipeline.merkle import kiln_id_from_h3

ZERO64 = "0" * 64

BASE_RECORD = {
    "schema": "kilntrace.record.v1",
    "runId": "test-run",
    "kilnId": kiln_id_from_h3("8a3c2b1a2b3ffff"),
    "h3": "8a3c2b1a2b3ffff",
    "centroid_e6": [74447123, 31118456],
    "polygon_e6": [[74446900, 31118300], [74447350, 31118320], [74447340, 31118610], [74446890, 31118590]],
    "areaM2": 12840,
    "class": "FCBK",
    "confidenceBp": 8731,
    "state": "NON_ZIGZAG",
    "prevState": "NEW",
    "riskScore": 72,
    "thermalDtCk": 315,
    "inBanWindow": False,
    "sceneDate": "2025-12-15",
    "chipSha256": "9b" * 32,
    "chipCID": "bafybeigdyrztestchip",
    "modelSha256": "c0" * 32,
}


def make_records(n: int) -> list[dict]:
    """n distinct valid records with different kiln IDs."""
    out = []
    for i in range(n):
        r = copy.deepcopy(BASE_RECORD)
        cell = f"8a3c2b1a2b{i:04x}f"[:15]
        r["h3"] = cell
        r["kilnId"] = kiln_id_from_h3(cell)
        r["centroid_e6"] = [74447123 + i * 1000, 31118456 + i * 1000]
        r["confidenceBp"] = 5000 + i
        out.append(r)
    return out
