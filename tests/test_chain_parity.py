"""Mandatory parity test (PDF 8.2): Python Merkle tree vs the real contract on a local chain.

Needs: pip install py-solc-x "eth-tester[py-evm]"  and  cd contracts && npm install
Skipped automatically if any of those are missing.
"""
import copy
from pathlib import Path

import pytest

solcx = pytest.importorskip("solcx")
pytest.importorskip("eth_tester")
ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "contracts" / "node_modules" / "@openzeppelin" / "contracts").exists():
    pytest.skip("OpenZeppelin not installed (cd contracts && npm install)", allow_module_level=True)

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_typed_data  # noqa: E402
from web3 import EthereumTesterProvider, Web3  # noqa: E402

from pipeline import chain, merkle  # noqa: E402
from tests.helpers import make_records  # noqa: E402


@pytest.fixture(scope="module")
def env():
    art = chain.compile_contract()
    w3 = Web3(EthereumTesterProvider())
    w3.eth.default_account = w3.eth.accounts[0]
    c, _ = chain.deploy(w3, None, art)
    return w3, c


def _commit(w3, c, records):
    tree = merkle.tree_for_records(records)
    batch_id, _ = chain.commit_batch(w3, c, tree["root"], "sha256:test", "ab" * 32, "0" * 40, "2025-12-15",
                                     len(records))
    return batch_id, tree


def test_all_records_verify_on_chain_and_tamper_fails(env):
    w3, c = env
    records = make_records(7)
    batch_id, tree = _commit(w3, c, records)
    assert c.functions.getBatch(batch_id).call()[0] == bytes.fromhex(tree["root"][2:])
    for rec, item in zip(records, tree["items"]):
        proof = [bytes.fromhex(p[2:]) for p in item["proof"]]
        kid = bytes.fromhex(rec["kilnId"][2:])
        assert c.functions.verifyRecord(batch_id, kid, merkle.record_hash(rec), proof).call()
        bad = copy.deepcopy(rec)
        bad["class"] = "Zigzag" if rec["class"] != "Zigzag" else "FCBK"
        assert not c.functions.verifyRecord(batch_id, kid, merkle.record_hash(bad), proof).call()


def test_single_record_batch(env):
    w3, c = env
    rec = make_records(1)
    batch_id, tree = _commit(w3, c, rec)
    assert tree["items"][0]["proof"] == []
    assert c.functions.verifyRecord(batch_id, bytes.fromhex(rec[0]["kilnId"][2:]),
                                    merkle.record_hash(rec[0]), []).call()


def test_eip712_field_check_parity(env):
    """A signature made in Python (same typed data the web app will use) is accepted by the contract."""
    w3, c = env
    records = make_records(3)
    batch_id, _ = _commit(w3, c, records)
    reporter = Account.create()
    msg = {"kilnId": bytes.fromhex(records[0]["kilnId"][2:]), "batchId": batch_id, "verdict": 1,
           "observedAt": 1765800000, "evidenceCID": "bafytestevidence",
           "nonce": c.functions.nonces(reporter.address).call()}
    typed = {
        "types": {
            "EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                             {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
            "FieldCheck": [{"name": "kilnId", "type": "bytes32"}, {"name": "batchId", "type": "uint256"},
                           {"name": "verdict", "type": "uint8"}, {"name": "observedAt", "type": "uint64"},
                           {"name": "evidenceCID", "type": "string"}, {"name": "nonce", "type": "uint256"}]},
        "primaryType": "FieldCheck",
        "domain": {"name": "KilnTrace", "version": "1", "chainId": w3.eth.chain_id, "verifyingContract": c.address},
        "message": msg,
    }
    sig = Account.sign_message(encode_typed_data(full_message=typed), reporter.key).signature
    args = (msg["kilnId"], batch_id, 1, msg["observedAt"], msg["evidenceCID"], reporter.address, sig)
    chain.send(w3, c.functions.submitFieldCheck(*args))
    assert c.functions.checkCount().call() >= 1
    assert c.functions.nonces(reporter.address).call() == 1
    with pytest.raises(Exception):          # replay with the old nonce is rejected
        c.functions.submitFieldCheck(*args).transact({"from": w3.eth.default_account})


def test_only_publisher_can_commit(env):
    w3, c = env
    other = w3.eth.accounts[1]
    with pytest.raises(Exception):
        c.functions.commitBatch(b"\x01" * 32, "x", b"\x00" * 32, b"\x00" * 20, 0, 1).transact({"from": other})
