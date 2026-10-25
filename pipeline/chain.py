"""Compile, deploy and use KilnTraceRegistry from Python (PDF section 9).

    python pipeline/chain.py compile     # contracts/src -> contracts/abi/KilnTraceRegistry.json (+ bytecode)
    python pipeline/chain.py deploy      # deploy to RPC_URL (Amoy), grant roles, save contracts/deployments/<chainId>.json
    python pipeline/chain.py commit      # commit this run's Merkle root (data/runs/<run_id>/evidence.json)

Needs in .env: RPC_URL, CHAIN_ID, PUBLISHER_PRIVATE_KEY (test wallet only).
Compiler: solc 0.8.24 via py-solc-x, stored in .solcx/ inside the project.
OpenZeppelin: contracts/node_modules/@openzeppelin/contracts (npm install in contracts/).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOLC_VERSION = "0.8.24"
SRC = ROOT / "contracts" / "src" / "KilnTraceRegistry.sol"
NODE_MODULES = ROOT / "contracts" / "node_modules"
ARTIFACT = ROOT / "contracts" / "abi" / "KilnTraceRegistry.json"
DEPLOY_DIR = ROOT / "contracts" / "deployments"
EXPLORERS = {80002: "https://amoy.polygonscan.com"}
IMPORT_RE = re.compile(r'import\s+(?:\{[^}]*\}\s+from\s+)?"([^"]+)"')


# ---------- compile ----------

def _collect_sources() -> dict[str, dict]:
    """Main contract plus every OpenZeppelin file it imports (resolved recursively)."""
    sources: dict[str, dict] = {}
    todo = [("KilnTraceRegistry.sol", SRC)]
    while todo:
        key, path = todo.pop()
        if key in sources:
            continue
        if not path.exists():
            raise SystemExit(f"missing {path} - run: cd contracts && npm install")
        text = path.read_text(encoding="utf-8")
        sources[key] = {"content": text}
        for imp in IMPORT_RE.findall(text):
            if imp.startswith("@"):
                k = imp
            else:   # relative import inside OpenZeppelin
                k = os.path.normpath(os.path.join(os.path.dirname(key), imp)).replace("\\", "/")
            todo.append((k, NODE_MODULES / k))
    return sources


def compile_contract() -> dict:
    import solcx
    bin_dir = ROOT / ".solcx"
    bin_dir.mkdir(exist_ok=True)

    def find():
        hits = sorted(bin_dir.glob(f"solc-v{SOLC_VERSION}*/solc*")) + sorted(bin_dir.glob(f"solc-v{SOLC_VERSION}*"))
        return next((h for h in hits if h.is_file()), None)

    solc = find()
    if solc is None:
        try:   # py-solc-x's post-install check looks in its default folder and raises; the download still works
            solcx.install_solc(SOLC_VERSION, solcx_binary_path=bin_dir)
        except Exception:
            pass
        solc = find()
    if solc is None:
        raise SystemExit(f"solc {SOLC_VERSION} not found in {bin_dir}")
    out = solcx.compile_standard({
        "language": "Solidity",
        "sources": _collect_sources(),
        "settings": {
            "viaIR": True,                       # avoids "stack too deep" in submitFieldCheck
            "optimizer": {"enabled": True, "runs": 200},
            "evmVersion": "paris",               # widely supported (Amoy, local test chain)
            "outputSelection": {"KilnTraceRegistry.sol": {"KilnTraceRegistry": ["abi", "evm.bytecode.object"]}},
        },
    }, solc_binary=str(solc))
    c = out["contracts"]["KilnTraceRegistry.sol"]["KilnTraceRegistry"]
    art = {"contractName": "KilnTraceRegistry", "compiler": f"solc {SOLC_VERSION} viaIR optimizer=200 evm=paris",
           "abi": c["abi"], "bytecode": "0x" + c["evm"]["bytecode"]["object"]}
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(art, indent=1), encoding="utf-8")
    return art


def load_artifact() -> dict:
    if not ARTIFACT.exists():
        return compile_contract()
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


# ---------- transactions ----------

def env() -> dict:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    need = ["RPC_URL", "PUBLISHER_PRIVATE_KEY"]
    missing = [k for k in need if not os.environ.get(k, "").strip()]
    if missing:
        raise SystemExit(f"set {', '.join(missing)} in .env")
    return {"rpc": os.environ["RPC_URL"].strip(), "key": os.environ["PUBLISHER_PRIVATE_KEY"].strip(),
            "chain_id": int(os.environ.get("CHAIN_ID", "80002"))}


def add_poa(w3) -> None:
    """Polygon blocks carry long extraData (PoA style); web3.py needs this middleware to read them."""
    try:
        from web3.middleware import ExtraDataToPOAMiddleware as poa
    except ImportError:   # older web3
        from web3.middleware import geth_poa_middleware as poa
    w3.middleware_onion.inject(poa, layer=0)


def connect(rpc: str):
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
    add_poa(w3)
    if not w3.is_connected():
        raise SystemExit(f"cannot reach RPC {rpc}")
    return w3


def send(w3, fn, account=None, gas_floor_gwei: int = 30):
    """Send a contract call. account=None uses the node's unlocked default account (local tests)."""
    if account is None:
        tx_hash = fn.transact({"from": w3.eth.default_account})
    else:
        prio = max(w3.to_wei(gas_floor_gwei, "gwei"), w3.eth.max_priority_fee)   # Amoy rejects tiny tips
        base = w3.eth.get_block("latest")["baseFeePerGas"]
        tx = fn.build_transaction({"from": account.address, "nonce": w3.eth.get_transaction_count(account.address),
                                   "chainId": w3.eth.chain_id, "maxPriorityFeePerGas": prio,
                                   "maxFeePerGas": 2 * base + prio})
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if rcpt["status"] != 1:
        raise SystemExit(f"transaction failed: {w3.to_hex(tx_hash)}")
    return rcpt


