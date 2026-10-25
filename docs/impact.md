# Climate impact method

Brick kilns are a major source of black carbon, PM2.5 and CO2 across the Indo-Gangetic Plain.
Punjab requires every kiln to use zigzag firing and orders shutdowns during smog episodes, but
enforcement depends on slow, contested ground inspection. KilnTrace's impact comes from making that
enforcement faster, better targeted and harder to dispute. We report only what we can measure or
derive transparently; headline numbers we cannot defend are left out.

## 1. Direct, measured outputs (Kasur District, one run)

| Output | How it is measured | Value |
|---|---|---|
| Kilns located from free imagery | Detections in the district from Sentinel-2 (Feb-Mar 2026) | 730 |
| Known kilns re-found | Share of 2023-24 hand-labelled kilns with a detection within 150 m | 80% of 687 |
| Non-zigzag kilns flagged for inspection | Tracked kilns in state NON_ZIGZAG | 387 |
| Possible conversions to zigzag | Baseline non-zigzag kiln now classified zigzag | 86 candidates, need field check |
| Possibly closed kilns | Baseline kiln not detected on a cloud-free mosaic | 159 candidates, need field check |
| Tamper-evident records | Records whose hash is anchored on-chain (batch #1) | 889 of 889 (100%) |
| Model precision for flagged kilns | Test split, conf 0.25, class-agnostic | 0.794 (recall 0.880) |

District-wide coverage costs nothing per run in imagery (Sentinel-2 is free) and minutes of GPU time.

## 2. Enforcement efficiency (non-speculative benefit)

Punjab inspectors carried out 45,736 kiln inspections between 1 January and 25 July 2026
(Express Tribune, 4 Aug 2026). If inspections are directed by KilnTrace's risk ranking instead of
being spread evenly, the **hit rate** (share of visits that find a non-compliant kiln) rises from the
base rate to the model's precision at the chosen threshold:

```
hit_rate_random  = share of non-zigzag kilns in the district
hit_rate_ranked  = precision of "non-zigzag" among flagged kilns (from ml/results.md, compliance view)
extra_findings   = inspections x (hit_rate_ranked - hit_rate_random)
```

Every extra finding is a non-compliant kiln reached sooner with the same inspection budget. Field
checks submitted through KilnTrace measure the real hit rate over time.

## 3. Avoided emissions (formula, conservative range)

For each kiln **verified** (by field check) to have converted from FCBK to zigzag:

```
avoided_tCO2e   = annual_bricks x (EF_FCBK - EF_zigzag)            [same form for PM2.5 and black carbon]
total_avoided   = sum over verified conversions
```

`annual_bricks`, `EF_FCBK` and `EF_zigzag` must come from published field measurements of South Asian
kilns (e.g. ICIMOD, World Bank, peer-reviewed kiln emission studies) and be reported as low / central /
high cases with citations. Only field-verified conversions count; model-only "possible conversions"
are excluded so the estimate cannot be inflated by classification errors.

## 4. Fairness and adoption

- Owners who have converted get public, tamper-proof evidence of it, which addresses the owners'
  association's concern about wrongful sealing and demolition (Express Tribune, 4 Aug 2026).
- The same verified record can support results-based finance for zigzag retrofits: a funder can pay
  per verified conversion and check each one independently on-chain.

## 5. Scaling

The method needs only free Sentinel-2 imagery and a commodity GPU. Punjab's roughly 10,000 kilns
(EPA Punjab / Urban Unit survey) fit in a few runs; the SentinelKilnDB coverage area (about
2.8 million km2, 62,671 kilns) shows the approach transfers across the brick kiln belt.

## Limits

- Kiln type from 10 m imagery is the hardest part; it is presented as a candidate needing confirmation.
- Detecting whether a kiln is **firing** (smog-ban violations) needs thermal data and is roadmap work.
- Emission factors vary widely between kilns and operators; ranges, not single numbers, should be reported.
