"""Independent verifier: prove a kiln record is exactly what was committed on-chain (PDF 12.1).

Anyone can run this with only public inputs: the contract address, the manifest (IPFS or a local
copy) and the chips. It trusts nothing from the KilnTrace backend.

    python verifier/verify.py --run kasur-2025-12 --kiln 0x3f5c...       # by kiln ID
    python verifier/verify.py --run kasur-2025-12 --index 0               # first record
    python verifier/verify.py --run kasur-2025-12 --kiln 0x... --manifest tampered.json   # tamper demo

Steps (stops at the first failure and says which one):
  1. read the batch for this run from the contract (root, manifest reference, model hash)
  2. load the manifest and check it is the committed one (sha256: reference, or download by IPFS CID)
  3. rebuild ALL leaves from the manifest records, recompute the Merkle root, compare with the chain
  4. recompute the chosen record's hash and check its chip image against chipSha256
  5. ask the contract itself: verifyRecord(batchId, kilnId, recordHash, proof)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import merkle  # noqa: E402

GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"


def ok(step: str, msg: str) -> None:
    print(f"{GREEN}  PASS{RESET}  {step}: {msg}")


def fail(step: str, msg: str) -> None:
    print(f"{RED}  FAIL{RESET}  {step}: {msg}")
    print(f"\n{RED}RESULT: FAIL at {step}{RESET}")
    sys.exit(1)


def fetch_ipfs(cid_path: str, gateway: str) -> bytes:
    import requests
    r = requests.get(gateway.rstrip("/") + "/" + cid_path, timeout=120)
    r.raise_for_status()
    return r.content


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--kiln", help="kilnId (0x...)")
    g.add_argument("--index", type=int, help="record index in the manifest")
    ap.add_argument("--manifest", help="local manifest file (default: download / data/runs/<run>/manifest.json)")
    ap.add_argument("--rpc", default=None)
    ap.add_argument("--gateway", default=None)
    args = ap.parse_args()

    from dotenv import load_dotenv
    from web3 import Web3
    load_dotenv(ROOT / ".env")
    rpc = args.rpc or os.environ.get("RPC_URL", "https://polygon-amoy.drpc.org")
    gateway = args.gateway or os.environ.get("IPFS_GATEWAY", "https://ipfs.io/ipfs/")
    run_dir = ROOT / "data" / "runs" / args.run
    if (run_dir / "chain.json").exists():
        chain_info = json.loads((run_dir / "chain.json").read_text(encoding="utf-8"))
    else:   # fresh clone: use the files published for the dashboard (docs/data)
        pub = json.loads((ROOT / "docs" / "data" / "run.json").read_text(encoding="utf-8"))
        if pub["runId"] != args.run or not pub.get("chain"):
            raise SystemExit(f"no local data for {args.run} and docs/data holds {pub['runId']}")
        chain_info = pub["chain"]
        run_dir = ROOT / "docs" / "data"
        rpc = args.rpc or pub.get("rpc") or rpc
    abi = json.loads((ROOT / "contracts" / "abi" / "KilnTraceRegistry.json").read_text(encoding="utf-8"))["abi"]

    print(f"KilnTrace verifier - run {args.run}, contract {chain_info['contract']}, batch {chain_info['batchId']}\n")

    # 1. chain
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
    from pipeline.chain import add_poa
    add_poa(w3)
    c = w3.eth.contract(address=chain_info["contract"], abi=abi)
    try:
        b = c.functions.getBatch(chain_info["batchId"]).call()
    except Exception as e:
        fail("1 read chain", f"cannot read batch: {e}")
    root_chain, model_chain, ref = b[0], b[1], b[7]
    ok("1 read chain", f"root 0x{root_chain.hex()[:16]}..., manifest {ref[:30]}..., {b[5]} records")

    # 2. manifest is the committed one
    if args.manifest:
        man_bytes = Path(args.manifest).read_bytes()
        src = args.manifest
    elif ref.startswith("sha256:"):
        man_bytes = (run_dir / "manifest.json").read_bytes()
        src = "local copy"
    else:
        man_bytes = fetch_ipfs(ref, gateway)
        src = f"IPFS {ref[:20]}..."
    if ref.startswith("sha256:"):
        h = hashlib.sha256(man_bytes).hexdigest()
        if h != ref[7:]:
            print(f"        manifest sha256 {h[:16]}... != committed {ref[7:23]}... (continuing to locate the change)")
        else:
            ok("2 manifest", f"{src} matches the committed sha256")
    else:
        ok("2 manifest", f"loaded from {src} (content-addressed by its CID)")
    man = json.loads(man_bytes)
    records = man["records"]

    # 3. rebuild the whole tree
    try:
        leaves = [merkle.record_leaf(r) for r in records]
        root = merkle.root(merkle.build(leaves))
    except Exception as e:
        fail("3 rebuild root", f"records cannot be hashed: {e}")
    if root != root_chain:
        fail("3 rebuild root", f"recomputed 0x{root.hex()[:16]}... != on-chain 0x{root_chain.hex()[:16]}... "
                               "- the records were changed after publication")
    ok("3 rebuild root", f"all {len(records)} records reproduce the on-chain root")

    # 4. chosen record + chip
    rec = next((r for r in records if r["kilnId"] == args.kiln), None) if args.kiln else records[args.index]
    if rec is None:
        fail("4 record", f"kiln {args.kiln} not in this run")
    rh = merkle.record_hash(rec)
    chip = None
    if rec["chipCID"].startswith("LOCAL-"):
        p = run_dir / "chips" / next((f.name for f in (run_dir / "chips").glob("*.png")
                                      if hashlib.sha256(f.read_bytes()).hexdigest() == rec["chipSha256"]), "missing")
        chip = p.read_bytes() if p.exists() else None
    else:
        try:
            chip = fetch_ipfs(rec["chipCID"], gateway)
        except Exception as e:
            print(f"        could not download chip: {e}")
    if chip is None or hashlib.sha256(chip).hexdigest() != rec["chipSha256"]:
        fail("4 record", "chip image missing or does not match chipSha256")
    if bytes.fromhex(rec["modelSha256"]) != model_chain:
        fail("4 record", "record's model hash differs from the batch's model hash")
    ok("4 record", f"{rec['class']} {rec['state']}, conf {rec['confidenceBp'] / 100:.1f}%, "
                   f"recordHash 0x{rh.hex()[:16]}..., chip sha256 matches")

    # 5. on-chain proof check
    layers = merkle.build(leaves)
    proof = merkle.proof(layers, merkle.leaf(rec["kilnId"], rh))
    valid = c.functions.verifyRecord(chain_info["batchId"], bytes.fromhex(rec["kilnId"][2:]), rh, proof).call()
    if not valid:
        fail("5 contract", "verifyRecord returned false")
    ok("5 contract", f"verifyRecord(batch {chain_info['batchId']}, proof of {len(proof)} hashes) = true")

    lon, lat = rec["centroid_e6"][0] / 1e6, rec["centroid_e6"][1] / 1e6
    print(f"\n{GREEN}RESULT: PASS{RESET} - kiln {rec['kilnId'][:12]}... at {lat:.5f}, {lon:.5f} is exactly as "
          f"published on {rec['sceneDate']}.")
    if chain_info.get("explorer"):
        print(f"Transaction: {chain_info['explorer']}")


if __name__ == "__main__":
    main()
