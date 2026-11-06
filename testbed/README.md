# Testbed (Online Boutique on minikube/kind)

Plan §2.3. Order of work:
1. `k8s/`: Online Boutique manifests + kube-prometheus-stack (5s scrape) + loadgenerator tuning.
2. `faults/`: one patch per fault F1–F8 (see docs/technical_plan.md §2.3). Each must be applied by `run_case.sh`
   so the change timestamp is recorded exactly.
3. `run_case.sh <fault_id> <service> <repeat>`: warm-up 10m → baseline 10m → apply change (+ write change_events)
   → run 10m → rollback → cool-down 5m.
4. `collect.py`: export Prometheus range queries + logs (+ traces) to the RCAEval-like layout.

Target: 8 fault types × 3 services × 5 repeats ≈ 120 cases (adjust for feasibility). Label every case with
`root_cause_service`, `root_cause_change_id`, `fault_type`, `t_change`, `t_anomaly`.
