# Technical Plan: FinOps for Cloud with Causal Root Cause Analysis

Working document. Everything needed to start building. Names in `code` are suggestions.

**Primary research foundation:** Eco-FinOps (Sreejindeth and Padmavathy, 2026), https://doi.org/10.3389/frai.2026.1861514. BARO is a supporting RCA baseline, not the primary foundation. The current implementation and evaluation protocol originated as a BARO-oriented plan and are not a reproduction of Eco-FinOps. The revised work must first reproduce the paper's relevant idle-resource task (seasonal CPU baseline, robust residual/MAD handling, negative-shift CUSUM, then causal verification) on compatible data before claiming a baseline comparison. Eco-FinOps reports 0.89 precision on its Alibaba Cluster Trace evaluation; that published result is not a result of this project and is not directly comparable to RCAEval or a different fault-injection protocol.

The paper's reported zombie labels were produced by controlled synthetic injection because its Alibaba trace has no native zombie ground truth. It describes seasonal hour/day/trend features, a 24-hour idle ratio, MAD-scaled residuals and negative CUSUM, followed by PC/DoWhy filtering against temporal workload context. Our current local RCAEval data has service fault labels and no cloud billing ground truth; it cannot by itself reproduce the paper's machine-level FinOps benchmark. See `IMPLEMENTATION_GAP_ANALYSIS.md` for current gaps and `IMPLEMENTATION_PROGRESS.md` for changes and validation.

---

## 0. One-paragraph summary

We implement an Eco-FinOps-aligned idle-resource baseline, retain BARO as a supporting metric-RCA baseline, and evaluate three capstone extensions:

- **M1. Change-event anchoring.** Deployments and config changes become candidate causes, scored by their measured before/after effect and how close they were in time.
- **M2. Topology-constrained causal graph.** Causal discovery limited to service call-graph edges, then a random walk to rank causes.
- **M3. Cost attribution and calibrated confidence.** Counterfactual and Shapley attribution of a simulated cost spike, plus calibrated confidence scores.

On top of this sits an **incident knowledge graph** that lets an LLM reuse past explanations. This tiered routing cuts tokens, money and latency. Everything is evaluated on **RCAEval** (RE1/RE2/RE3) and on **our own deployment-fault dataset** from an Online Boutique testbed. A Streamlit dashboard shows metrics, logs, cost, the causal graph and RCA results, and includes a chat **agent** with tool access to all results.

---

## 1. Claims we will test (keep the paper honest)

| ID | Claim | Measured by |
|---|---|---|
| C1 | M1+M2+M3 improves AC@1/AC@3 over BARO, RCD, CIRCA | RCAEval RE2/RE3 + our dataset |
| C2 | Each module helps independently | Ablation table |
| C3 | M1 stays robust when unrelated (decoy) changes happen | Accuracy vs. #decoys / missing-event rate |
| C4 | Calibrated confidence matches empirical accuracy | ECE, reliability diagram |
| C5 | Cost attribution identifies the cause responsible for most of ΔCost | Attribution accuracy on testbed (ground-truth cause known) |
| C6 | Incident-graph memory reduces LLM tokens, cost and latency with no loss in correctness | Tokens/incident, ₹/incident, p50/p95 latency, correctness |

No numbers are promised in advance. Report what is measured, with bootstrap confidence intervals.

---

## 2. Data

### 2.1 RCAEval (primary benchmark)

- Repo: https://github.com/phamquiluan/RCAEval. Data is on Zenodo (linked from the repo).
- Datasets:
  - **RE1:** metrics only, 375 cases.
  - **RE2:** metrics + logs + traces.
  - **RE3:** multi-source, with **code-level faults**.
- Systems: Online Boutique, Sock Shop, Train Ticket.
- Each case has an annotated root-cause service and root-cause indicator, plus a known fault injection time.
- **First task:** clone it, run 2–3 baselines end-to-end, and write down:
  - the folder layout,
  - the metric column naming convention (service + metric name),
  - where the injection time and labels are stored,
  - how traces are formatted.

  Don't assume the format; inspect it.
- Use RCAEval's own evaluation code for AC@k so numbers are comparable with published results.

### 2.2 Synthesised change events for RCAEval (needed for M1)

RCAEval has no deployment log, so we create a `change_events` table per case. **This must be done carefully, or reviewers will say the label is leaked.**

Rules:

- **Code-level faults (RE3):**
  - Add a `deploy` event on the true root-cause service at `t_inject − U(0, 120s)`.
  - With probability `p_miss` (e.g. 0.2), drop it to simulate an untracked change.
