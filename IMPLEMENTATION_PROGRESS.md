# Implementation Progress

## Session 1 — 2026-10-26

### Audit completed

- Reviewed the root README, project plan, next steps, benchmark protocol, data README/audit, package/dependency configuration, core source modules, configuration, SQL schema, Streamlit entry point, testbed scaffold, tests, and sampled RCAEval baseline outputs.
- Reviewed the primary Eco-FinOps paper. Its zombie detector uses hour/day/trend seasonal Ridge, robust MAD residual scaling, a 24-hour idle ratio and negative-shift CUSUM, followed by PC/DoWhy causal filtering. Its reported 0.89 precision is based on injected zombie labels over Alibaba Cluster Trace and is not comparable to this project's RCAEval results without reproducing the task/data protocol. The technical plan now identifies Eco-FinOps as primary and BARO as supporting.
- Confirmed existing utility work and data must be preserved. Important incomplete seams include RCAEval ingestion, graph discovery, M2/M3 engine wiring, action workflow, fleet analysis, and dashboard integration.
- `git status --short` failed: the workspace's `.git` directory is not recognized as a repository. No assumptions about clean/dirty status are made.

### Files changed

- Added `IMPLEMENTATION_GAP_ANALYSIS.md`.
- Added `PROJECT_IMPLEMENTATION_PLAN.md`.
- Added this progress record.
- Added `src/cloudrca/detect/cost_spike.py` and tests in `tests/test_core.py`.
- Replaced the RCAEval loader stub in `src/cloudrca/ingest/rcaeval.py` and added a fixture test in `tests/test_core.py`.
- Updated `README.md` and `docs/technical_plan.md` to use the fixed project title and Eco-FinOps primary/BARO supporting decision.
- Updated `IMPLEMENTATION_GAP_ANALYSIS.md` with paper-specific reproduction limitations.

### Tests

- `./.venv/bin/python -m pytest -q`: **15 passed**.
- A loader unit test first failed because other-system service names were only loaded from the selected manifest subset. The loader was corrected to inspect all configured systems; the suite then passed.
- `./.venv/bin/python -c "from cloudrca.ingest.rcaeval import iter_cases; c=next(iter_cases(dataset='RE1-OB')); ..."`: successfully loaded `re1ob_adservice_cpu_1`, yielding 4,201 rows × 49 columns, injection time `1685202688`, and `root_cause_indicator=None`.

### Implemented

- Added a persistent threshold detector for supplied actual/expected cost bucket series. It validates aligned time indexes, requires configurable absolute and percentage deviation plus persistence, handles zero expected cost with an absolute-only gate, splits intervals at missing data, reports excess cost and provenance, and explicitly avoids causal/probability claims.
- Implemented the curated RCAEval loader. It reads the manifest, metrics, injection timestamp and optional logs/traces; removes columns positively identified as foreign-system telemetry; applies the documented upstream missing-value handling; maps system names; and retains the absent indicator label as `None`. Its CLI exports normalized case folders.

### Remaining work

- Add expected-cost forecasting (seasonal/reference model) and billing adapters; current spike detection requires callers to supply expected and actual costs in the same units.
- Implement the three primary cost alert types, causal attribution integration, safe action lifecycle, and fleet ranking.
- Eco-FinOps-specific reproduction and full evaluation remain pending; existing baseline artifacts alone do not validate the proposed system.

## Session 2 — 2026-11-03

### Implemented

- Added `src/cloudrca/detect/cost_baseline.py:seasonal_ridge_expected`, a time-of-day/day-of-week/trend Ridge baseline. It fits finite historical buckets strictly before a caller-supplied cutoff and returns predictions only at/after that cutoff. It rejects irregular timestamp intervals and insufficient training history; output is an estimate, not observed cloud cost.
- Added `analyze_cost_series` in `src/cloudrca/detect/cost_spike.py` to connect the baseline to persistent cost-spike detection as one callable pipeline.
- Added tests for post-cutoff leakage resistance, expected seasonal levels, short training history and irregular buckets.
- Updated the gap analysis and implementation plan to reflect expected-cost modeling as implemented while keeping pricing/billing validation open.

### Validation

