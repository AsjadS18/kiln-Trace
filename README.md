# KilnTrace

**Track 4: Climate Data & Environmental Monitoring** — IEEE ClimateChain Global Hackathon.

AI finds every brick kiln from free satellite images, flags the ones that don't meet Punjab's zigzag
requirement, and locks the evidence on-chain so inspection records can't be faked or erased.

**Live dashboard:** _GitHub Pages URL_ · **Demo video:** _link_ ·
**Contract:** [`0x31Edb74a…9f741d24` on Polygon Amoy](https://amoy.polygonscan.com/address/0x31Edb74aaff280103B80fFe8e3deD9bc9f741d24)

## The problem

South Asia's brick kiln belt holds 55,000+ kilns, about 10,000 of them in Punjab, Pakistan. They are a
major source of black carbon and PM2.5 during the winter smog season. Punjab requires zigzag firing
technology and orders shutdowns during smog episodes, but enforcement relies on slow ground
inspection that both regulators and kiln owners contest. Research models stop at a map; nobody has
a shared record that everyone accepts as unaltered.

## What KilnTrace does

```
Sentinel-2 (free, 10 m)  ->  YOLO-OBB detector  ->  change tracking  ->  evidence records
        |                     kiln + type            vs 2023-24 labels     Merkle tree
        v                                                                       |
 cloud-free mosaic                                                              v
 (same grid + scaling                                  Polygon Amoy: commitBatch(root, manifest,
  as training data)                                     model hash, code commit)
                                                                               |
                     public dashboard + independent verifier  <----------------+
```

1. **Fetch** — least-cloudy Sentinel-2 L2A scene per tile for the district (Microsoft Planetary Computer).
2. **Detect** — YOLO-OBB finds kilns and classifies FCBK / CFCBK (non-compliant) vs Zigzag (compliant).
3. **Track** — matches kilns to the 2023-24 SentinelKilnDB labels: non-zigzag, zigzag, possible conversion, new, not seen.
4. **Anchor** — every kiln becomes one integer-only JSON record; all records go into a Merkle tree; the root,
   manifest hash, model SHA-256 and git commit are committed on-chain in one transaction.
5. **Verify** — anyone can recompute the root from the published manifest and ask the contract to
   confirm any record, from the command line or in the browser.

## Results

### Model — YOLO11s-OBB, SentinelKilnDB held-out test split (18,492 tiles, 12,819 kilns)

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| **all (3 classes)** | 0.773 | 0.764 | **0.800** | 0.524 |
| CFCBK | 0.875 | 0.681 | 0.782 | 0.531 |
| FCBK | 0.736 | 0.788 | 0.789 | 0.500 |
| Zigzag | 0.709 | 0.824 | 0.828 | 0.540 |

- **Class-agnostic mAP50 (any kiln): 0.917.** The SentinelKilnDB paper reports 0.875 (RT-DETR), 0.869
  (TerraMind) and 0.867 (Galileo); evaluation code differs, so treat the comparison as indicative.
- **Compliance view** (non-zigzag vs zigzag, the regulator's question): 84% type accuracy on detected kilns.
- **Operating point** conf 0.25: precision 0.794, recall 0.880. Trained 50 epochs on one RTX 3060 (~4 h).
- Frozen model SHA-256 `f5f038e1…921d4079b`, recorded with every on-chain batch.
  Full report: [`ml/results.md`](ml/results.md).

| PR curve | Confusion matrix (normalised) | Training curves |
|---|---|---|
| ![PR curve](docs/images/model/BoxPR_curve.png) | ![Confusion matrix](docs/images/model/confusion_matrix_normalized.png) | ![Training](docs/images/model/training_curves.png) |

### Kasur District run — Sentinel-2, Feb-Mar 2026, 3,925 km²

| | Count |
|---|---|
| Kilns detected | 730 (559 FCBK, 169 zigzag, 2 CFCBK) |
| Kilns tracked — one on-chain record each | 889 |
| Non-zigzag (non-compliant design) | 387 |
| Zigzag | 55 |
| Possible conversions to zigzag (need field check) | 86 |
| New since 2023-24 | 202 |
| Not seen — possibly closed (need field check) | 159 |
| 2023-24 hand-labelled kilns found again (within 150 m) | 80% of 687 |

Committed as **batch #1** on Polygon Amoy
([transaction](https://amoy.polygonscan.com/tx/0x674ae2767db80dc20391bd4961dae565edcdbdbc8a8f5effc079d0a7d5a39054)),
Merkle root `0xd1e2a6a2…ddfaeed6f`. `verifier/verify.py` passes all 5 checks; changing one field in the
manifest fails at step 3 (root mismatch).

## Verify it yourself

```bash
python verifier/verify.py --run kasur-2026-02 --index 0
# tamper demo
python verifier/make_tampered.py --run kasur-2026-02 --index 0
python verifier/verify.py --run kasur-2026-02 --index 0 --manifest data/runs/kasur-2026-02/manifest_tampered.json
```

Or open the dashboard, click a kiln and press **Verify on-chain**: your browser recomputes all record
hashes and the Merkle root and calls `verifyRecord` on the contract directly.

## Lessons that mattered

- **Match the training grid exactly.** SentinelKilnDB tiles were downloaded from Google Earth Engine in
  EPSG:4326 at `scale=10`, i.e. square 0.0000898° pixels (10 m N-S but 8.6 m E-W at Kasur), and each
  128 px tile is min-max stretched per band. Inference uses the same grid and scaling.
- **Season matters for kiln type.** December smog washes out the reddish brick colour that separates
  zigzag from FCBK: with the same intermediate model, December imagery gave 16 zigzag kilns and clear
  Feb-Mar imagery 124 (169 with the final model).
- **No floats in hashed data.** Coordinates are micro-degree integers, confidence in basis points, so
  Python, Solidity and the browser hash identical bytes.

## Repository

```
ml/          dataset conversion, label checks, training, evaluation, model freezing
pipeline/    fetch, tiles, infer, track, evidence, ipfs, chain, export_web, merkle (shared)
contracts/   KilnTraceRegistry.sol (OpenZeppelin AccessControl, EIP712, ECDSA, MerkleProof), ABI, deployments
verifier/    independent verifier + tamper demo
schemas/     frozen JSON Schemas for records and manifests
config/      AOI, run settings, smog-ban windows
docs/        dashboard (GitHub Pages), security and impact write-ups, images
tests/       pytest suite incl. Python <-> contract parity on a local EVM
fixtures/    fake sample runs for UI development
```

## Run it

```bash
conda create -n kilntrace -c conda-forge python=3.11 -y && conda activate kilntrace
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements-lock.txt
pip install py-solc-x "eth-tester>=0.14.0b1" "py-evm>=0.12.1b1,<0.13"
cd contracts && npm install && cd ..
python -m pytest -q

# data + model
hf download SustainabilityLabIITGN/SentinelKilnDB --repo-type dataset --local-dir data/skdb
python ml/prepare_dataset.py && python ml/train.py
python ml/eval.py --weights runs/kiln_s_256/weights/best.pt
python ml/freeze.py --weights runs/kiln_s_256/weights/best.pt --version v1

# one run (config/run.yaml)
python pipeline/fetch.py && python pipeline/infer.py && python pipeline/track.py
python pipeline/evidence.py            # add --ipfs with PINATA_JWT in .env
python pipeline/chain.py deploy        # once; needs RPC_URL + PUBLISHER_PRIVATE_KEY in .env (test wallet)
python pipeline/chain.py commit
python pipeline/export_web.py          # dashboard data -> docs/data
```

## Security, impact, limitations

- [docs/security.md](docs/security.md) — threat model and data-integrity assessment
- [docs/impact.md](docs/impact.md) — climate impact method (measured outputs, enforcement efficiency, avoided-emissions formula)
- Kiln type from 10 m imagery is the weakest link; it is shown as a candidate needing a field check.
- Detecting active firing during smog bans needs thermal data (Landsat) — roadmap.
- On-chain anchoring proves records were not changed after publication, not that the observation was right;
  that is why the model hash, inputs and a dispute process are part of the design.
- Roadmap: field-check PWA and relayer (contract support already built and tested), province-wide runs,
  thermal activity scoring, reviewer workflow for disputes, mainnet or permissioned deployment.

## Training data checks

SentinelKilnDB converted to YOLO-OBB: 114,300 tiles (128 x 128 px). Box counts match the dataset card
exactly (train 63,787 / val 21,042 / test 12,819), with 0 malformed labels and 0 class mismatches against
the DOTA labels. Random training tiles per class, labels drawn on top (tiles upscaled 4x; yellow dot =
first corner):

| FCBK | Zigzag | CFCBK |
|---|---|---|
| ![FCBK labels](docs/images/label_check/train_FCBK.png) | ![Zigzag labels](docs/images/label_check/train_Zigzag.png) | ![CFCBK labels](docs/images/label_check/train_CFCBK.png) |

## Credits and licence notes

Training data: **SentinelKilnDB** (Sustainability Lab, IIT Gandhinagar; NeurIPS 2025 Datasets and
Benchmarks), CC BY-NC 4.0, non-commercial use.
https://huggingface.co/datasets/SustainabilityLabIITGN/SentinelKilnDB

Satellite imagery: Copernicus Sentinel-2 via Microsoft Planetary Computer. District boundaries:
geoBoundaries (PAK ADM2). Basemap: Esri World Imagery. Policy figures: Express Tribune, 4 Aug 2026.
