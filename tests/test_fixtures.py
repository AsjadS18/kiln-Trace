"""Checks the committed sample runs stay consistent with merkle.py and the schemas."""
import json
from pathlib import Path

import pytest

from pipeline import merkle as m
from pipeline.schema import validate_manifest

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "sample_run"
pytestmark = pytest.mark.skipif(not (OUT / "index.json").exists(), reason="fixtures not generated")


def _runs():
    return json.loads((OUT / "index.json").read_text(encoding="utf-8"))["runs"]


def test_fixture_manifests_valid_and_roots_match():
    for run in _runs():
        man = json.loads((OUT / run["manifest"]).read_text(encoding="utf-8"))
        validate_manifest(man)
        rebuilt = m.tree_for_records(man["records"])
        assert rebuilt["root"] == man["merkle"]["root"] == run["merkleRoot"]


def test_fixture_proofs_verify_and_chips_match():
    import hashlib
    for run in _runs():
        man = json.loads((OUT / run["manifest"]).read_text(encoding="utf-8"))
        proofs = json.loads((OUT / run["proofs"]).read_text(encoding="utf-8"))
        root = m.hex_to_bytes32(proofs["root"])
        by_id = {r["kilnId"]: r for r in man["records"]}
        for item in proofs["items"]:
            rec = by_id[item["kilnId"]]
            assert m.to_hex(m.record_hash(rec)) == item["recordHash"]
            assert m.verify([m.hex_to_bytes32(p) for p in item["proof"]], root, m.record_leaf(rec))
            chip = (OUT / "chips" / f"{rec['h3']}.png").read_bytes()
            assert hashlib.sha256(chip).hexdigest() == rec["chipSha256"]