- The initial test run found a NumPy/Pandas boolean-mask API mismatch; corrected it to use `np.asarray`.
- `./.venv/bin/python -m pytest -q`: **19 passed** after the correction, cadence validation and end-to-end modeled cost-spike test.

### Remaining issues

- No forecasting backtest has been run on provider billing history; the project has no verified bill series and configured sample prices remain null.
- Eco-FinOps causal verification, three cost alert categories, attribution/action workflow, fleet prioritization, and full application integration remain incomplete.

## Session 3 — 2026-11-05

### Implemented

- Generalized seasonal Ridge forecasting so the same past-only model can forecast cost or utilization series. Cost analysis continues to use the cost-specific wrapper.
- Added `src/cloudrca/detect/idle_resource.py:assess_idle_resource` as the initial A1 policy. A candidate requires billable active state, sustained CPU below the configured floor, memory telemetry, and at least one quiet workload signal (requests or network). When enough history exists, it also requires a material drop below a seasonal CPU baseline, robust MAD-scaled residuals, and either a negative standardized residual shift or negative CUSUM threshold crossing; otherwise it marks use of the documented rule fallback.
- The A1 result reports evidence, uncalibrated confidence status, a modeled upper bound for spend during observed idle buckets when a valid hourly compute rate is supplied, stop safety checks, approval requirement, dry-run mode, rollback triggers, and post-action verification conditions. It does not execute actions.
- Added `configs/alerts.yaml` for A1 policy thresholds and a configuration loader. Results explicitly mark causal verification as not run and retain unknown confidence.
- Added tests for the positive candidate path, active-workload negative control, unresolved safety checks, and rejection of CPU-only evidence.

### Validation

- The first A1 test exposed that this pandas installation uses microsecond-resolution datetime integers. Replaced unit assumptions with `Timedelta` duration arithmetic in the forecast trend and cost-impact calculation.
- `./.venv/bin/python -m pytest -q`: **23 passed**.

### Remaining issues

- A1 still lacks PC/DoWhy causal workload verification, provider inventory/event adapters, and validated thresholds.
- A2 rightsizing and A3 unnecessary scaling are unimplemented.
- No action execution, fleet ranking, post-action observation, or measured savings pipeline exists yet.

## Session 4 — 2026-11-05

### Implemented

- Added policy-level A2 and A3 recommenders in `src/cloudrca/detect/optimization.py`, with thresholds in `configs/alerts.yaml`.
- A2 uses seven-day P99 CPU/memory demand, explicit same-currency instance-hour pricing, compatible family/region/architecture/credit model filtering, SLO gates, and gross/first-month net savings arithmetic.
- A3 compares P99 request demand with a versioned per-replica capacity result and headroom. It requires HPA configuration, collected scaling events, CPU/memory requests and limits, and passing SLOs. Cost savings remain absent unless billable capacity release is confirmed and a marginal rate is supplied.
- Both policy results require approval, are dry-run recommendations, include rollback/verification steps, and mark confidence uncalibrated. Added `docs/ALERT_POLICIES.md` for presentation and method explanation.

### Validation

- Added positive and negative fixture coverage for A2/A3, including SLO failure, incompatible SKU filtering, missing capacity validation and shared-capacity no-savings behavior.
- `./.venv/bin/python -m pytest -q`: **26 passed**.

### Remaining issues

- The alert functions are not connected to real cloud inventory, price catalogs, Kubernetes HPA data or action adapters.
- No testbed scaling/rightsizing execution or post-action SLO/billing verification has been measured.
- Fleet overlap handling, durable action audit/approval, UI integration, and Eco-FinOps causal verification remain outstanding.

## Session 5 — 2026-11-05

### Implemented

- Added `src/cloudrca/detect/fleet.py:rank_fleet_opportunities` for transparent priority ordering and overlap-aware monthly savings totals.
- The function excludes unestimated/non-positive opportunities, requires a shared currency, uses a default same-resource overlap key, supports explicit cross-resource overlap groups, and labels evidence/risk weighting as an uncalibrated heuristic.
- Ranking requires explicit evidence and operational-risk scores; it does not silently assume confidence or zero risk.
- Added a fixture test showing that two recommendations sharing one capacity group contribute only the larger estimate to totals.
- Updated `docs/ALERT_POLICIES.md`, gap analysis, and project plan with the fleet policy and its validation limits.

