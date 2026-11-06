# RCAEval data audit (2026-10-13)

Goal: confirm that the data we will benchmark on is complete and correct, and record every deviation.

## What was checked
1. **Completeness**: 735 cases = 375 RE1 + 270 RE2 + 90 RE3; per-dataset counts match the published table; every directory has the files the
   index says it should (`scripts/verify_rcaeval.py`).
2. **Internal consistency (all 735)**: case name ↔ index fields; `inject_time.txt` ↔ index; row/column counts ↔ index; time
   range; injection inside the series; strictly increasing 1 Hz time; no ±inf; root-cause service has a metric column;
   log/trace row counts ↔ index.
3. **Provenance**: Zenodo archives md5-verified (all 9) against Zenodo's published checksums, extracted, and
   compared with the Hugging Face mirror for every case (`scripts/compare_hf_zenodo.py`): inject time, metric names+times+values
   (`allclose`), log/trace presence and row counts.

## Result
- Mirror vs canonical: **711 / 735 identical**; the 24 differences were each traced to a cause (below).
- Curated copy (`data/processed/rcaeval`): **735 / 735 pass** all structural checks, 4 cases carry a data-quality warning.
- Zenodo is the source for RCAEval's own scripts (RE1-OB `data.csv`, RE1-SS/TT `simple_data.csv`, RE2/RE3 `simple_metrics.csv`); the mirror values equal those files.

## Findings

### A. Defects in the mirror (fixed in the curated copy from Zenodo)
| Case | Defect | Fix |
|---|---|---|
| `re1ob_currencyservice_loss_1` | `inject_time.txt` = `16933142` (8 digits, truncated; lies before the series start) | `1693314223` from Zenodo |
| `re1ob_productcatalogservice_cpu_3` | metrics truncated to 63 of 4 201 rows; injection after series end | full 4 201 rows from Zenodo |
| `re2tt_ts-auth-service_cpu_1` | no logs (index `has_logs=False`) although Zenodo has a 279 630-line `logs.csv` | converted from Zenodo (ns→s timestamps) |

### B. Defects in the canonical Zenodo data that the mirror already cleaned (curated copy keeps the mirror's version)
Eight cases have extra rows with a NaN `time` in Zenodo's CSV (7–262 rows); the mirror drops them (or, for the two 70-minute RE1-OB cpu cases, re-times the trailing ones) and all remaining values are identical (checked):
`re1ob_adservice_cpu_5, re1ob_checkoutservice_cpu_4, re1ob_productcatalogservice_cpu_4, re1ss_catalogue_disk_3, re1ss_user_mem_1,
re1tt_ts-order-service_mem_3, re2ob_checkoutservice_cpu_2, re2ob_checkoutservice_mem_2`. Row counts differ from Zenodo by that amount, so do not
mix the two sources inside one experiment.

### C. Benign differences
- RE1-OB `data.csv` has a duplicate `time.1` column; mirror drops it.
- RE1-SS/TT `data.csv` is the *raw* Prometheus dump (437 / 1 241 columns); the published 57–63 / 198–238 metric counts correspond to `simple_data.csv`, which the mirror matches. **When you run RCAEval's `main.py` on the Zenodo layout, check which file it globs** (`data.csv` first in the shipped `main.py`) before trusting reproduced numbers.
- 13 RE3-SS cases have a header-only (116-byte, checked for all 13) `traces.csv` in Zenodo; the mirror has none (Sock Shop is not traced).
- RE3-TT `ts-route-service_f3` repetitions 4–6 live under `ts-route-service_f3_1/{1,2,3}` in Zenodo; the mirror renamed them `_4…_6`. Zenodo's RE2-OB also contains a stray `checkoutservice_cpu/multi-source-data` dir and `.DS_Store` files; ignored.

### D. Data-quality properties (not fixed; handle in the loader)
- 4 cases with mostly-NaN columns from the other system (see `data/README.md`): drop foreign-service columns.
- Partly-NaN metric columns are normal (latency/error with no traffic): `ffill` then `fillna(0)` like RCAEval.
- `frontendservice` vs `frontend` naming in RE2-OB traces.
- RE1-OB has two metric vocabularies (`load`/`latency` vs `workload`/`latency-50/90`), split by fault type.
- Metric series length varies (RE1-OB cpu/mem are 70 min, others 12 min): windowing must be relative to `inject_time`, not absolute row counts.
- No root-cause *indicator* labels in the mirror or index.

## Not checked (be honest about the limits)
- Metric *semantics/units* (no unit metadata in the files).
- Log and trace **content** equality between mirror and Zenodo (only presence and row counts were compared; the timestamp unit differs by design).
- That injected faults are visibly present in the metrics (a sanity check we should do when we implement BARO: per-fault-type z-score of the root-cause service).
- TORAI datasets (not part of RE1–3, not downloaded).

## Reproduce
```
python -I scripts/download_rcaeval.py              # HF mirror        -> data/raw/rcaeval
python -I scripts/download_zenodo.py               # canonical (39 GB) -> data/raw/zenodo
python -I scripts/verify_rcaeval.py data/raw/rcaeval
python -I scripts/compare_hf_zenodo.py
python -I scripts/build_rcaeval_processed.py
python -I scripts/verify_rcaeval.py data/processed/rcaeval
python -I scripts/derive_call_graph.py
```
Pinned: Zenodo record 14590730; RCAEval repo commit `259ea4167160256a74ad30004aa3d96a998c846e`.
