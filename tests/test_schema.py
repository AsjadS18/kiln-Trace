import copy

import pytest

from pipeline.schema import validate_manifest, validate_record
from tests.helpers import BASE_RECORD, ZERO64, make_records


def test_valid_record_passes():
    validate_record(BASE_RECORD)


def test_first_sighting_prev_state_null():
    r = copy.deepcopy(BASE_RECORD)
    r["prevState"] = None
    r["state"] = "NEW"
    validate_record(r)


@pytest.mark.parametrize("field,value", [
    ("class", "zigzag"),
    ("confidenceBp", 10001),
    ("confidenceBp", 87.31),
    ("centroid_e6", [74.447123, 31.118456]),
    ("kilnId", "0x123"),
    ("state", "CLOSED"),
    ("sceneDate", "15/12/2025"),
    ("polygon_e6", [[1, 2], [3, 4], [5, 6]]),
    ("chipSha256", "XYZ"),
])
def test_invalid_values_fail(field, value):
    r = copy.deepcopy(BASE_RECORD)
    r[field] = value
    with pytest.raises(ValueError):
        validate_record(r)


def test_missing_and_extra_fields_fail():
    r = copy.deepcopy(BASE_RECORD)
    del r["modelSha256"]
    with pytest.raises(ValueError):
        validate_record(r)
    r = copy.deepcopy(BASE_RECORD)
    r["note"] = "extra"
    with pytest.raises(ValueError):
        validate_record(r)


def _manifest(records):
    return {
        "schema": "kilntrace.manifest.v1",
        "runId": "test-run",
        "createdAt": "2026-10-25T09:00:00Z",
        "aoi": {"name": "Kasur District", "geojsonSha256": ZERO64},
        "imagery": {
            "collection": "sentinel-2-l2a", "window": ["2025-12-01", "2025-12-31"],
            "stacItems": ["S2A_TEST"], "composite": "median", "scaling": "per_tile_minmax",
            "mosaicSha256": ZERO64,
        },
        "model": {"name": "test", "sha256": ZERO64, "imgsz": 256, "conf": 0.35},
        "code": {"repo": "local", "commit": "abc1234"},
        "thresholds": {"nmsIou": 0.3, "matchMeters": 60},
        "merkle": {"root": "0x" + ZERO64, "leaf": "x", "pairs": "sorted", "recordHash": "x"},
        "records": records,
    }


def test_manifest_valid_and_checks_nested_records():
    validate_manifest(_manifest(make_records(3)))
    bad = make_records(3)
    bad[1]["class"] = "Unknown"
    with pytest.raises(ValueError):
        validate_manifest(_manifest(bad))