### Validation

- `./.venv/bin/python -m pytest -q`: **27 passed**.

### Remaining issues

- Cross-resource overlap groups must be supplied by an inventory/billing integration; the function does not infer them.
- Fleet-scale throughput benchmarks and durable action approval/audit/verification remain to be implemented.

## Session 6 — 2026-11-05

### Implemented

- Added `src/cloudrca/actions/workflow.py:ActionWorkflow`, a SQLite-backed action record and audit trail.
- Plans use idempotency keys; altered reuse is rejected. Only allowlisted approvers can approve/reject. Unapproved dry-run is blocked. The dry-run is local only and records no execution or side effects. Simulation checks can pass or fail and are labeled as simulated verification, never live verification.
- Credential-like fields are rejected from action payload storage. No cloud provider adapter or write path was added.
- Added tests for state transitions, approval, idempotency, secret-field rejection and simulation-only verification.

### Validation

- `./.venv/bin/python -m pytest -q`: **29 passed**.

### Remaining issues

- The action ledger is not connected to dashboard recommendations or provider adapters.
- Real permission checks, action execution, live rollback and post-change cost/SLO verification remain outstanding.

## Session 7 — 2026-11-05

### Implemented

- Hardened `src/cloudrca/rca/m3_cost.py`: rejects cyclic graphs, incomplete/non-numeric fitting data, invalid interventions, and invalid attribution inputs.
- Attribution output now distinguishes observed pre/post cost delta from the structural model's Shapley allocation, labels estimates as `model_estimate`, and records the value function and identification assumptions. It explicitly says model fit alone does not establish causal identification.
- Added seeded controlled structural-effect tests and negative tests for cyclic DAGs and invalid causes. The fixture uses Ridge regularization, so the test allows a small estimate error rather than asserting an exact recovered effect.
- Confirmed `ActionWorkflow.record_simulated_rollback` is present; its terminal record says live resources were not changed.

### Validation

- First run: **1 failed, 30 passed**. The seeded estimate was 6.16 against constructed effect 6.0 due to regularized model fitting; updated the assertion tolerance to 0.25 while retaining a narrow effect check.
- `./.venv/bin/python -m pytest -q`: **31 passed** after correcting the fixture tolerance.

### Remaining issues

- Attribution still depends on a user-specified DAG and does not establish no-confounding or transportability. It is not yet wired into the RCA engine or connected to observed cloud bills/events.
- Live provider execution/verification, dashboard integration, testbed measurements, and scalability evaluation remain incomplete.

## Session 8 — 2026-11-05

### Implemented

- Added `resource_cost_breakdown` to `src/cloudrca/ingest/cost_model.py`. It groups modeled component costs by explicit resource dimensions, rejects missing dimensions and invalid totals, and reconciles grouped totals to row-level totals. Output is labeled simulated and carries billing-basis provenance.
- Added tests for component arithmetic, resource grouping, reconciliation, missing dimensions, and unsupported component sets.
- Updated the gap analysis to account for implemented cost reconciliation and the actual unit test coverage.

### Validation

- `./.venv/bin/python -m pytest -q`: **33 passed**.

### Remaining issues

- Grouped modeled cost is not a real invoice reconciliation; pricing configuration remains unset.
- There is no end-to-end cost-spike → cause → action → verification orchestrator or UI, and causal attribution is not identified without experiment assumptions.
- No external dataset download or live testbed experiment was started in this session; RCAEval does not supply cloud billing ground truth.

## Session 9 — 2026-11-05

### Implemented

- Added `scripts/run_policy_demo.py`, a fixed-seed synthetic walkthrough that composes seasonal cost-spike detection, idle-resource assessment, rightsizing, scaling, and fleet ranking. It writes a structured JSON report and labels all evidence and prices synthetic.
- Added `docs/DEMO_GUIDE.md` with a presentation sequence, methodology explanation and explicit limitations; linked it from the README and implementation plan.
- Added repeatability and output-contract test for the demo.

### Validation

- `./.venv/bin/python scripts/run_policy_demo.py`: completed; 1 synthetic cost spike and positive synthetic candidates for A1/A2/A3; the demonstration fleet estimate is USD 1,022/month under fixture inputs only.
- `./.venv/bin/python -m pytest -q`: **34 passed**.