def deploy(w3, account=None, art: dict | None = None):
    art = art or load_artifact()
    factory = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    admin = account.address if account else w3.eth.default_account
    rcpt = send(w3, factory.constructor(admin), account)
    c = w3.eth.contract(address=rcpt["contractAddress"], abi=art["abi"])
    for role in ("PUBLISHER_ROLE", "REVIEWER_ROLE"):
        send(w3, c.functions.grantRole(getattr(c.functions, role)().call(), admin), account)
    return c, rcpt


def date_to_unix(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def commit_batch(w3, c, root_hex: str, manifest_ref: str, model_sha: str, commit: str, scene_date: str,
                 count: int, account=None) -> tuple[int, dict]:
    code = bytes.fromhex(commit) if re.fullmatch(r"[0-9a-f]{40}", commit or "") else bytes(20)
    rcpt = send(w3, c.functions.commitBatch(bytes.fromhex(root_hex[2:]), manifest_ref, bytes.fromhex(model_sha),
                                            code, date_to_unix(scene_date), count), account)
    from web3.logs import DISCARD   # Polygon adds a fee-transfer log from a system contract; skip it
    ev = c.events.BatchCommitted().process_receipt(rcpt, errors=DISCARD)
    return int(ev[0]["args"]["batchId"]), rcpt


def contract_at(w3, address: str):
    return w3.eth.contract(address=address, abi=load_artifact()["abi"])


def deployment_file(chain_id: int) -> Path:
    return DEPLOY_DIR / f"{chain_id}.json"


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["compile", "deploy", "commit"])
    ap.add_argument("--config", default="config/run.yaml")
    args = ap.parse_args()

    if args.cmd == "compile":
        art = compile_contract()
        print(f"compiled: {len(art['abi'])} ABI entries, bytecode {len(art['bytecode']) // 2} bytes -> {ARTIFACT}")
        return

    from eth_account import Account
    e = env()
    w3 = connect(e["rpc"])
    acct = Account.from_key(e["key"])
    if w3.eth.chain_id != e["chain_id"]:
        raise SystemExit(f"RPC chain id {w3.eth.chain_id} != CHAIN_ID {e['chain_id']}")
    bal = w3.from_wei(w3.eth.get_balance(acct.address), "ether")
    print(f"chain {w3.eth.chain_id}, publisher {acct.address}, balance {bal:.4f} POL")
    explorer = EXPLORERS.get(w3.eth.chain_id, "")

    if args.cmd == "deploy":
        c, rcpt = deploy(w3, acct)
        info = {"chainId": w3.eth.chain_id, "address": c.address, "deployer": acct.address,
                "txHash": w3.to_hex(rcpt["transactionHash"]), "block": rcpt["blockNumber"],
                "explorer": f"{explorer}/address/{c.address}" if explorer else None,
                "deployedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
        deployment_file(w3.eth.chain_id).write_text(json.dumps(info, indent=2), encoding="utf-8")
        print(json.dumps(info, indent=2))
        print("Add to .env:  CONTRACT_ADDRESS=" + c.address)
        return

    from pipeline.common import load_config, run_dir
    cfg = load_config(args.config)
    out_dir = run_dir(cfg)
    ev = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    dep = json.loads(deployment_file(w3.eth.chain_id).read_text(encoding="utf-8"))
    c = contract_at(w3, dep["address"])
    ref = ev["manifestCID"] or f"sha256:{ev['manifestSha256']}"
    batch_id, rcpt = commit_batch(w3, c, ev["merkleRoot"], ref, ev["modelSha256"], ev["codeCommit"],
                                  ev["sceneDate"], ev["recordCount"], acct)
    info = {"runId": ev["runId"], "chainId": w3.eth.chain_id, "contract": dep["address"], "batchId": batch_id,
            "merkleRoot": ev["merkleRoot"], "manifestRef": ref, "txHash": w3.to_hex(rcpt["transactionHash"]),
            "block": rcpt["blockNumber"],
            "explorer": f"{explorer}/tx/{w3.to_hex(rcpt['transactionHash'])}" if explorer else None}
    (out_dir / "chain.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
