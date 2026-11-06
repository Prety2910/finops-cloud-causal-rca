# Data

Raw and processed data are git-ignored. Everything below was **observed from the files**, not assumed.
Re-run `make data` to rebuild and re-verify; see [`docs/DATA_AUDIT.md`](../docs/DATA_AUDIT.md) for the audit.

## Directories

| Path | What | Source |
|---|---|---|
| `data/raw/rcaeval/` | Hugging Face Parquet mirror of RE1/RE2/RE3 (735 cases) | `huggingface.co/datasets/phamquiluan/RCAEval` |
| `data/raw/zenodo/` | Canonical archives, md5-verified, extracted (`<name>.ok` holds md5) | Zenodo record 14590730 (doi 10.5281/zenodo.14590730) |
| `data/processed/rcaeval/` | **Curated working copy. Load from here.** Mirror + 3 patched cases, `cases.parquet` manifest | built by `scripts/build_rcaeval_processed.py` |
| `data/processed/rcaeval_verification.csv` | per-case structural checks (735 rows) | `scripts/verify_rcaeval.py` |
| `data/processed/rcaeval_hf_vs_zenodo.csv` | per-case mirror-vs-canonical diff (735 rows) | `scripts/compare_hf_zenodo.py` |

## RCAEval: processed layout (`data/processed/rcaeval/`)

```
cases.parquet                      one row per case (manifest; 735 rows)
<case>/inject_time.txt             unix seconds of fault injection (single integer)
<case>/metrics.parquet             wide table, see below
<case>/logs.parquet                RE2, RE3 only (not RE1; 1 RE2/RE3 case gap fixed, see audit)
<case>/traces.parquet              RE2-OB, RE2-TT, RE3-OB, RE3-TT only (Sock Shop is not traced)
```

**Case name** = `{suite}{system}_{root_cause_service}_{fault}_{repetition}`, e.g. `re2tt_ts-route-service_cpu_1`.
`suite` ∈ re1/re2/re3, `system` ∈ ob (Online Boutique) / ss (Sock Shop) / tt (Train Ticket).
Service names contain `-` but never `_`, so `case.split("_")` is safe for the last two fields.

**`cases.parquet` columns**: `case, dataset (RE1-OB…), suite, system, system_name, root_cause_service, fault,
fault_description, repetition, inject_time, n_metrics, n_timesteps, time_start, time_end, duration_minutes,
normal_timesteps, faulty_timesteps, has_logs, n_logs, has_traces, n_traces, has_root_cause_file, source`
(`source` = `hf` or `hf+zenodo:<what>` for patched cases).

### Where the labels are
- **Root-cause service**: `cases.parquet.root_cause_service` (also embedded in the case name).
- **Injection time**: `<case>/inject_time.txt` (== `cases.parquet.inject_time`; checked for all 735).
- **Fault type**: `cases.parquet.fault`: RE1/RE2 `cpu, mem, disk, delay, loss` (+`socket` in RE2); RE3 `f1…f5` = "code-level fault F1…F5".
- **Root-cause indicator** (metric/log that reveals the fault): **not in this data.** The README of the mirror
  mentions `root_cause.txt` but `has_root_cause_file` is False for all 735. The service level is the only label we have;
  RCAEval's own evaluator derives indicator-level credit elsewhere. Do not plan indicator-level metrics until located.

### Metrics (`metrics.parquet`)
- Columns: `time` (int64 unix seconds, **1 Hz**, strictly increasing, no gaps in the processed copy) then one float64
  column per series named **`<service>_<kind>`**. Split with `col.split("_", 1)` (services have `-`, kinds have `-` too, never `_`).
- Service names: OB = `adservice, cartservice, checkoutservice, currencyservice, emailservice, frontend, paymentservice,
  productcatalogservice, recommendationservice, redis, shippingservice` (+ `frontend-external`, `main`,
  `PassthroughCluster` in RE1-OB; `frontend-check` in RE3-OB). SS = `carts, carts-db, catalogue, catalogue-db, front-end,
  orders, orders-db, payment, queue-master, rabbitmq, rabbitmq-exporter, session-db, shipping, user, user-db`.
  TT = 64 `ts-*` services (+ `istio-init` in RE2-TT/RE3-TT).
- Metric kinds by dataset:

