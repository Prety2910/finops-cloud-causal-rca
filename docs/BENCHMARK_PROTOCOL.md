# Benchmark protocol

Operationalises plan §1 (claims) and §5 (evaluation). Everything runs from `configs/eval.yaml`.

## Claims → experiments → outputs

| Claim | Command | Output (under `results/<run>/`) | Primary metric |
|---|---|---|---|
| C1 main table | `make benchmark` | `main_table.csv`, `per_case.csv` | AC@1/3/5, Avg@5 + 95% CI, paired test vs best baseline |
| C2 ablations | `make ablate` | `ablation.csv` | AC@1 per variant (base, +M1, +M2, +M1+M2, full, Granger, no-topology) |
| C3 decoy robustness | `make robustness` | `robustness.csv` | AC@1 vs λ_decoy, p_miss, jitter; no-change-fault cases separately |
| C4 calibration | in `make benchmark` | `calibration.csv`, reliability plot | ECE (15 bins), Brier, selective-accuracy curve |
| C5 cost attribution | in `make ablate` (testbed) | `cost_attribution.csv` | % cases where true cause has largest Shapley φ; unexplained ₹ |
| C6 LLM savings | `make llm-eval` | `llm_stream.csv` | tokens/₹/p50-p95 latency per incident, tier hit-rate, correctness |
| Efficiency | in `make benchmark` | `runtime.csv` | sec/case, #CI tests with/without constraint |
| Generalisation | `make benchmark` (LOSO flag) | `loso.csv` | AC@1 leave-one-system-out |

## Rules
1. **Splits** per system: 60/20/20 dev/calibration/test, stratified by fault type, seed in config.
2. **Settings reported both ways** for anomaly time: labelled injection time and detector-triggered.
3. **Baselines** run through RCAEval's code; record commit hash of RCAEval in every `summary.json`.
4. **Per-case log** (`per_case.csv`) is the source of truth: method, case, truth, ranking, seconds, seed, config hash.
5. **Stats**: 1000× bootstrap 95% CI; paired bootstrap and exact McNemar for full vs best baseline.
6. **Change-event synthetic sweeps**: λ_decoy ∈ {0,1,2,4}, p_miss ∈ {0,0.2,0.5}, jitter ∈ {0,60,300}s; one seed per setting, published.
7. **Cost**: label as simulated; sensitivity analysis (±50% prices) reports top-cause stability rate.
8. **No tuning on test.** Final test run happens once, after the engine is frozen (W16).

## Reproduction record (keep per run)
`git rev-parse HEAD`, RCAEval commit, `pip freeze`, config hashes, wall-clock, machine spec.