- **Resource / network faults (CPU, MEM, DISK, DELAY, LOSS):**
  - No true change event. These test that M1 doesn't hurt when there's no change involved.
  - Optionally add a `config` event for faults that would really come from config (e.g. a CPU-limit change). Document which ones.
- **Decoys:** for every case, add `K ~ Poisson(λ_decoy)` benign deploy/config events on random **non-root** services at random times in the look-back window.
- Sweep `λ_decoy ∈ {0, 1, 2, 4}`, `p_miss ∈ {0, 0.2, 0.5}`, and time jitter. Report the robustness curves (claim C3).
- Fix the random seeds and publish the generator script.

### 2.3 Our testbed dataset (realistic change events + cost)

**Stack:**

- **Cluster:** minikube or kind on a laptop (≥16 GB RAM recommended; Train Ticket is too heavy, use **Online Boutique**).
- **App:** Online Boutique (`GoogleCloudPlatform/microservices-demo`). It ships a Locust-based `loadgenerator`; tune users and spawn rate.
- **Monitoring:**
  - Prometheus + cAdvisor + kube-state-metrics via the `kube-prometheus-stack` Helm chart.
  - Scrape interval: 5s.
- **Traces (optional but valuable for M2):** OpenTelemetry Collector → Jaeger. Online Boutique has OTel support.
- **Logs:** `kubectl logs` collected via Loki or a simple log-shipper script into Postgres.

**Fault catalogue** (each is a *deployment* or *config change*, so the change event is real):

| # | Type | How | Expected effect |
|---|---|---|---|
| F1 | Deploy: N+1 RPC | Patch `recommendationservice` to call `productcatalogservice.GetProduct` once per item instead of `ListProducts` once | Catalog CPU and RPC count ↑, front-end latency ↑ |
| F2 | Deploy: CPU-heavy loop | Add a busy loop or a slow regex in `currencyservice` | CPU ↑, latency ↑ |
| F3 | Deploy: memory leak | Append to a global list per request in a service | MEM ↑, OOM restarts |
| F4 | Deploy: retry storm | Short timeout + aggressive retries in `checkoutservice` client | Downstream request rate ↑, errors ↑ |
| F5 | Config: lower CPU limit | `kubectl set resources` on a service | Throttling ↑, latency ↑ |
| F6 | Config: lower replicas / cache off | Scale to 1 replica, or disable a cache env var | Latency ↑ under load |
| F7 | Benign deploy (decoy) | Rebuild the same image with a version bump | Should NOT be blamed |
| F8 | Non-change fault (control) | Chaos Mesh CPU stress or network delay, no deploy | M1 must not invent a change cause |

**Procedure per case:**

1. Warm up for 10 min.
2. Record baseline for 10 min.
3. Apply the change via a script that also writes to `change_events`, so the timestamp is exact.
4. Run 10 min.
5. Roll back.
6. Cool down for 5 min.

Mix in 0–3 benign deploys per case. Target ~120 cases: 8 types × 3 services × 5 repeats, adjusted for feasibility.

- Labels: `root_cause_service`, `root_cause_change_id` (if any), `fault_type`, `t_change`, `t_anomaly`.
- Export each case to the same layout as RCAEval, so a single loader works for both.

### 2.4 Cost model ("simulated cost attribution using published pricing")

Cost is **derived from resource usage**. Locust only creates load. Define it in `config/pricing.yaml`. All prices are placeholders: **fill them from the provider's public pricing page and record the date and region in the paper.**

```yaml
currency: INR
fx_usd_inr: <fill>             # record date
region: ap-south-1              # example
compute:
  vcpu_hour: <fill>             # derived from an on-demand instance price / vCPUs
  gb_ram_hour: <fill>
storage:
  iops_month: <fill>            # provisioned-IOPS-style pricing (e.g. io-class volumes)
  gb_month: <fill>
network:
  egress_gb: <fill>
  inter_az_gb: <fill>
requests:
  per_million_requests: <fill>  # API-gateway / LB style
```

**Per service s, per time step Δt:**

```
cost_s(t) = vcpu_hour     * cpu_cores_s(t)        * Δt/3600
          + gb_ram_hour   * mem_gb_s(t)           * Δt/3600
          + iops_price    * iops_s(t)             * Δt/(30*24*3600)
          + egress_gb     * net_tx_gb_s(t)
          + per_req_price * requests_s(t)         / 1e6
total_cost(t) = Σ_s cost_s(t)
```

