# Cost Alert Policies

This document explains the three current cost-alert policy functions. They
produce structured recommendations and never modify infrastructure. Thresholds
are initial settings in `configs/alerts.yaml`; they require validation on a
held-out workload set before operational use.

## A1: Suspected idle or zombie compute

Entry point: `cloudrca.detect.idle_resource.assess_idle_resource`.

Required telemetry is a regularly sampled `DatetimeIndex` frame containing
`cpu_pct`, `memory_pct`, and at least one of `requests_per_second` or
`network_mbps`. The policy examines the most recent 24 hours. CPU must be below
the configured 5% floor for at least 80% of observations, and every provided
workload signal must be quiet for at least 80%. Memory is required and reported
as median and P95 evidence. Billable active state must be explicitly true.

With at least 48 historical points before the observation window, seasonal
Ridge predicts CPU from time-of-day, day-of-week and trend features. The
detector scales in-sample training residuals by `1.4826 × MAD`; it requires a
median standardized negative shift of at least 1.5 or a one-sided negative
CUSUM crossing 5. The CUSUM drift is 0.25. Short-history fallback uses the
CPU-floor and independent workload evidence and marks that the seasonal model
was not used.

The returned cost estimate is the supplied hourly compute rate multiplied by
the observed CPU-idle bucket hours. It is an upper bound on spend during those
historical buckets, not a forecast of future savings or a causal effect. The
output states that causal verification was not run. Stop proposals require
known ownership, non-critical status, no active jobs, an inactive schedule, and
clear dependencies; approval is still required. Verification checks service
health, SLOs, jobs, dependencies and billable charges. Rollback is to restart
the resource using its recorded configuration if health checks fail.

## A2: Overprovisioned VM / rightsizing

Entry point: `cloudrca.detect.optimization.recommend_rightsize`.

Input telemetry must cover at least seven regularly sampled days and include
CPU percent, memory working set in GiB, bucket P95 latency and error rate.
Telemetry must have at least 95% coverage. CPU demand is converted to cores
using the current SKU's vCPU count. The minimum modeled CPU capacity is

```text
required vCPU = P99(CPU %) × current vCPU / target CPU utilization
```

Memory capacity is `P99(memory working set) × (1 + memory headroom)`. The
default target CPU utilization is 80%, and memory headroom is 20%. A candidate
must meet the measured latency and error SLOs and be cheaper than the current
SKU. The price/spec catalog must include a version, currency, and instance-hour
price unit. Alternatives must match the current instance family, region,
architecture and CPU-credit model, and must meet optional network/storage
requirements.

```text
gross monthly estimate = (current hourly price - proposed hourly price) × 730
first-month net estimate = gross monthly estimate - one-time transition cost
```

The proposal requires a human-approved maintenance window. It lists restart,
regional availability, compatibility and rollback checks. Post-change
verification checks SLOs, memory pressure and the bill. Savings are estimates
until those checks are measured.

## A3: Unnecessary resource scaling

Entry point: `cloudrca.detect.optimization.recommend_scaling_policy`.

Input telemetry must cover at least seven regularly sampled days and include
request rate, replica count, CPU, memory, bucket P95 latency and error rate.
The caller must also supply collected scaling events (an empty list means the
event source was checked and no events were found), the HPA min/max/CPU target,
CPU and memory requests and limits, plus a versioned and validated safe
requests-per-second-per-replica result from a load test or capacity study.

```text
modeled safe replicas = max(configured minimum,
  ceil(P99(requests/second) × (1 + replica headroom) / safe requests/second/replica))
```

The alert requires observed P95 replicas to exceed the modeled safe count,
validated supporting inputs, and passing latency/error SLOs. A monthly savings
estimate is returned only when the caller confirms that removing replicas
releases billable capacity and supplies the marginal replica-hour rate:

```text
gross monthly estimate = replicas released × marginal hourly rate × 730
```

If replicas share already-paid-for VMs, the model reports no cost saving. The
recommendation requires approval and lists an explicit floor, SLO checks,
replica stability and billing verification, with restoration of previous HPA
limits or replica count as rollback.

## Validation status

Unit tests use generated fixtures to check arithmetic, SLO gates, workload
controls, catalog compatibility, missing evidence and billable-capacity rules.
These fixtures are not experimental measurements. No provider price catalog,
cloud write adapter, Kubernetes testbed run, post-remediation observation or
realized savings result is currently connected to these policies.

## Fleet prioritization

Entry point: `cloudrca.detect.fleet.rank_fleet_opportunities`.

Each normalized input needs a resource, alert category and positive monthly
savings estimate in a shared currency. A caller may provide an
`overlap_group` for recommendations that consume the same billable capacity;
only the largest estimate from each group contributes to the aggregate. With
no group, recommendations for the same resource are treated as overlapping.
This does not discover cross-resource overlap automatically.

## Modeled cost accounting

`cloudrca.ingest.cost_model.resource_cost_breakdown` applies the existing
usage-proxy formulas and groups row-level component costs by supplied
dimensions such as resource, project, or region. It returns used components,
currency, total and grouped reconciliation. Outputs are explicitly marked
`simulated`; these formulas are not provider invoices, and unset or invalid
prices must not be represented as observed spend.

The display order uses the transparent heuristic
`monthly estimate × evidence score × (1 - operational risk)`. Evidence and
risk are ordinal inputs on [0, 1], not calibrated probabilities or causal
effects. Items without a positive monthly estimate are excluded from the
aggregate and counted separately. Synthetic tests verify overlap suppression;
no fleet throughput result has been measured yet.

## Approval and action audit

Entry point: `cloudrca.actions.workflow.ActionWorkflow`.

The local SQLite workflow records a structured action plan under an
idempotency key, permits approval only for configured approver identities, and
records the plan, approval, dry-run and verification events. Reusing an
idempotency key with different action contents is rejected. Payloads with
credential-like field names are rejected from storage. Dry-run records that no
provider adapter was invoked and that no side effect occurred. Verification
records are labeled simulation-only; a passing simulated verification does
not mean a live cloud action was performed or verified. There is no cloud
write path in this implementation.
