  # Project Implementation Plan

**Title:** FinOps for Cloud with Causal Root Cause Analysis  
**Primary foundation:** Eco-FinOps (2026). BARO remains a supporting baseline.

## Existing architecture

- **Core:** Python package `src/cloudrca`, configured by `configs/*.yaml`.
- **Data:** curated RCAEval manifest and cases under `data/processed/rcaeval`; raw and processed data are documented in `data/README.md` and `docs/DATA_AUDIT.md`.
- **Cost:** simulated usage pricing in `src/cloudrca/ingest/cost_model.py`; catalog values in `configs/pricing.yaml` are intentionally unset.
- **Detection/RCA:** generic robust-z detector; BARO-style scoring; ITS/HAC event scoring; constrained graph utilities; linear SCM/Shapley and calibration utilities. `src/cloudrca/rca/engine.py` composes BARO/M1 but leaves M2 and M3 as TODOs.
- **UI and operations:** Streamlit scaffold (`app/Home.py`), SQL schema (`db/schema.sql`), testbed documentation and collection stubs.
- **Evaluation:** utilities and RCAEval baseline logs under `results/baselines_reproduced`; no complete proposed-method evaluation table was identified.
- **VCS limitation:** `git status --short` fails with “not a git repository” despite a `.git` directory. Preserve files and do not rely on status/history until this is resolved.

## File-level implementation order

1. **Cost spike analysis (implemented):** `src/cloudrca/detect/cost_spike.py:analyze_cost_series` runs the past-only Eco-FinOps-inspired seasonal Ridge baseline from `cost_baseline.py` and threshold/persistence detector together. It records evidence, excess and modeled/observed provenance. No pricing defaults are introduced. Backtesting and billing adapters remain subsequent work.
2. **RCAEval loader (implemented):** `src/cloudrca/ingest/rcaeval.py` reads the audited manifest and parquet schema; a fixture test and a real curated-case load pass.
3. **Alert policies:** A1 suspected idle compute in `src/cloudrca/detect/idle_resource.py` reads thresholds from `configs/alerts.yaml` and includes seasonal residual MAD and negative CUSUM; add causal workload verification. A2 rightsizing and A3 unnecessary scaling now have policy functions in `src/cloudrca/detect/optimization.py`; connect provider/testbed adapters and validate thresholds. Keep price, workload, criticality, schedule, dependency and SLO requirements explicit; refuse unsupported savings calculations.
4. **Cost attribution:** `src/cloudrca/rca/m3_cost.py` now validates DAG/data/candidate inputs and labels Shapley allocations as model estimates with explicit identification assumptions; a seeded structural-effect fixture checks expected direction and magnitude. Wire it through the engine only when graph and cost columns meet documented assumptions, then add confounder controls and an event-aware cost breakdown.
5. **Action safety and fleet:** fleet ranking is implemented in `src/cloudrca/detect/fleet.py` with declared-overlap suppression. `src/cloudrca/actions/workflow.py` records durable approval, idempotency, audit, dry-run and simulated verification; connect provider adapters and genuine post-action SLO/cost verification only with explicit authorization and required permissions. Benchmark fleet processing at 100/1k/10k synthetic resources.
6. **Eco-FinOps baseline and BARO comparison:** inspect the primary paper and data fit; implement the justified seasonal baseline/anomaly components and report reproduction limits. Keep BARO outputs intact.
7. **Integrations:** complete graph discovery/replayer; then connect LLM memory, agent and the current Streamlit app to structured records.
8. **Evaluation and documentation:** run tests and controlled scenarios, save all outputs and document measured results only.

Presentation walkthrough: `scripts/run_policy_demo.py` composes the cost-spike detector, A1/A2/A3 policies and fleet overlap ranking using a fixed-seed synthetic fixture. Its scope and caveats are documented in `docs/DEMO_GUIDE.md`; it is not an experimental result.

## Risks and mitigations

- Null pricing is deliberate; keep costs unavailable until explicit prices are supplied and labeled with region/source/date.
- RCAEval has no real cloud bills; costs derived from it are simulated proxies, not billing facts.
- Correlated or temporally adjacent events are candidate causes; causal effects need identification assumptions or controlled interventions.
- Rightsizing and scaling savings overlap; fleet totals must account for shared billable capacity.
- Do not introduce live provider writes before approval, audit, rollback/verification and permissions are in place.
- No integrated empirical results should be inferred from baseline logs alone.

## Validation strategy

- Run existing pytest suite before/after each code change using the repository virtual environment.
- Test cost arithmetic with explicit price fixtures and no configured prices; test zero expected cost, short persistence, isolated excursions and sustained spikes.
- Test each alert with positive and negative controls, including quiet schedules, rising traffic, absent billing units and SLO guard failures.
- Use synthetic, seeded injections for attribution and scalability; label them synthetic.
- Use curated RCAEval only for service-level RCA unless verified fields support stronger claims.
- Record commands and actual pass/fail output in `IMPLEMENTATION_PROGRESS.md`.