- Two pricing modes:
  - **"usage" (pay-per-use):** cost follows usage, as above.
  - **"provisioned + autoscale":** cost = replicas × instance price. An HPA-like rule adds replicas when CPU > 70%. This gives step-shaped cost spikes, which is realistic.
- Map metric names per dataset: `cpu`, `mem`, `disk io`, `net tx`, `request rate`. Where a metric is missing (e.g. no IOPS in RE1), drop that term and document it.

**Fallback ladder:**

- **(a)** Testbed metrics × prices: best.
- **(b)** RCAEval metrics × prices: always available.
- **(c)** Hypothesis-driven parametric cost: `cost = Σ w_k · f_k(metrics)` with assumed weights ranges. Run a **sensitivity analysis**:
  - sample prices ±50%,
  - check that the cause ranking and the top attributed cause stay stable,
  - report the stability rate.

Never present (b) or (c) as real billing.

### 2.5 Splits

- Per system: 60% dev (method tuning), 20% calibration (M3 temperature/isotonic, LLM thresholds), 20% test.
- Also report **leave-one-system-out** (tune on 2 systems, test on the 3rd) for generalisation.

---

## 3. System architecture

```
 RCAEval cases ─┐
 Testbed cases ─┼─► replayer.py ──► Postgres/TimescaleDB ──► detector.py (online)
 change_events ─┘   (1×–60× speed)       (metrics, logs,           │ anomaly at t_a
                                          traces, cost,            ▼
                                          changes)          rca_engine/
                                                            ├─ base: BARO scorer
                                                            ├─ M1 change anchoring
                                                            ├─ M2 topo causal graph + walk
                                                            └─ M3 cost attribution + calibration
                                                                   │ RCA result JSON
                                                                   ▼
                                                            llm_layer/
                                                            ├─ signature + similarity
                                                            ├─ incident graph (NetworkX + PG)
                                                            └─ tier router (T1/T2/T3)
                                                                   │ explanation JSON
                                                                   ▼
                                                  Streamlit dashboard  ◄──► agent (tool-calling LLM)
                                                  (+ embedded Grafana panels, optional)
```

Keep dependencies small: Postgres (with the Timescale extension if easy, plain Postgres otherwise), Python, Streamlit. Neo4j and Kafka are **not** needed.

### 3.1 Database schema (minimum)

```sql
CREATE TABLE metrics (ts TIMESTAMPTZ, case_id TEXT, service TEXT, metric TEXT, value DOUBLE PRECISION);
CREATE INDEX ON metrics (case_id, service, metric, ts);
CREATE TABLE logs    (ts TIMESTAMPTZ, case_id TEXT, service TEXT, level TEXT, message TEXT);
CREATE TABLE spans   (ts TIMESTAMPTZ, case_id TEXT, trace_id TEXT, span_id TEXT, parent_id TEXT,
                      service TEXT, operation TEXT, duration_ms DOUBLE PRECISION, status INT);
CREATE TABLE change_events (event_id TEXT PRIMARY KEY, case_id TEXT, ts TIMESTAMPTZ, service TEXT,
                      type TEXT CHECK (type IN ('deploy','config')), detail JSONB, is_decoy BOOL);
CREATE TABLE cost    (ts TIMESTAMPTZ, case_id TEXT, service TEXT, component TEXT, inr DOUBLE PRECISION);
CREATE TABLE incidents (incident_id TEXT PRIMARY KEY, case_id TEXT, t_anomaly TIMESTAMPTZ,
                      detected_by TEXT, status TEXT);
CREATE TABLE rca_results (incident_id TEXT, rank INT, candidate TEXT, candidate_type TEXT,
                      score DOUBLE PRECISION, confidence DOUBLE PRECISION,
                      cost_share_inr DOUBLE PRECISION, causal_path JSONB, module_scores JSONB);
CREATE TABLE explanations (incident_id TEXT, tier INT, model TEXT, input_tokens INT,
                      output_tokens INT, cost_inr DOUBLE PRECISION, latency_ms INT,
                      reused_from TEXT, body JSONB, ts TIMESTAMPTZ);
CREATE TABLE ig_nodes (node_id TEXT PRIMARY KEY, kind TEXT, attrs JSONB);   -- incident graph
CREATE TABLE ig_edges (src TEXT, dst TEXT, kind TEXT, attrs JSONB);
```

Create a **read-only DB role** for the agent.

### 3.2 Replayer

