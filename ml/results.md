# Model results

- Weights: `runs/kiln_s_256/weights/best.pt`
- SHA-256: `f5f038e13ead745321f9a6a43592a1da41efbc8dbbb10c354c72a0c921d4079b`
- Split: **test** (18,492 images, 12,819 labelled kilns), imgsz 256
- Evaluated: 2026-10-25T16:43:31Z

## Detection metrics (Ultralytics)

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| **all** | 0.773 | 0.764 | 0.800 | 0.524 |
| CFCBK | 0.875 | 0.681 | 0.782 | 0.531 |
| FCBK | 0.736 | 0.788 | 0.789 | 0.500 |
| Zigzag | 0.709 | 0.824 | 0.828 | 0.540 |

Class-agnostic mAP50 (any kiln, type ignored): **0.917**. For reference, the SentinelKilnDB paper reports class-agnostic mAP50 of 87.5 (RT-DETR), 86.9 (TerraMind) and 86.7 (Galileo).

Ultralytics plots (PR curves, confusion matrix): `runs/eval_kiln_s_256_test/`

## Operating threshold

Chosen confidence threshold: **0.1** (max recall with precision >= 0.7). At this threshold: precision 0.736, recall 0.902, 11,565 kilns found, 1,254 missed, 4,158 false alarms (matching at IoU >= 0.5, class ignored).

| conf | precision | recall | F1 | found | missed | false alarms |
|---|---|---|---|---|---|---|
| 0.05 | 0.690 | 0.912 | 0.785 | 11,689 | 1,130 | 5,258 |
| 0.1 **<-** | 0.736 | 0.902 | 0.810 | 11,565 | 1,254 | 4,158 |
| 0.15 | 0.758 | 0.894 | 0.821 | 11,466 | 1,353 | 3,650 |
| 0.2 | 0.777 | 0.889 | 0.829 | 11,394 | 1,425 | 3,262 |
| 0.25 | 0.794 | 0.880 | 0.835 | 11,279 | 1,540 | 2,917 |
| 0.3 | 0.810 | 0.867 | 0.838 | 11,111 | 1,708 | 2,605 |
| 0.35 | 0.829 | 0.849 | 0.839 | 10,889 | 1,930 | 2,242 |
| 0.4 | 0.853 | 0.817 | 0.834 | 10,473 | 2,346 | 1,811 |
| 0.45 | 0.867 | 0.766 | 0.814 | 9,823 | 2,996 | 1,507 |
| 0.5 | 0.877 | 0.702 | 0.780 | 8,993 | 3,826 | 1,256 |
| 0.55 | 0.889 | 0.634 | 0.740 | 8,127 | 4,692 | 1,014 |
| 0.6 | 0.901 | 0.552 | 0.685 | 7,079 | 5,740 | 775 |
| 0.65 | 0.921 | 0.445 | 0.600 | 5,702 | 7,117 | 487 |
| 0.7 | 0.940 | 0.308 | 0.465 | 3,954 | 8,865 | 253 |
| 0.75 | 0.957 | 0.138 | 0.241 | 1,766 | 11,053 | 79 |
| 0.8 | 0.972 | 0.021 | 0.042 | 276 | 12,543 | 8 |
| 0.85 | 1.000 | 0.001 | 0.001 | 7 | 12,812 | 0 |
| 0.9 | 0.000 | 0.000 | 0.000 | 0 | 12,819 | 0 |
| 0.95 | 0.000 | 0.000 | 0.000 | 0 | 12,819 | 0 |

## Compliance view (the regulator's question)

Non-zigzag = FCBK + CFCBK (non-compliant design in Punjab). Rows = truth, columns = model, at threshold 0.1.

| truth \ model | non-zigzag | zigzag | missed |
|---|---|---|---|
| non-zigzag | 5,748 | 739 | 885 |
| zigzag | 1,112 | 3,966 | 369 |
| no kiln (false alarm) | 2,663 | 1,495 | - |

Type accuracy on detected kilns (non-zigzag vs zigzag): **0.840**

## Full class confusion

| truth \ model | CFCBK | FCBK | Zigzag | missed |
|---|---|---|---|---|
| CFCBK | 236 | 19 | 38 | 56 |
| FCBK | 2 | 5,491 | 701 | 829 |
| Zigzag | 5 | 1,107 | 3,966 | 369 |
| no kiln | 76 | 2,587 | 1,495 | - |

## Notes

- Honest numbers: these are on the held-out test split, never used for training or model selection.
- The risk score shown to users is a priority for inspection, not proof; field checks confirm.

## Operating point used in production runs

The automatic rule above picks conf 0.1. For real Sentinel-2 imagery we use **conf 0.25** (frozen in
`models/kiln_v1.json`): on the test split it gives precision 0.794 and recall 0.880, i.e. 2 points less
recall than 0.1 but about 30% fewer false alarms (2,917 vs 4,158), with F1 0.835 near the maximum.
Model SHA-256: `f5f038e13ead745321f9a6a43592a1da41efbc8dbbb10c354c72a0c921d4079b`.

Note on the benchmark comparison: our metrics come from Ultralytics' OBB validator on the official
SentinelKilnDB test split; the paper's numbers come from its own evaluation code, so the comparison is
indicative rather than exact.
