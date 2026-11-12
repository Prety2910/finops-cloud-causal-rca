# Capstone Policy Demo Guide

## Purpose and data status

Run `./.venv/bin/python scripts/run_policy_demo.py` from the repository root.
This generates `results/demo/policy_demo.json` and prints the four alert
outcomes plus an overlap-aware fleet estimate. The script fixes its random
seed (default 17), and `--seed` / `--output` can be supplied to reproduce or
save another run.

The equivalent portable commands used by GitHub Actions are:

```bash
python scripts/run_policy_demo.py --output results/demo/policy_demo.json
python scripts/build_demo_dashboard.py \
  --input results/demo/policy_demo.json \
  --output results/demo/index.html
```

The existing dashboard reads that report. Install the optional app dependencies
with `pip install -e '.[app]'`, then launch `streamlit run app/Home.py`. The
dashboard code compiles, but a browser render has not yet been verified in this
environment because Streamlit is not installed here.

For a no-install presentation view, run
`./.venv/bin/python scripts/build_demo_dashboard.py` and open
`results/demo/index.html` in a browser. This static report is generated only
from JSON; it does not need a server or cloud connection.

Every input in this walkthrough is a **synthetic fixture**: telemetry, prices,
capacity test, cost series, and scaling observations. The output demonstrates
that implemented policy functions compose and produce structured evidence. It
is not a real bill, cloud observation, calibrated probability, proven causal
effect, executed action, or measured saving. RCAEval is a separate dataset for
service-level RCA and does not provide the billing ground truth used here.
This walkthrough makes no AWS calls and includes zero CloudTrail observations.
CloudTrail records, when collected separately, are real event observations;
they are not present in this report and would be candidate temporal evidence,
not causal proof on their own.

The separate `Synthetic demo artifacts` GitHub Actions workflow runs on Ubuntu
when manually dispatched or when relevant source files are pushed to `main`.
It uploads `policy_demo.json` and `index.html` as a downloadable workflow
artifact. The workflow uses no AWS credentials or services.

## Presentation flow

1. Show the persistent cost excursion against the past-only seasonal Ridge
   expectation. Explain that the detector requires absolute, relative, and
   persistence gates; this does not assign a cause.
2. Show the separate controlled SCM illustration. Excess replicas are injected
   into the fixture's assumed data-generating process; explain the model's
   counterfactual value function, allocation, and identification assumptions.
   This is a methodological illustration, not evidence that a real-world
   causal effect is identified. It is separate from the cost-spike fixture and
   does not claim to explain that spike.
3. Show A1 idle-resource evidence. Low CPU is paired with memory telemetry,
   request and network quietness, billable-active state and a historical
   seasonal check. A proposed stop still requires dependency, schedule,
   ownership and job checks plus human approval.
4. Show A2 rightsizing. The fixture uses seven days, P99 CPU/memory, SLO checks
   and an explicitly versioned same-family price/spec catalog.
5. Show A3 scaling. P99 request demand is compared with a validated fixture
   capacity per replica, headroom, observed replica count and SLOs. Savings are
   only estimated because this scenario explicitly models billable capacity
   release.
6. Show fleet overlap handling and risk/evidence ranking. The resulting sum is
   an estimate under the synthetic assumptions; overlapping recommendations
   are not added twice when they share a declared capacity group.
7. Point to `ActionWorkflow` tests for allowlisted approval, idempotency,
   dry-run, audit and simulated verification. There is no provider write path.

## What the demo does not establish

The demo is a software walkthrough, not the evaluation plan. Thresholds need
held-out validation; causal attribution needs an identified design or
controlled confounder experiments; costs need provider-verified prices and
billing rules; and savings require post-change billing and SLO observations.
The current Streamlit page remains a scaffold, and the RCA engine does not yet
wire M2/M3 into a complete incident workflow.