- Reads a case and inserts rows with original timestamps shifted to "now", at a configurable speed (1×, 10×, 60×).
- Emits change events at their (shifted) times.
- The dashboard and detector see it as live data.

### 3.3 Online anomaly detector

- Watch the front-end SLO metrics (p95 latency, error rate) and total cost.
- Use a robust z-score: `|x − median_W| / (1.4826 · MAD_W)` over a sliding 10-min window, threshold 4, at least 3 consecutive points. A BOCPD (Bayesian online change point) variant is optional.
- On trigger:
  - create an incident at `t_a`,
  - call the RCA engine with the window `[t_a − 10 min, t_a + 5 min]` and change look-back `L = 15 min`.
- For benchmark evaluation you can also use the labelled injection time (as RCAEval baselines do). Report both settings.

---

## 4. RCA engine (the algorithm)

**Notation:**

- Services `S`. Metric series `x_{s,m}(t)`.
- Pre-window `P = [t_a − W, t_a)`, post-window `Q = [t_a, t_a + W']`.
- Change events `E`, each `e = (service s_e, type, t_e)`.
- Candidates `C` = all (service, metric) pairs ∪ all change events in `[t_a − L, t_a + W']`.

### 4.1 Base scorer: BARO-style robust scoring

For each (s, m):

```
z_{s,m} = max_{t∈Q} |x_{s,m}(t) − median_P(x_{s,m})| / IQR_P(x_{s,m})
```

- Service score `b_s = max_m z_{s,m}`.
- Normalise to [0,1] by rank or min-max within the case.
- Use RCAEval's BARO implementation as the reference and verify you reproduce its reported numbers before modifying anything.

### 4.2 M1: Change-event anchoring

For each change event `e` on service `s_e`:

1. **Effect test (interrupted time series)** on each metric of `s_e`, and on each metric of its call-graph neighbours within 1 hop:

   ```
   y_t = β0 + β1·t + β2·D_t + β3·(t − t_e)·D_t + ε_t ,   D_t = 1[t ≥ t_e]
   ```

   - Fit with OLS using Newey–West (HAC) standard errors (`statsmodels`, `cov_type='HAC'`), because metrics are autocorrelated.
   - Effect `δ_e = max_m (|β2|/se(β2) , |β3|/se(β3))`.
   - Cheaper alternative / sanity check: Mann–Whitney U between pre and post windows of length 5 min.
2. **Temporal weight:** `w_e = exp(−(t_a − t_e)/τ)` for `t_e ≤ t_a`, else 0. Start with τ = 5 min; tune on dev.
3. **Significance gate:** only count events with `p_e < α` (α = 0.01; Bonferroni over events per case).
4. **Change score:** `c_e = w_e · σ(δ_e − δ0)`, where σ is the sigmoid and δ0 a threshold tuned on dev.
5. **Combination:**
   - Change events become candidates with score `c_e`.
   - Their service also gets a boost: `b'_s = b_s + λ · max_{e: s_e = s} c_e`.
   - **Propagation:** if `s_e` is an ancestor of the anomalous service in the M2 graph, the change candidate inherits `c_e · reach(s_e → anomaly)`. Reach comes from the walk in 4.3.
6. **Output:** e.g. "deploy-5847 on recommendationservice", with its own score.

**Decoy defence (essential):**

- A benign deploy produces δ ≈ 0, so it fails the gate.
- Check that resource-fault cases (no true change) don't lose accuracy versus base. Report this explicitly.

### 4.3 M2: Topology-constrained causal graph + ranking

1. **Call graph `G_call`:**
   - Build from traces: for each span with a parent, add the edge `caller_service → callee_service`.
   - For RE1 (no traces), use the known static architecture of each system. Write it once as a YAML adjacency list.
2. **Allowed causal edges:**
   - Faults propagate **callee → caller**, so allow `callee → caller` between services.
   - Inside a service: allow `resource → latency → errors` (cpu, mem, disk, net → latency → error rate).
   - Everything else is forbidden.
3. **Causal discovery on allowed edges only.** Variables = the top-k most anomalous metrics per service (k = 3), to keep the variable count ≤ ~60.
   - **Option A (default):** PC algorithm from `causal-learn`, with `BackgroundKnowledge` forbidding non-allowed edges. Use the Fisher-z test on differenced, standardised series, α = 0.05.
   - **Option B:** Granger causality (`statsmodels`, lag ≤ 3) only on allowed pairs. Keep the edge if p < 0.05.
   - Keep both; choose by dev performance; report both in the appendix.
