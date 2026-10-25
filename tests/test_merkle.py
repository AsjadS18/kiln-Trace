import copy

import pytest
from eth_utils import keccak as eth_keccak

from pipeline import merkle as m
from tests.helpers import BASE_RECORD, make_records


def test_keccak_matches_ethereum():
    # keccak256("") is a well-known constant; also cross-check against eth_utils.
    assert m.k256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert m.k256(b"KilnTrace") == eth_keccak(b"KilnTrace")


def test_canonical_is_sorted_and_compact():
    assert m.canonical({"b": 1, "a": [2, {"d": True, "c": None}]}) == b'{"a":[2,{"c":null,"d":true}],"b":1}'


def test_canonical_independent_of_key_order():
    shuffled = dict(reversed(list(BASE_RECORD.items())))
    assert m.record_hash(shuffled) == m.record_hash(BASE_RECORD)


@pytest.mark.parametrize("bad", [
    {"x": 1.0},
    {"x": [1, 2.5]},
    {"x": 2**53},
    {"x": "kilné"},
    {"x": (1, 2), "y": object()},
])
def test_canonical_rejects_non_portable_values(bad):
    with pytest.raises(m.CanonicalError):
        m.canonical(bad)


def test_kiln_id_format_and_value():
    kid = m.kiln_id_from_h3("8a3c2b1a2b3ffff")
    assert kid.startswith("0x") and len(kid) == 66 and kid == kid.lower()
    assert kid == "0x" + eth_keccak(b"KT1:8a3c2b1a2b3ffff").hex()


def test_leaf_matches_independent_encoding():
    # abi.encode(bytes32, bytes32) is just the two 32-byte words concatenated.
    rh = m.record_hash(BASE_RECORD)
    raw = bytes.fromhex(BASE_RECORD["kilnId"][2:]) + rh
    assert m.leaf(BASE_RECORD["kilnId"], rh) == eth_keccak(eth_keccak(raw))


def test_single_record_root_is_leaf_with_empty_proof():
    lf = m.record_leaf(BASE_RECORD)
    layers = m.build([lf])
    assert m.root(layers) == lf
    assert m.proof(layers, lf) == []
    assert m.verify([], lf, lf)


@pytest.mark.parametrize("n", range(1, 18))
def test_every_proof_verifies(n):
    recs = make_records(n)
    leaves = [m.record_leaf(r) for r in recs]
    layers = m.build(leaves)
    rt = m.root(layers)
    for lf in leaves:
        assert m.verify(m.proof(layers, lf), rt, lf)


def test_root_independent_of_record_order():
    recs = make_records(7)
    a = m.root(m.build([m.record_leaf(r) for r in recs]))
    b = m.root(m.build([m.record_leaf(r) for r in reversed(recs)]))
    assert a == b


@pytest.mark.parametrize("field,value", [
    ("class", "Zigzag"),
    ("confidenceBp", 8732),
    ("centroid_e6", [74447124, 31118456]),
    ("thermalDtCk", None),
])
def test_tampered_record_fails(field, value):
    recs = make_records(7)
    layers = m.build([m.record_leaf(r) for r in recs])
    rt = m.root(layers)
    original_leaf = m.record_leaf(recs[3])
    pf = m.proof(layers, original_leaf)

    tampered = copy.deepcopy(recs[3])
    tampered[field] = value
    assert not m.verify(pf, rt, m.record_leaf(tampered))
    # and the root of a tree rebuilt with the tampered record changes
    recs[3] = tampered
    assert m.root(m.build([m.record_leaf(r) for r in recs])) != rt


def test_wrong_kiln_id_fails():
    recs = make_records(5)
    layers = m.build([m.record_leaf(r) for r in recs])
    rh = m.record_hash(recs[0])
    good = m.leaf(recs[0]["kilnId"], rh)
    bad = m.leaf(recs[1]["kilnId"], rh)
    assert not m.verify(m.proof(layers, good), m.root(layers), bad)


def test_duplicate_and_empty_rejected():
    lf = m.record_leaf(BASE_RECORD)
    with pytest.raises(ValueError):
        m.build([lf, lf])
    with pytest.raises(ValueError):
        m.build([])


def test_tree_for_records_output():
    recs = make_records(4)
    t = m.tree_for_records(recs)
    rt = m.hex_to_bytes32(t["root"])
    for item in t["items"]:
        lf = m.hex_to_bytes32(item["leaf"])
        assert m.verify([m.hex_to_bytes32(p) for p in item["proof"]], rt, lf)