### Remaining issues

- Demo output is deliberately synthetic and must not be presented as system accuracy or realized savings.
- Dashboard remains a scaffold; causal RCA engine integration, empirical testbed runs, provider prices/bills, and fleet scalability measurements remain to be completed.

## Session 10 — 2026-11-05

### Implemented

- Replaced the Streamlit placeholder in `app/Home.py` with a data-backed view of the deterministic policy-demo report: cost-spike summary, A1/A2/A3 cards, fleet ranking, evidence/safety details, and explicit research limitations.
- The view rejects reports without `synthetic_demo_only` provenance and never offers cloud action controls.
- Updated the gap analysis, README and demo guide with installation and launch instructions.

### Validation

- `./.venv/bin/python -m py_compile app/Home.py scripts/run_policy_demo.py`: passed.
- `./.venv/bin/python -m pytest -q`: **34 passed**.
- Streamlit is absent from `.venv` because it is an optional app dependency; dashboard browser smoke test not run.

### Remaining issues

- Dashboard currently consumes only the synthetic demo report; live/API-backed analysis and incident memory remain unintegrated.
- Streamlit rendering, M2 causal discovery/engine integration, M3 orchestration, empirical experiments, and provider-backed post-action verification remain open.

## Session 11 — 2026-11-05

### Implemented

- Extended the synthetic walkthrough with a controlled SCM cost-attribution fixture in which injected excess replicas cause modeled compute cost.
- Kept that fixture explicitly separate from the cost-spike series; it demonstrates a counterfactual method but does not claim to explain the detected spike.
- Added a dashboard panel for observed synthetic cost delta, model-attributed amount, residual, value function and identification assumptions.
- Updated the demo guide and added a seeded-effect assertion.

### Validation

- `./.venv/bin/python scripts/run_policy_demo.py`: passed; rewrote the deterministic JSON report with the controlled attribution example.
- `./.venv/bin/python -m py_compile app/Home.py scripts/run_policy_demo.py`: passed.
- `./.venv/bin/python -m pytest -q`: **34 passed**.

### Remaining issues

- SCM example is controlled synthetic data; this is not a real billing experiment or engine integration.
- UI remains unrendered due to missing optional Streamlit dependency; causal assumptions and remaining evaluation gaps are unchanged.

## Session 12 — 2026-11-06

### Implemented

- Added `src/cloudrca/demo_dashboard.py` and `scripts/build_demo_dashboard.py` to create a self-contained HTML presentation dashboard from the labeled synthetic JSON report. It shows cost spikes, alert evidence/safety, the separate SCM example, and fleet ranking. It rejects reports without synthetic provenance.
- Kept the Streamlit dashboard intact; the static HTML path is an additional option when the optional Streamlit package is unavailable.
- Updated README and demo guide with the no-install browser workflow.

### Validation

- `./.venv/bin/python scripts/build_demo_dashboard.py`: passed; generated `results/demo/index.html`.
- `./.venv/bin/python -m py_compile src/cloudrca/demo_dashboard.py scripts/build_demo_dashboard.py`: passed.
- Initial pytest run: **1 failed, 34 passed** because the assertion expected a different section heading. Corrected the assertion to the actual title.
- `./.venv/bin/python -m pytest -q`: **35 passed**.

### Environment resource snapshot

- Project workspace: approximately 44 GB total; `data/` is 42 GB, `.venv/` is 648 MB, `results/` is 22 MB, and remaining source/config/artifacts are about 1.3 GB.
- Dataset breakdown: `data/raw/zenodo` 39 GB, `data/raw/rcaeval` 3.3 GB, curated `data/processed` 25 MB.
- VM-visible filesystem: 2.0 TB total, 1.9 TB used, 179 GB available (92% used at snapshot time). VM reports 24 logical CPUs and 216 GiB RAM, with 188 GiB available.
- GPU status cannot be read: `nvidia-smi` cannot communicate with an NVIDIA driver, `/dev/nvidia*` is absent, and PyTorch/TensorFlow are not installed in this environment. Do not report GPU memory/utilization as zero; the GPU is not exposed to this session.