4. **Ranking walk:**
   - Run personalised PageRank on the **reversed** learned graph, starting from the anomalous front-end SLO nodes.
   - Personalisation vector = normalised anomaly scores `z`.
   - Edge weights = |partial correlation|.
   - Damping 0.85, implemented with NetworkX `pagerank`.
   - Result: `r_s` per service (max over its metric nodes).
5. **Final score:**

   ```
   S(c) = α·b̂_c + β·r̂_c + γ·ĉ_c     (hats = normalised within case)
   ```

   Tune α, β, γ on the dev split by grid search on AC@1. Report the selected values.

### 4.4 M3a: Cost attribution

1. Fit a **linear SCM** on the pre-window `P` along the learned graph: each node is regressed on its parents (ridge, λ = 1e-2). Cost nodes are `cost_s` (from the §2.4 formula) and `total_cost`, with parents = that service's resource metrics.
2. Observed spike: `ΔC = mean_Q(total_cost) − mean_P(total_cost)`.
3. **Counterfactual for candidate c:** `do(c := mean_P(c))` for the post-window, propagated through the SCM to get `Ĉ_{−c}`. Raw attribution `a_c = mean_Q(total_cost) − mean(Ĉ_{−c})`.
4. **Shapley** over the top-k candidates (k ≤ 5, so ≤ 32 coalitions; exact computation is cheap). The value function `v(T)` = cost reduction from jointly resetting the set T. Shapley values sum to `v(all)`.
5. Report `₹ φ_c` and `φ_c/ΔC` per cause, plus "unexplained" = `ΔC − v(all)`.
6. **Validation (C5):** on the testbed the true cause is known. Check that it receives the largest φ, and report the fraction of cases where it does.

### 4.5 M3b: Calibrated confidence

1. Raw case-level probabilities: `p_c = softmax(S(c)/T)` over candidates.
2. Fit **temperature T** on the calibration split by minimising NLL of the true cause. Alternative: **isotonic regression** on top-1 score → P(correct).
3. Metrics:
   - ECE (15 bins),
   - Brier score,
   - reliability diagram,
   - plus a **selective accuracy** curve (accuracy when only answering if conf ≥ θ).
4. Product behaviour: if top-1 conf < θ_abstain, show "low confidence — top 3 candidates".

### 4.6 What-if simulator

- Reuses the SCM: user picks an intervention, e.g. "revert deploy X" or "CPU limit +1 core" (mapped to a node change).
- Propagate through the graph and show the predicted latency and cost deltas.
- Label it as a *model estimate*.

### 4.7 Engine output (JSON contract shared by the LLM layer, dashboard and agent)

```json
{
  "incident_id": "inc-0042",
  "t_anomaly": "2026-11-20T14:30:00Z",
  "candidates": [
    {"rank": 1, "id": "deploy-5847", "type": "change", "service": "recommendationservice",
     "confidence": 0.84, "cost_share_inr": 6150.0, "cost_share_frac": 0.75,
     "causal_path": ["deploy-5847", "recommendationservice.rpc_out", "productcatalogservice.cpu",
                     "frontend.latency_p95", "total_cost"],
     "evidence": {"its_level_z": 7.9, "minutes_before_anomaly": 4.2, "base_z": 5.1, "walk": 0.31}},
    {"rank": 2, "id": "productcatalogservice.cpu", "type": "metric", "confidence": 0.09}
  ],
  "delta_cost_inr": 8200.0,
  "unexplained_inr": 410.0,
  "decoys_ignored": ["deploy-5850"]
}
```

---

## 5. Evaluation protocol (RCA)

- **Metrics:** AC@1, AC@3, AC@5, Avg@5 at the service level. Add the indicator level (fine-grained) where RCAEval provides labels. Also report "change-level AC@1" on cases that have a true change.
- **Baselines:** BARO, RCD, CIRCA (required), plus any other baselines in the RCAEval framework that run in reasonable time.
- **Ablations:**
  - Base
  - +M1
  - +M2
  - +M1+M2
  - Full
  - M2 with PC vs Granger
  - M2 without topology constraint
- **Robustness:**
  - accuracy vs λ_decoy, p_miss and change-time jitter (± 0–5 min),
  - fault types with no change event (must not degrade).
- **Generalisation:** leave-one-system-out.
- **Efficiency:** wall-clock time per case and the number of CI tests in PC with vs without the constraint.
- **Statistics:** 1000× bootstrap 95% CIs; paired bootstrap or McNemar for full vs best baseline.
- **Reproducibility:** fixed seeds, a single `make reproduce` command, all configs in `configs/`.

