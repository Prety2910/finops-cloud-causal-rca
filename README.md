# FinOps for Cloud with Causal Root Cause Analysis

Capstone project. Primary foundation: [Eco-FinOps (Sreejindeth and Padmavathy, 2026)](https://doi.org/10.3389/frai.2026.1861514). BARO is retained as a supporting baseline. Full design: [`docs/technical_plan.md`](docs/technical_plan.md).
**What to do next:** [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md). Experiment design: [`docs/BENCHMARK_PROTOCOL.md`](docs/BENCHMARK_PROTOCOL.md).

## Layout

```
configs/            pricing.yaml, rca.yaml, llm.yaml, eval.yaml, systems/*.yaml (static call graphs)
data/               raw/ processed/ change_events/   (git-ignored; formats documented in data/README.md)
db/schema.sql       Postgres/Timescale schema + read-only role
docs/               plan, next steps, benchmark protocol
scripts/            setup_rcaeval.sh, inspect_rcaeval.py
testbed/            Online Boutique on minikube/kind: k8s/, faults/ (F1-F8), run_case.sh, collect.py
src/cloudrca/
  config.py schemas.py          shared config loader + Case/Candidate dataclasses
  ingest/                       rcaeval.py testbed.py cost_model.py synth_changes.py replayer.py
  detect/                       detector.py
  rca/                          base_baro m1_change m2_graph m3_cost shapley calibrate whatif engine
  llm/                          signature incident_graph router explain prompts/
  agent/                        tools.py agent.py
  eval/                         run_rca_eval run_llm_eval robustness metrics stats figures
app/                Streamlit dashboard (Home.py + pages/)
tests/              pytest
results/            outputs of `make` targets (git-ignored)
```

## Status

| Area | State |
|---|---|
| Metrics, bootstrap/McNemar, calibration (ECE/Brier/temperature), exact Shapley | implemented + tested |
| Cost model, seasonal Ridge expected-cost baseline, persistent cost-spike detector, three policy-level cost alerts (`detect/idle_resource.py`, `detect/optimization.py`), RCAEval curated-data loader, ITS/HAC (M1), BARO-style scorer, PageRank walk, SCM + attribution, signature similarity, tier-choice rule | implemented + tested where marked in `tests/`; cloud adapters/evaluation remain pending |
| RCAEval data: downloaded, audited, curated, documented (`docs/DATA_AUDIT.md`) | **done** |
| Replayer, PC/Granger discovery, engine M2/M3 wiring, LLM router/explain, agent, dashboard, testbed | **stubs or partial** (see `IMPLEMENTATION_GAP_ANALYSIS.md`) |

Run the deterministic synthetic presentation walkthrough with
`./.venv/bin/python scripts/run_policy_demo.py`. The resulting report is saved
to `results/demo/policy_demo.json`; all values are fixtures, not real bills or
measured savings. The demo contains no AWS calls or CloudTrail observations;
its cost and utilization inputs are synthetic. See [the demo guide](docs/DEMO_GUIDE.md).

Build an offline, self-contained HTML dashboard from that report with
`./.venv/bin/python scripts/build_demo_dashboard.py`, then open
`results/demo/index.html` in a browser. This works without Streamlit.
The separate `Synthetic demo artifacts` GitHub Actions workflow generates both
files on Ubuntu and uploads them as a downloadable workflow artifact.

To view the report in the existing Streamlit interface, install the optional
app dependencies (`pip install -e '.[app]'`) and run
`streamlit run app/Home.py`. Streamlit is optional and was not installed in the
current validation environment, so the UI has not received a browser smoke test.

## Quick start

```bash
make setup          # pip install -e ".[dev,db]"  (a .venv already exists in this folder)
make test
make db             # needs Docker; Postgres on host port 5433
bash scripts/setup_rcaeval.sh
make data           # download + audit + build curated RCAEval copy (see docs/DATA_AUDIT.md)
```

Run `make` targets only after the corresponding loader exists; each stub says what's missing.
