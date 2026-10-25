"""Shared record hashing and Merkle tree (FROZEN interface).

Used by the pipeline, backend and verifier. web/lib/merkle.ts must produce identical bytes.

- recordHash = keccak256(canonical JSON)
- leaf       = keccak256(keccak256(abi.encode(bytes32 kilnId, bytes32 recordHash)))
- node       = keccak256(min(a, b) || max(a, b))   (OpenZeppelin MerkleProof, sorted pairs)
- leaves are sorted; an odd node at the end of a level is carried up unchanged
"""
from __future__ import annotations

import json

from Crypto.Hash import keccak
from eth_abi import encode

MAX_SAFE_INT = 2**53 - 1  # largest integer JavaScript represents exactly


class CanonicalError(ValueError):
    """Raised when data cannot be hashed identically in every language."""


def k256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def _check_portable(obj, path: str = "$") -> None:
    """Reject values that different languages would serialise differently."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, float):
        raise CanonicalError(f"float at {path}: use scaled integers (_e6, basis points, centi-kelvin)")
    if isinstance(obj, int):
        if abs(obj) > MAX_SAFE_INT:
            raise CanonicalError(f"integer at {path} exceeds 2^53-1 (not JS-safe)")
        return
    if isinstance(obj, str):
        if not obj.isascii():
            raise CanonicalError(f"non-ASCII string at {path}")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonicalError(f"non-string key at {path}")
            _check_portable(k, f"{path}.<key>")
            _check_portable(v, f"{path}.{k}")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check_portable(v, f"{path}[{i}]")
        return
    raise CanonicalError(f"unsupported type {type(obj).__name__} at {path}")


def canonical(obj) -> bytes:
    """Canonical JSON bytes: sorted keys, no whitespace, UTF-8."""
    _check_portable(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def record_hash(record: dict) -> bytes:
    return k256(canonical(record))


def hex_to_bytes32(h: str) -> bytes:
    if not (isinstance(h, str) and h.startswith("0x") and len(h) == 66):
        raise ValueError(f"expected 0x-prefixed 32-byte hex, got {h!r}")
    return bytes.fromhex(h[2:])


def to_hex(b: bytes) -> str:
    return "0x" + b.hex()


def kiln_id_from_h3(h3_cell: str) -> str:
    """Stable kiln ID, assigned once at first sighting."""
    return to_hex(k256(("KT1:" + h3_cell).encode("ascii")))


def leaf(kiln_id_hex: str, rec_hash: bytes) -> bytes:
    if len(rec_hash) != 32:
        raise ValueError("record hash must be 32 bytes")
    return k256(k256(encode(["bytes32", "bytes32"], [hex_to_bytes32(kiln_id_hex), rec_hash])))


def record_leaf(record: dict) -> bytes:
    return leaf(record["kilnId"], record_hash(record))


def _pair(a: bytes, b: bytes) -> bytes:
    return k256(a + b) if a < b else k256(b + a)


def build(leaves: list[bytes]) -> list[list[bytes]]:
    """Return all tree layers; layers[-1][0] is the root."""
    if not leaves:
        raise ValueError("cannot build a tree with no leaves")
    if len(set(leaves)) != len(leaves):
        raise ValueError("duplicate leaves (same kilnId and record twice in one run)")
    level = sorted(leaves)
    layers = [level]
    while len(level) > 1:
        nxt = [_pair(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
        layers.append(level)
    return layers


def root(layers: list[list[bytes]]) -> bytes:
    return layers[-1][0]


def proof(layers: list[list[bytes]], lf: bytes) -> list[bytes]:
    idx = layers[0].index(lf)
    out = []
    for level in layers[:-1]:
        sib = idx ^ 1
        if sib < len(level):
            out.append(level[sib])
        idx //= 2
    return out


def verify(proof_nodes: list[bytes], root_hash: bytes, lf: bytes) -> bool:
    """Same algorithm as OpenZeppelin MerkleProof.verify."""
    h = lf
    for p in proof_nodes:
        h = _pair(h, p)
    return h == root_hash


def tree_for_records(records: list[dict]) -> dict:
    """Convenience: hashes, root and proofs for a run. Hex strings, ready for JSON."""
    hashes = [record_hash(r) for r in records]
    leaves = [leaf(r["kilnId"], h) for r, h in zip(records, hashes)]
    layers = build(leaves)
    rt = root(layers)
    return {
        "root": to_hex(rt),
        "items": [
            {
                "kilnId": r["kilnId"],
                "recordHash": to_hex(h),
                "leaf": to_hex(lf),
                "proof": [to_hex(p) for p in proof(layers, lf)],
            }
            for r, h, lf in zip(records, hashes, leaves)
        ],
    }