---

## 6. LLM layer: incident knowledge graph + tiered routing

### 6.1 Incident graph

- **Nodes:** `service`, `metric`, `change`, `incident`, `root_cause`, `fix`, `explanation`.
- **Edges:**
  - `incident -HAS_ANOMALY-> metric`
  - `incident -CAUSED_BY-> root_cause` (confidence)
  - `root_cause -ON-> service`
  - `root_cause -VIA_PATH-> metric` (ordered)
  - `incident -RESOLVED_BY-> fix` (outcome: success/fail)
  - `incident -SIMILAR_TO-> incident` (similarity)
  - `service -CALLS-> service`
- **Storage:** `ig_nodes`/`ig_edges` in Postgres, loaded into NetworkX at startup.

### 6.2 Incident signature and similarity

The signature for an incident is a tuple:

- root-cause service,
- candidate type (change / metric),
- change type (deploy / config / none),
- fault family (if known),
- the multi-hot set of anomalous metric *kinds* (cpu, mem, latency, …) per service role,
- the causal path pattern (sequence of metric kinds),
- the ΔCost bucket.

Similarity:

```
sim = 0.4·Jaccard(anomalous metric sets) + 0.3·path_similarity + 0.2·[same root service & change type]
    + 0.1·cos(embed(summary_new), embed(summary_old))
```

- `path_similarity` = 1 − normalised edit distance between the path sequences.
- Embeddings: a small local model (`sentence-transformers/all-MiniLM-L6-v2`), so no API cost.
- Optional upgrade: a Weisfeiler–Lehman graph kernel on the causal subgraph (via `grakel`).

### 6.3 Tier router

| Tier | Condition | Action | LLM cost |
|---|---|---|---|
| T1 | `sim ≥ τ_hit` and the matched incident's fix outcome = success | Fill the stored explanation template with new numbers (service, ₹, times) | 0 |
| T2 | `τ_partial ≤ sim < τ_hit` | Small model (e.g. `claude-haiku-5-5`) gets the RCA JSON + the matched past explanation and adapts it | low |
| T3 | `sim < τ_partial` or confidence < θ_abstain | Large model (e.g. `claude-sonnet-5-5`) gets the RCA JSON + compact causal subgraph + top 20 relevant log lines | high |

- Tune τ_hit and τ_partial on the calibration split to maximise savings subject to correctness ≥ the T3-only correctness minus 2 points.
- **Write-back:** every T2/T3 output is stored as `explanation` and `fix` nodes and linked. If a user marks it wrong in the dashboard, set outcome = fail. T1 never reuses failed explanations.
- **Prompt compaction:** send only the RCA JSON, the causal path, and the top-N log lines matched by service + time window + error level. Never send raw metric dumps.
- Use the API's prompt caching for the fixed system prompt and the schema.

**LLM output schema (enforced via tool/JSON mode):**

```json
{"summary": "...", "root_cause": "...", "evidence": ["..."], "recommended_fix": "...",
 "estimated_saving_inr_per_day": 0, "confidence_note": "...", "references": ["incident ids"]}
```

### 6.4 LLM-layer evaluation (C6)

- **Stream protocol:** replay test incidents in timestamp order (recurring fault types appear naturally). Start with an empty graph (cold start) and with a graph pre-filled from the dev split (warm start).
- **Systems compared:**
  - (i) raw telemetry → large LLM (truncated to the context budget),
  - (ii) RCA JSON → large LLM, no memory,
  - (iii) ours (tiered + memory).
- **Metrics:**
  - tokens in/out per incident,
  - ₹ per incident (from published API prices; record the date),
  - p50/p95 latency,
  - T1/T2/T3 hit rates over time (plot).
- **Correctness:**
  - automatic check that the explanation names the correct root cause and service,
  - an LLM judge with a fixed rubric (factual consistency with the RCA JSON, actionable fix, no hallucinated services),
  - manual rating of 50 samples by two people (report agreement).
- **Ablation:** without similarity components; without write-back.

---

## 7. Agent (chat assistant on the dashboard)

- Tool-calling LLM loop (Claude API tool use). Start on the small model; escalate to the large model if a tool call fails or the user asks for deep analysis.
- **Tools (read-only):**

  | Tool | Purpose |
  |---|---|
  | `list_incidents(since, until, min_cost)` | browse incidents |
  | `get_rca(incident_id)` | the §4.7 JSON |
  | `get_cost_breakdown(incident_id | time range, group_by)` | cost by service/component |
  | `query_metrics(service, metric, start, end, agg)` | parameterised SQL, no free-form SQL |
  | `get_logs(service, start, end, level, limit)` | relevant logs |
  | `find_similar(incident_id, k)` | incident-graph neighbours |
  | `what_if(incident_id, intervention)` | §4.6 simulator |
  | `get_changes(start, end, service)` | deploy/config history |

