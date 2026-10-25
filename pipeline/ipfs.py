"""Pin files to IPFS via Pinata. Needs PINATA_JWT in .env (never commit it)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PIN_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"


def _jwt() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    jwt = os.environ.get("PINATA_JWT", "").strip()
    if not jwt:
        raise SystemExit("PINATA_JWT is not set in .env")
    return jwt


def pin_files(files: list[tuple[str, bytes]], name: str, folder: bool = True) -> str:
    """Pin one file, or several files under a common folder (paths like 'chips/a.png').
    Returns the CID (CIDv1). For a folder, files are reachable at <CID>/<file name>."""
    multipart = [("file", (path, data, "application/octet-stream")) for path, data in files]
    if not folder and len(files) != 1:
        raise ValueError("folder=False needs exactly one file")
    resp = requests.post(
        PIN_URL,
        headers={"Authorization": f"Bearer {_jwt()}"},
        files=multipart,
        data={"pinataMetadata": json.dumps({"name": name}), "pinataOptions": json.dumps({"cidVersion": 1})},
        timeout=600,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Pinata error {resp.status_code}: {resp.text[:300]}")
    return resp.json()["IpfsHash"]
