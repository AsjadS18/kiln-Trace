"""Validate records and manifests against the frozen JSON schemas."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


@lru_cache(maxsize=None)
def _validators():
    record = json.loads((SCHEMA_DIR / "kiln_record.schema.json").read_text(encoding="utf-8"))
    manifest = json.loads((SCHEMA_DIR / "manifest.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        (record["$id"], Resource.from_contents(record)),
        (manifest["$id"], Resource.from_contents(manifest)),
    ])
    return (
        Draft202012Validator(record, registry=registry),
        Draft202012Validator(manifest, registry=registry),
    )


def _check(validator, obj, what: str) -> None:
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        lines = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:10]]
        raise ValueError(f"invalid {what}:\n  " + "\n  ".join(lines))


def validate_record(record: dict) -> None:
    _check(_validators()[0], record, "record")


def validate_manifest(manifest: dict) -> None:
    _check(_validators()[1], manifest, "manifest")