- **Guardrails:**
  - read-only DB role,
  - row limits,
  - every numeric answer must come from a tool result; the system prompt says to cite incident ids,
  - log every tool call to an `agent_log` table.
- **Example questions it must answer:**
  - "Why did cost jump at 14:30?"
  - "Which deploys this week caused incidents?"
  - "How much would reverting X save?"
  - "Show similar past incidents."
- **Evaluation (light):** 30 scripted questions with known answers; report the % answered correctly and the average tool calls.

---

## 8. Dashboard (Streamlit, with optional Grafana)

**Pages:**

1. **Live overview:** front-end latency, error rate, total cost (₹/hour) over time; anomaly markers; change events as vertical lines; replay speed control.
2. **Incident detail:**
   - ranked root-cause cards (confidence bar, ₹ share),
   - causal graph view (`streamlit-agraph` or `pyvis`) with the causal path highlighted,
   - cost waterfall (Shapley shares + unexplained),
   - the LLM explanation with a tier badge (T1/T2/T3) and its ₹/latency,
   - 👍/👎 feedback (writes the outcome back to the incident graph).
3. **Logs:** filter by service, level and time; the incident window is pre-filtered.
4. **Cost explorer:** by service and component; pricing assumptions shown on the page.
5. **What-if:** choose an intervention → predicted latency/cost.
6. **Assistant:** chat panel (§7).
7. **Evaluation:** AC@k tables, ablation, reliability diagram, LLM savings charts. Doubles as the paper figures.

Grafana is optional: point it at the same Postgres for the live panels and embed via iframe if you want the "Grafana" look. Streamlit alone is enough.

---

## 9. Repository layout

```
cloud-rca/
├─ configs/            pricing.yaml, rca.yaml, llm.yaml, systems/*.yaml (static call graphs)
├─ data/               raw/ (RCAEval, testbed), processed/, change_events/
├─ testbed/            k8s manifests, fault patches (F1–F8), run_case.sh, collect.py
├─ ingest/             loaders (rcaeval.py, testbed.py), cost_model.py, synth_changes.py, replayer.py
├─ detect/             detector.py
├─ rca/                base_baro.py, m1_change.py, m2_graph.py, m3_cost.py, calibrate.py, whatif.py, engine.py
├─ llm/                signature.py, incident_graph.py, router.py, prompts/, explain.py
├─ agent/              tools.py, agent.py
├─ app/                streamlit pages
├─ eval/               run_rca_eval.py, run_llm_eval.py, robustness.py, stats.py, figures.py
├─ db/                 schema.sql
├─ tests/
└─ Makefile            setup, ingest, eval, app, reproduce
```

**Python libraries:**

- Data and stats: `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`
- Causal and graphs: `causal-learn`, `networkx`
- Storage: `psycopg[binary]`, `sqlalchemy`
- Dashboard: `streamlit`, `plotly`, `streamlit-agraph` or `pyvis`
- LLM: `anthropic`, `sentence-transformers`
- Testing: `pytest`
- Optional: `grakel`, `ruptures` (change points)

---

## 10. Six-month timeline (week by week)

Start: mid-October 2026. Each month ≈ 4 weeks. **Bold** = milestone.

### Month 1: Foundations
- W1: Read the BARO, RCD, CIRCA and RCAEval papers. Set up the repo, Postgres, and `schema.sql`.
- W2: Download RCAEval and document its format. Run BARO, RCD and CIRCA through the RCAEval framework on RE2.
- W3: Reproduce the baseline numbers on RE1/RE2/RE3. Build the `rcaeval.py` loader into Postgres.
- W4: Write `replayer.py` and `detector.py`. **Milestone: baseline table reproduced; a replayed case visible in a basic Streamlit chart.**

### Month 2: Testbed, cost, change events
- W5: minikube + Online Boutique + kube-prometheus-stack + Locust running stably. Optional: OTel/Jaeger.
- W6: Implement fault patches F1–F8 and `run_case.sh` (writes change_events). Run 10 pilot cases.
- W7: Run the full ~120-case campaign (automate it overnight). Export to the RCAEval-like layout.
- W8: `cost_model.py` + `pricing.yaml` (fill prices, record date), plus `synth_changes.py` for RCAEval with decoys. **Milestone: both datasets have cost + change events. Fallback check: if the testbed slips, continue with RCAEval + synthetic changes.**