| Dataset | kinds |
|---|---|
| RE1-OB, cpu/mem faults | `cpu, mem, load, latency, error` (**different vocabulary**; 70-minute series: 2 679–4 201 rows) |
| RE1-OB, delay/disk/loss | `cpu, mem, workload, latency-50, latency-90, error` (721 rows) |
| RE1-SS, RE1-TT | `cpu, mem, workload, latency-50, latency-90, error` |
| RE2-*, RE3-* | the above + `socket`, `diskio` (disk I/O only for some services) |

  So the disk metric is `diskio` (RE2/RE3) and **absent from RE1** (RCAEval's code uses `latency` as the "disk metric" for RE1).
  There is no request-rate/IOPS/network-bytes series: **cost model terms** available are `cpu`, `mem`, `workload` (≈request rate), `diskio` (RE2/3 only), `socket`. No network egress.
- Series length / window around injection:

| Dataset | rows | duration | pre / post inject |
|---|---|---|---|
| RE1-OB | 721 (delay, disk, loss), 2 679–4 201 (cpu, mem) | 12 / 70 min | 360 / 361 or 2100 / 2101 |
| RE1-SS, RE1-TT | 607–721, 721–961 | 10–16 min | 360 / ~361 (TT up to 480/481) |
| RE2-* | 930–1 441 (OB), 1 441 (SS, TT) | 24 min | 720 / 721 |
| RE3-OB, RE3-SS | 1 441 | 24 min | 720 / 721 |
| RE3-TT | 1 801 | 30 min | 900 / 901 |

- **Missing values**: NaN where a metric was not observed (e.g. latency with no requests). RCAEval's runner does
  `replace(±inf, nan) → ffill → fillna(0)`; do the same (document any deviation). Partly-NaN columns are common (up to 5–11% of cells in a case).
- **Foreign-system columns** (upstream defect): 4 cases carry mostly-NaN columns from the *other* app deployed in the same cluster:
  `re1ob_productcatalogservice_cpu_3` (7 SS cols), `re3ob_adservice_f3_2` / `_f3_3` (30 SS cols), `re3ss_carts_f1_3` (22 OB cols).
  Loader rule: **keep only columns whose service belongs to the case's system** (service lists above / `configs/systems/*.yaml`).

### Logs (`logs.parquet`)
`timestamp` (int64 **unix seconds**; the Zenodo CSV has nanoseconds, the mirror divides by 1e9), `container_name`
(= the service name as in metrics, **checked: always a subset of metric services**), `message` (free text).
Window is ±(duration/2) around injection. Many services (DBs, queues) emit no logs.
Zenodo's CSV additionally has `time, level, req_path, error` columns that are not in the mirror.

### Traces (`traces.parquet`) — RE2-OB/TT, RE3-OB/TT
Columns: `time` (HH:MM string, ignore), `traceID, spanID, parentSpanID` (null = root), `serviceName, methodName,
operationName`, `startTimeMillis` (ms epoch), `startTime` (**µs** epoch), `duration` (**µs**), `statusCode`.
- `serviceName` is the same vocabulary as the metric service **except** RE2-OB, where the frontend is `frontendservice`
  (metrics/logs: `frontend`). Normalise `frontendservice → frontend`.
- `statusCode` is meaningful only for the gRPC Online Boutique spans (0 OK, 9, 13…); it is entirely null for Train Ticket.
- ~100% of non-root parents resolve inside the same file, so caller→callee service edges can be read directly
  (`scripts/derive_call_graph.py` does this).
- Sock Shop has **no traces**: its call graph in `configs/systems/sock_shop.yaml` is hand-written; verify against the app manifests.

## Counts (verified)

| Dataset | Cases | Fault types | Root-cause services | Logs | Traces |
|---|---|---|---|---|---|
| RE1-OB / SS / TT | 125 each | cpu, mem, disk, delay, loss (25 each) | 5 each | – | – |
| RE2-OB / SS / TT | 90 each | + socket (15 each) | 5 each | ✔ | OB ✔, SS –, TT ✔ |
| RE3-OB | 30 | f1 9, f2 3, f3 6, f4 6, f5 6 | adservice, cartservice, currencyservice, emailservice | ✔ | ✔ |
| RE3-SS | 30 | f1 10, f2 3, f3 10, f4 7 | carts, front-end, orders | ✔ | – |
| RE3-TT | 30 | f1 7, f2 7, f3 10, f4 6 | ts-auth-service, ts-route-service | ✔ | ✔ |

**Implication for the plan:** only RE3 (90 cases, code-level faults) maps naturally to "deploy" change events (§2.2).
RE1/RE2 are all resource/network faults → no true change event, they serve as the no-change control. RE3 has just 2–4 root-cause
services per system and uneven repetitions, so report per-fault-type results with care (small n).

## Testbed (to be filled in when the testbed exists)
- Case export layout (mirror the processed layout above):
- Change-events table fields:

## Cost
- `components_used` per dataset (cpu, mem, workload, diskio, socket): fill from `ingest/cost_model.py` output.
