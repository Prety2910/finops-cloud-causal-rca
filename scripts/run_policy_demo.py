#!/usr/bin/env python3
"""Run a deterministic, synthetic end-to-end demo of the three FinOps alerts.

All measurements and prices in this script are constructed fixtures. They are
for a reproducible presentation walkthrough, not research results or provider
billing observations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import networkx as nx

from cloudrca.detect.cost_spike import analyze_cost_series
from cloudrca.detect.fleet import rank_fleet_opportunities
from cloudrca.detect.idle_resource import IdleResourcePolicy, assess_idle_resource
from cloudrca.detect.optimization import recommend_rightsize, recommend_scaling_policy
from cloudrca.rca.m3_cost import LinearSCM, attribute_cost


def build_demo(seed: int = 17) -> dict:
    rng = np.random.default_rng(seed)
    result: dict = {
        "provenance": "synthetic_demo_only",
        "seed": seed,
        "data_sources": {
            "cloudtrail": {
                "status": "not_used",
                "observations_included": 0,
                "note": "This demo makes no AWS calls and contains no CloudTrail observations.",
            },
            "cost": "Synthetic fixture values; not observed bills or charges.",
            "utilization": "Synthetic fixture telemetry; not observed cloud metrics.",
            "causal_attribution": (
                "Controlled synthetic SCM illustration under injected assumptions; "
                "not evidence that a real-world causal effect is identified."
            ),
        },
    }

    # Cost series: seven training days with daily seasonality, then a persistent
    # modeled increase. This exercises expected-cost forecasting and alerting.
    cost_index = pd.date_range("2026-01-01", periods=24 * 10, freq="h", tz="UTC")
    values = 20 + 3 * np.sin(2 * np.pi * cost_index.hour.to_numpy() / 24)
    cutoff = cost_index[24 * 7]
    values[24 * 7:] += 12
    cost_result = analyze_cost_series(
        pd.Series(values, index=cost_index), train_end=cutoff,
        min_excess_per_period=5, min_increase_pct=15, persistence=6,
        min_train_samples=48, provenance="simulated",
    )
    result["cost_spike"] = {
        "method": cost_result["method"],
        "alert_count": len(cost_result["alerts"]),
        "alerts": [alert.to_dict() for alert in cost_result["alerts"]],
    }

    # Separate controlled structural example: injected excess replicas drive
    # per-window compute spend. Kept separate from the cost-spike output so no
    # causal link is implied between those independent fixtures.
    cause_pre = rng.uniform(0.0, 1.0, 300)
    cause_post = rng.uniform(3.0, 4.0, 100)
    causal_pre = pd.DataFrame({"excess_replicas": cause_pre,
        "compute_cost": 5.0 + 8.0 * cause_pre + rng.normal(0, 0.08, len(cause_pre))})
    causal_post = pd.DataFrame({"excess_replicas": cause_post,
        "compute_cost": 5.0 + 8.0 * cause_post + rng.normal(0, 0.08, len(cause_post))})
    causal_model = LinearSCM(nx.DiGraph([("excess_replicas", "compute_cost")])).fit(causal_pre)
    causal_result = attribute_cost(causal_model, causal_pre, causal_post,
                                   ["excess_replicas"], cost_node="compute_cost")
    result["controlled_cost_attribution"] = {
        **causal_result,
        "cost_unit": "USD per observation bucket (synthetic fixture)",
        "injected_cause": "excess replicas",
        "separate_from_cost_spike_scenario": True,
    }

    # Idle resource: 14 days of workload-like behavior followed by a quiet day.
    idx = pd.date_range("2026-02-01", periods=24 * 15, freq="h", tz="UTC")
    cpu = 15 + 5 * np.sin(2 * np.pi * idx.hour.to_numpy() / 24)
    cpu[-24:] = 2.0
    requests, network = np.ones(len(idx)), np.full(len(idx), 0.5)
    requests[-24:], network[-24:] = 0.0, 0.0
    idle_telemetry = pd.DataFrame({"cpu_pct": cpu, "memory_pct": 42.0,
                                   "requests_per_second": requests, "network_mbps": network}, index=idx)
    result["idle_resource"] = assess_idle_resource(
        "demo-vm-idle", idle_telemetry, billable_active=True,
        hourly_compute_rate=0.25, currency="USD", business_critical=False,
        scheduled_active=False, active_jobs=False, dependencies_clear=True,
        owner="demo-team", policy=IdleResourcePolicy(minimum_history_samples=48),
    )

    # Rightsizing: week-long low demand and a fictional versioned same-family
    # catalog. Costs are explicitly fixture prices in USD per instance-hour.
    idx7 = pd.date_range("2026-03-01", periods=24 * 7 + 1, freq="h", tz="UTC")
    vm = pd.DataFrame({"cpu_pct": 25.0, "memory_working_set_gb": 5.0,
                       "p95_latency_ms": 55.0, "error_rate_pct": 0.1}, index=idx7)
    catalog = [
        {"instance_type": "demo-c8", "vcpu": 8, "memory_gb": 32, "hourly_price": 1.6,
         "price_unit": "instance_hour", "currency": "USD", "family": "general",
         "region": "demo-region", "architecture": "x86", "cpu_credit_model": None},
        {"instance_type": "demo-c4", "vcpu": 4, "memory_gb": 16, "hourly_price": 0.8,
         "price_unit": "instance_hour", "currency": "USD", "family": "general",
         "region": "demo-region", "architecture": "x86", "cpu_credit_model": None},
    ]
    result["rightsizing"] = recommend_rightsize(
        "demo-vm-rightsize", vm, current_instance="demo-c8", catalog=catalog,
        catalog_version="synthetic-fixture-v1", currency="USD",
        latency_slo_ms=100, error_slo_pct=1,
    )

    # Scaling: stable request demand, excessive configured replicas, validated
    # synthetic load-test capacity, and an explicit billable release condition.
    scale = pd.DataFrame({"requests_per_second": 100.0, "replicas": 10,
                          "cpu_pct": 35.0, "memory_pct": 40.0,
                          "p95_latency_ms": 60.0, "error_rate_pct": 0.1}, index=idx7)
    result["scaling"] = recommend_scaling_policy(
        "demo-service", scale, minimum_replicas=2, safe_rps_per_replica=20,
        capacity_model_version="synthetic-load-fixture-v1", capacity_model_validated=True,
        scaling_configuration={"min_replicas": 2, "max_replicas": 12,
                               "target_cpu_utilization_pct": 70},
        scaling_events=[], resource_requests={"cpu_request_cores": 1,
            "memory_request_gb": 2, "cpu_limit_cores": 2, "memory_limit_gb": 4},
        latency_slo_ms=100, error_slo_pct=1, reduces_billable_capacity=True,
        marginal_billable_rate_per_replica_hour=0.2, currency="USD",
    )

    opportunities = []
    for key, alert_type, resource in (
        ("rightsizing", "overprovisioned_vm", "demo-vm-rightsize"),
        ("scaling", "unnecessary_scaling", "demo-service"),
    ):
        rec = result[key]
        savings = rec["estimated_savings"].get("gross_monthly")
        if savings is not None and savings > 0:
            opportunities.append({"resource_id": resource, "alert_type": alert_type,
                "estimated_monthly_savings": savings, "evidence_score": 0.8,
                "operational_risk": 0.25, "overlap_group": resource})
    result["fleet_ranking"] = rank_fleet_opportunities(opportunities, currency="USD")
    result["interpretation"] = (
        "All data and prices here are deterministic synthetic fixtures. Alert and savings outputs "
        "exercise policy logic only; they are not calibrated probabilities, established causal effects, cloud bills, "
        "executed actions, or verified savings."
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path, default=Path("results/demo/policy_demo.json"))
    args = parser.parse_args()
    report = build_demo(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Wrote synthetic demo report: {args.output}")
    print(f"Cost spike alerts: {report['cost_spike']['alert_count']}")
    print(f"A1 idle candidate: {report['idle_resource']['candidate']}")
    print(f"A2 rightsizing candidate: {report['rightsizing']['candidate']}")
    print(f"A3 scaling candidate: {report['scaling']['candidate']}")
    print("Fleet estimated monthly savings (synthetic USD): "
          f"{report['fleet_ranking']['estimated_monthly_savings_after_overlap']:.2f}")


if __name__ == "__main__":
    main()