### Month 3: Core algorithm (M1, M2)
- W9: Base BARO scorer in our code; match the RCAEval BARO numbers.
- W10: M1 (ITS with HAC, gate, temporal weight, propagation). Test on testbed dev cases.
- W11: M2 (call graph from traces / static YAML, PC with background knowledge, Granger option, PageRank).
- W12: Score combination + grid search on dev. **Milestone: first full results table vs baselines + M1/M2 ablation.**

### Month 4: M3, robustness, what-if
- W13: SCM fit, counterfactual cost attribution, exact Shapley; validate C5 on the testbed.
- W14: Calibration (temperature + isotonic), ECE, reliability diagram, abstention.
- W15: Robustness sweeps (decoys, missing events, jitter), leave-one-system-out, runtime.
- W16: What-if simulator; freeze the RCA engine and the JSON contract. **Milestone: complete RCA results + all RCA figures.**

### Month 5: LLM layer, agent, dashboard
- W17: Incident graph storage, signatures, similarity.
- W18: Tier router, prompts, write-back, prompt caching; tune thresholds on the calibration split.
- W19: Agent tools + tool-calling loop; Streamlit pages 1–5.
- W20: Pages 6–7, feedback loop, LLM evaluation (stream protocol, 3 systems). **Milestone: end-to-end demo + LLM cost/latency results.**

### Month 6: Evaluation, paper, report
- W21: Final test-split runs, bootstrap CIs, significance tests, agent Q&A evaluation, manual rating of explanations.
- W22: Paper draft (intro, related work, method, setup). Pick a venue and check its deadline/format.
- W23: Results, ablations, limitations (simulated cost, synthetic change events on RCAEval). Release the dataset + code.
- W24: Capstone report, slides, demo video; buffer for slippage. **Milestone: submission-ready paper + final presentation.**

Weeks 25–26 are **buffer**. Use them if the testbed or the LLM evaluation slips.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Testbed unstable or laptop too weak | Use only Online Boutique; reduce replicas; fall back to RCAEval + synthetic changes (§2.2) and parametric cost (§2.4c) |
| "Label leakage" critique of synthetic change events | Decoys, missing events, no-change fault types, robustness curves; the testbed has real change events |
| PC too slow / unstable | Top-k metric selection, the topology constraint, Granger fallback |
| Gains over BARO are small | Focus the claims on change-level accuracy, robustness to decoys, calibration and cost attribution, which baselines don't offer |
| LLM costs during development | Use T1/T2 heavily; cache; cap T3 calls; use the small model for agent development |
| Cost numbers questioned | Publish the pricing config with date/region; sensitivity analysis; always say "simulated" |
| Novelty overlap (deploy-aware RCA in industry, e.g. Gandalf; LLM-RCA with retrieval, e.g. RCACopilot) | Cite them; position the work as an open benchmark plus the combination of causal graph + change effect + cost attribution + calibration + cost-aware LLM memory |

---

## 12. Reading list (start here)

- RCAEval benchmark paper and repo (Pham et al.): datasets, baselines, metrics.
- BARO (Pham et al., FSE 2024): base scorer.
- RCD (Ikram et al., NeurIPS 2022): causal-discovery RCA baseline.
- CIRCA (Li et al., KDD 2022): regression-based hypothesis testing on a causal graph, close to M3.
- "Root Cause Analysis for Microservice System based on Causal Inference: How Far Are We?" (ASE 2024): broad comparison.
- Gandalf (Microsoft, NSDI 2020): safe deployment / bad-rollout detection, related to M1.
- RCACopilot (Microsoft, EuroSys 2024): LLM RCA with historical incident retrieval, related to §6.
- Interrupted time series with HAC errors: any standard econometrics or ITS tutorial.
- causal-learn docs: PC with `BackgroundKnowledge`.

Verify each citation's venue and year before putting it in the paper.

---

## 13. Day-1 checklist

- [ ] Create the repo with the §9 layout; commit `schema.sql` and an empty `pricing.yaml`.
- [ ] `docker run` Postgres; apply the schema.
- [ ] Clone RCAEval, download RE2, run BARO on one case, and print AC@k.
- [ ] Write down the RCAEval file format in `data/README.md`.
- [ ] Install minikube and check it can run Online Boutique (resource check).
