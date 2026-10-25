# Security and data-integrity assessment

KilnTrace produces evidence that regulators, kiln owners, courts and NGOs may disagree about.
The design goal is that **nobody, including the KilnTrace team, can change a published result
without being caught**, and that anyone can check this without trusting us.

## What is anchored and how

| Item | Where it lives | Integrity mechanism |
|---|---|---|
| Kiln record (location, type, confidence, state, risk, image hash, model hash) | Run manifest (JSON) | `recordHash = keccak256(canonical JSON)`; canonical = sorted keys, no whitespace, integers only (no floats) so every language hashes identical bytes |
| All records of a run | Merkle tree | OpenZeppelin-compatible: leaf = `keccak256(keccak256(abi.encode(kilnId, recordHash)))`, sorted-pair internal nodes |
| Merkle root, manifest reference, model SHA-256, code commit, scene date, record count | `KilnTraceRegistry` on Polygon Amoy | One `commitBatch` transaction per run, timestamped by the block |
| Kiln image chips | IPFS (Pinata) or local archive | SHA-256 of each chip is inside the hashed record |
| Model weights | Frozen file `models/kiln_v1.pt` | SHA-256 recorded in every record and every batch |

Only 32-byte hashes go on-chain: cheap (one transaction per run) and privacy-preserving, yet every
single record can be proven.

## Threats and mitigations

| Threat | Impact | Mitigation in KilnTrace | Status |
|---|---|---|---|
| Results edited after publication (by us, an official or an attacker) | False evidence | Merkle root on-chain; any edit changes the root. `verifier/verify.py` and the dashboard's "Verify on-chain" recompute it independently | Implemented, demo: one changed field -> FAIL at step 3 |
| Backdating a record | Fake history | `committedAt` = block timestamp; records carry `sceneDate`; manifest lists the exact Sentinel-2 STAC scene IDs | Implemented |
| Silently swapping the AI model | Unaccountable decisions | Model SHA-256 stored per record and per batch; verifier checks they match | Implemented |
| Cherry-picking or re-processing imagery | Biased evidence | Manifest records imagery collection, date window, scene IDs, composite method, scaling and mosaic SHA-256, so anyone can rebuild the run | Implemented |
| Code changed between runs | Irreproducible results | Git commit hash stored in manifest and on-chain (`codeCommit`) | Implemented |
| Fake or spam field reports | Polluted ground truth | EIP-712 signatures with per-reporter nonces (replay rejected), relayer rate limits and GPS distance checks, reviewer moderation | Contract + tests implemented; relayer/app are roadmap |
| Stolen publisher key | Fake batches | Role-based access (`PUBLISHER_ROLE`, `REVIEWER_ROLE`, admin can revoke); separate keys per role; multisig/hardware wallet for admin in production | Roles implemented and tested |
| Reporter safety and privacy | Retaliation | Pseudonymous addresses; no names or phone numbers in evidence; only hashes and CIDs on-chain | By design |
| Evidence files disappear (IPFS unpinned) | Evidence unavailable | Pin with more than one provider plus a local archive; the on-chain root still proves integrity once files are restored | Partially (local archive + optional Pinata) |
| Satellite or model error | Wrong accusation | Output is a priority score, never proof; confidence shown; human field check and open dispute process; model metrics published (`ml/results.md`) | Implemented in data model and contract |
| Smart-contract bugs | Broken registry | Small surface; OpenZeppelin `AccessControl`, `EIP712`, `ECDSA`, `MerkleProof`; automated tests on a local chain | Implemented |
| Secrets leaking from the repo | Key theft | Private keys only in `.env` (git-ignored); test wallets only; `.env.example` has no values | Implemented |

## How to check a record yourself

```bash
python verifier/verify.py --run kasur-2026-02 --index 0
```

1. reads the batch (root, manifest reference, model hash) from the contract over public RPC
2. loads the manifest and checks it is the committed one
3. rebuilds **all** leaves, recomputes the Merkle root and compares it with the chain
4. recomputes the chosen record's hash and checks its image against `chipSha256`
5. calls `verifyRecord(batchId, kilnId, recordHash, proof)` on the contract

Tamper demo: `python verifier/make_tampered.py --run kasur-2026-02 --index 0` changes one kiln's class
in a copy of the manifest; verifying that copy fails at step 3.

## Tests that back these claims

- `tests/test_merkle.py`: hashing, canonical JSON, proofs for 1-17 records, tamper detection
- `tests/test_chain_parity.py`: Python tree vs the real compiled contract on a local EVM: every record
  verifies, a changed field fails, EIP-712 signature accepted and replay rejected, only publishers commit
- `tests/test_schema.py`: records and manifests are validated against frozen JSON Schemas before hashing

## Known limits

- Anchoring proves a record was not changed **after** publication. It cannot prove the original
  observation was right; that is why inputs, model hash and code commit are recorded and why field
  checks and disputes exist.
- Amoy is a public testnet. Production would use a mainnet or a permissioned chain with multisig governance.
