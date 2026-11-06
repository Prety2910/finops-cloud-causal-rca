# Next steps

Ordered. Each step has a **done-when** so you know when to stop. Week numbers follow
`technical_plan.md` §10 (W1 = week of 13 Oct 2026; W24 ≈ end of March 2027).

## Status (2026-10-13)
- ✅ Steps 1–3 done: Postgres up (**host port 5433**, 5432 was taken by another container), RCAEval cloned, RE1/RE2/RE3 downloaded
  from both the HF mirror and the canonical Zenodo archives, audited, curated copy built, format documented in `data/README.md`,
  audit in `docs/DATA_AUDIT.md`. Call graphs for OB and TT derived from traces.
- ➡️ Next: step 4 (reproduce baselines) and step 5 (loader). **Read DATA_AUDIT §C first**: RCAEval's shipped `main.py` globs
  `data.csv`, which for RE1-SS/TT is the raw 437/1 241-column dump, not the `simple_data.csv` behind the published numbers.

## Critical path (do in this order)

| # | Step | Done when | Wk |
|---|------|-----------|----|
| 1 ✅ | `make setup && make test`; `cp .env.example .env`; `make db` (Docker needed) | tests green, `\dt` in psql shows the tables | 1 |
| 2 ✅ | `bash scripts/setup_rcaeval.sh`; download RE1/RE2/RE3 from the Zenodo links in its README into `data/raw/rcaeval/` | data on disk | 1–2 |
| 3 ✅ | **Inspect format**: `python scripts/inspect_rcaeval.py data/raw/rcaeval`; fill `data/README.md` (layout, column naming, inject-time location, labels, trace format) | `data/README.md` has no blanks | 2 |
| 4 | **Reproduce baselines** (BARO, RCD, CIRCA) with RCAEval's own code on RE2 then RE1/RE3; save to `results/baselines_reproduced/` | AC@1/3/5 within noise of the published tables | 2–3 |
| 5 | Implement `ingest/rcaeval.py` → `Case`; check `service_of()` in `rca/base_baro.py` against real column names | `iter_cases` yields every case; a unit test on 1 real case | 3 |
| 6 | Implement `replayer.py` + wire `detect/detector.py`; one replayed case on a Streamlit chart | **Milestone M-1** | 4 |
| 7 | `ingest/synth_changes.py` over all RCAEval cases (`make synth-changes`) — freeze the generator + seeds before any tuning | change_events saved with seed in metadata | 4–8 |
| 8 | Testbed: minikube + Online Boutique + kube-prometheus-stack + Locust stable; then faults F1–F8 and 10 pilot cases | pilot cases export to RCAEval layout | 5–6 |
| 9 | Full ~120-case campaign (overnight); fill `configs/pricing.yaml` (date, region, source) | **Milestone M-2** | 7–8 |
| 10 | Own BARO scorer reproduces step-4 numbers; then M1, M2, combine (grid search on dev only) | first table + ablations (**M-3**) | 9–12 |
| 11 | M3: SCM + Shapley (validate C5 on testbed), calibration, robustness, LOSO, what-if; **freeze engine + JSON contract** | all RCA figures (**M-4**) | 13–16 |
| 12 | LLM layer, agent, dashboard, LLM eval | end-to-end demo (**M-5**) | 17–20 |
| 13 | Final test-split run once, CIs, significance, paper, report | submission (**M-6**) | 21–24 |

## Do this week
1. Steps 1–3 above (environment + data + format notes).
2. Read BARO, RCD, CIRCA, RCAEval papers (the reading list is in plan §12).
3. Decide questions in "Open decisions" below.

## Open decisions (answer early; they change scope)
- **Laptop/cloud for the testbed**: needs ≥16 GB RAM. This VM has no working GPU, which is fine (nothing here needs one), but check RAM/CPU before step 8.
- **Which RCAEval systems for the headline table**: plan implies all three; Train Ticket is heavy and its call graph must come from traces. Suggest: OB + Sock Shop first, Train Ticket if time allows.
- **LLM budget** for step 12 (T3 calls cost money; cap them).
- **Target venue** (affects page limits and evaluation expectations).

## Discipline rules (protect the paper)
- Tune only on **dev**, fit calibration on **calibration**, touch **test** once at the end.
- Headline AC@k from RCAEval's evaluator; our own metrics code is for ablations and must agree on baselines.
- Every number in the paper must come from a file in `results/` produced by a `make` target.
- Say "simulated cost" and "synthetic change events" wherever they apply.
- Don't write loaders or call-graph YAMLs from memory: verify against real data (the Sock Shop / Online Boutique YAMLs in `configs/systems/` are marked VERIFY; Train Ticket is empty on purpose).
