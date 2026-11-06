"""Evidence-gated recommendations for VM rightsizing and excess scaling.

These functions produce plans only. They do not call cloud or Kubernetes APIs.
All prices and capacity limits must come from caller-supplied, versioned inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

import numpy as np
import pandas as pd

from cloudrca.config import load


@dataclass(frozen=True)
class RightsizingPolicy:
    observation_days: int = 7
    cpu_quantile: float = 0.99
    memory_quantile: float = 0.99
    latency_quantile: float = 0.95
    error_quantile: float = 0.95
    target_cpu_utilization: float = 0.80
    memory_headroom: float = 0.20
    monthly_hours: float = 730.0

    @classmethod
    def from_config(cls, config: dict | None = None) -> "RightsizingPolicy":
        cfg = config if config is not None else load("configs/alerts.yaml")
        return cls(**cfg.get("rightsizing_vm", {}))


@dataclass(frozen=True)
class ScalingPolicy:
    observation_days: int = 7
    demand_quantile: float = 0.99
    replica_headroom: float = 0.25
    latency_quantile: float = 0.95
    error_quantile: float = 0.95

    @classmethod
    def from_config(cls, config: dict | None = None) -> "ScalingPolicy":
        cfg = config if config is not None else load("configs/alerts.yaml")
        return cls(**cfg.get("unnecessary_scaling", {}))


def _validated_window(telemetry: pd.DataFrame, days: int, columns: set[str]) -> pd.DataFrame:
    if not isinstance(telemetry, pd.DataFrame) or not isinstance(telemetry.index, pd.DatetimeIndex):
        raise TypeError("telemetry must be a DataFrame with a DatetimeIndex")
    if telemetry.index.has_duplicates or not telemetry.index.is_monotonic_increasing:
        raise ValueError("telemetry timestamps must be unique and increasing")
    missing = columns - set(telemetry.columns)
    if missing:
        raise ValueError(f"telemetry missing required columns: {sorted(missing)}")
    if len(telemetry) < 2 or (telemetry.index[-1] - telemetry.index[0]) < pd.Timedelta(days=days):
        raise ValueError(f"at least {days} days of telemetry are required")
    intervals = np.diff(telemetry.index.asi8)
    if len(intervals) and np.any(intervals != intervals[0]):
        raise ValueError("telemetry timestamps must use a regular interval")
    return telemetry.apply(pd.to_numeric, errors="coerce")


def _catalog_row(catalog: list[dict], sku: str) -> dict | None:
    rows = [row for row in catalog if row.get("instance_type") == sku]
    if len(rows) > 1:
        raise ValueError(f"catalog has duplicate instance_type {sku!r}")
    return rows[0] if rows else None


def recommend_rightsize(
    resource_id: str,
    telemetry: pd.DataFrame,
    *,
    current_instance: str,
    catalog: list[dict],
    catalog_version: str,
    currency: str,
    latency_slo_ms: float,
    error_slo_pct: float,
    transition_cost: float = 0.0,
    required_network_gbps: float | None = None,
    required_storage_gb: float | None = None,
    policy: RightsizingPolicy | None = None,
) -> dict[str, Any]:
    """Recommend a cheaper compatible VM when seven-day demand and SLOs allow.

    Required telemetry: CPU percent, memory working set in GiB, bucket P95
    latency in ms, and bucket error rate in percent. CPU demand is converted to
    cores from the current VM's vCPU capacity. The proposal retains compatible
    family, region, architecture, and CPU-credit model. Caller-supplied catalog
    prices must share a currency and price basis, and must be versioned.
    """
    policy = policy or RightsizingPolicy.from_config()
    if not resource_id or not catalog_version or not currency:
        raise ValueError("resource_id, catalog_version, and currency are required")
    if not 0 < policy.target_cpu_utilization <= 1 or not 0 <= policy.memory_headroom < 5:
        raise ValueError("rightsizing capacity policy is invalid")
    if transition_cost < 0:
        raise ValueError("transition_cost must be non-negative")
    if not 0 < policy.cpu_quantile <= 1 or not 0 < policy.memory_quantile <= 1:
        raise ValueError("CPU and memory quantiles must be in (0, 1]")
    if not 0 < policy.latency_quantile <= 1 or not 0 < policy.error_quantile <= 1:
        raise ValueError("SLO quantiles must be in (0, 1]")
    if not np.isfinite(latency_slo_ms) or latency_slo_ms <= 0 or not 0 <= error_slo_pct <= 100:
        raise ValueError("latency and error SLO thresholds are invalid")
    required_columns = {"cpu_pct", "memory_working_set_gb", "p95_latency_ms", "error_rate_pct"}
    data = _validated_window(telemetry, policy.observation_days, required_columns)
    current = _catalog_row(catalog, current_instance)
    if current is None:
        raise ValueError(f"current instance {current_instance!r} is absent from the price/spec catalog")
    for field in ("vcpu", "memory_gb", "hourly_price", "price_unit", "currency",
                  "family", "region", "architecture"):
        if field not in current:
            raise ValueError(f"current catalog row missing {field!r}")
    if current["price_unit"] != "instance_hour" or current["currency"] != currency:
        raise ValueError("catalog price must be in the requested currency per instance-hour")
    skus = [row.get("instance_type") for row in catalog]
    if len(skus) != len(set(skus)):
        raise ValueError("catalog instance_type values must be unique")
    if any(not np.isfinite(float(current[k])) or float(current[k]) <= 0
           for k in ("vcpu", "memory_gb", "hourly_price")):
        raise ValueError("current catalog capacities and hourly price must be positive and finite")
    for col in required_columns:
        if data[col].notna().mean() < 0.95:
            raise ValueError(f"telemetry column {col!r} has less than 95% coverage")

    cpu_p99 = float(data["cpu_pct"].quantile(policy.cpu_quantile))
    memory_p99 = float(data["memory_working_set_gb"].quantile(policy.memory_quantile))
    latency_p95 = float(data["p95_latency_ms"].quantile(policy.latency_quantile))
    error_p95 = float(data["error_rate_pct"].quantile(policy.error_quantile))
    if ((data["cpu_pct"].dropna() < 0).any() or (data["cpu_pct"].dropna() > 100).any()
            or (data["memory_working_set_gb"].dropna() < 0).any()
            or cpu_p99 > 100 or memory_p99 > float(current["memory_gb"])):
        raise ValueError("CPU/memory telemetry is outside the declared current VM capacity")
    slo_pass = latency_p95 <= latency_slo_ms and error_p95 <= error_slo_pct
    required_vcpu = (cpu_p99 / 100.0 * float(current["vcpu"])) / policy.target_cpu_utilization
    required_memory = memory_p99 * (1 + policy.memory_headroom)
    compatible = []
    for row in catalog:
        if row.get("instance_type") == current_instance:
            continue
        same_profile = all(row.get(k) == current.get(k) for k in ("family", "region", "architecture"))
        same_credit_model = row.get("cpu_credit_model") == current.get("cpu_credit_model")
        if not same_profile or not same_credit_model:
            continue
        if any(k not in row for k in ("vcpu", "memory_gb", "hourly_price")):
            continue
        if row.get("price_unit") != "instance_hour" or row.get("currency") != currency:
            continue
        capacities = (float(row["vcpu"]), float(row["memory_gb"]), float(row["hourly_price"]))
        if not all(np.isfinite(v) and v > 0 for v in capacities):
            continue
        if capacities[0] < required_vcpu or capacities[1] < required_memory:
            continue
        if required_network_gbps is not None and float(row.get("network_gbps", 0)) < required_network_gbps:
            continue
        if required_storage_gb is not None and float(row.get("storage_gb", 0)) < required_storage_gb:
            continue
        if capacities[2] < float(current["hourly_price"]):
            compatible.append(row)

    proposed = min(compatible, key=lambda row: float(row["hourly_price"])) if compatible else None
    candidate = bool(slo_pass and proposed is not None)
    gross_monthly = None
    net_first_month = None
    if candidate and proposed is not None:
        gross_monthly = (float(current["hourly_price"]) - float(proposed["hourly_price"])) * policy.monthly_hours
        net_first_month = gross_monthly - transition_cost
    reasons = []
    if not slo_pass:
        reasons.append("observed latency or error rate exceeds the configured SLO")
    if proposed is None:
        reasons.append("no cheaper same-profile catalog option meets the modeled capacity floor")
    return {
        "alert_type": "overprovisioned_vm",
        "resource_id": resource_id,
        "candidate": candidate,
        "current_instance": current_instance,
        "proposed_instance": proposed.get("instance_type") if proposed else None,
        "catalog_version": catalog_version,
        "currency": currency,
        "evidence": {
            "observation_days": policy.observation_days,
            "cpu_p99_pct": cpu_p99,
            "memory_working_set_p99_gb": memory_p99,
            "required_vcpu_with_target_utilization": required_vcpu,
            "required_memory_gb_with_headroom": required_memory,
            "observed_p95_latency_ms": latency_p95,
            "observed_p95_error_rate_pct": error_p95,
            "latency_slo_ms": latency_slo_ms,
            "error_slo_pct": error_slo_pct,
            "slo_pass": slo_pass,
        },
        "confidence": None,
        "confidence_status": "uncalibrated; capacity and SLO rules",
        "estimated_savings": {
            "gross_monthly": gross_monthly,
            "transition_cost_once": transition_cost,
            "net_first_month": net_first_month,
            "currency": currency if proposed else None,
            "basis": "catalog hourly VM price difference × configured 730-hour month",
            "verified": False,
        },
        "recommended_action": (
            f"Review resize from {current_instance} to {proposed['instance_type']} in an approved maintenance window."
            if candidate else "No rightsizing action recommended."
        ),
        "safety": {
            "approval_required": True,
            "execution_mode": "dry_run",
            "preconditions": ["validate workload and instance-family support", "check regional availability",
                              "confirm restart/maintenance impact", "preserve prior instance for rollback"],
            "verification_conditions": ["latency and error SLOs hold after resize", "memory pressure remains safe",
                                         "billable VM charge decreases by modeled amount"],
            "rollback": f"Resize back to {current_instance} if SLO or health checks fail.",
        },
        "reasons_not_recommended": reasons,
    }


def recommend_scaling_policy(
    service_id: str,
    telemetry: pd.DataFrame,
    *,
    minimum_replicas: int,
    safe_rps_per_replica: float,
    capacity_model_version: str,
    capacity_model_validated: bool,
    scaling_configuration: dict | None,
    scaling_events: list[dict] | None,
    resource_requests: dict | None,
    latency_slo_ms: float,
    error_slo_pct: float,
    reduces_billable_capacity: bool,
    marginal_billable_rate_per_replica_hour: float | None = None,
    currency: str = "INR",
    policy: ScalingPolicy | None = None,
) -> dict[str, Any]:
    """Compare observed replicas with a validated SLO-safe demand counterfactual.

    Required telemetry includes requests/second, actual replicas, CPU and
    memory, bucket P95 latency, and bucket error rate for at least seven days.
    HPA configuration, collected scaling events, and resource requests must be
    supplied. The capacity input must come from a versioned load test or
    controlled capacity study. Savings require released billable capacity.
    """
    policy = policy or ScalingPolicy.from_config()
    if not service_id or not capacity_model_version:
        raise ValueError("service_id and capacity_model_version are required")
    if minimum_replicas < 1 or not np.isfinite(safe_rps_per_replica) or safe_rps_per_replica <= 0:
        raise ValueError("minimum_replicas and safe_rps_per_replica must be positive")
    if not 0 < policy.demand_quantile <= 1 or not 0 < policy.latency_quantile <= 1 or not 0 < policy.error_quantile <= 1:
        raise ValueError("demand and SLO quantiles must be in (0, 1]")
    if policy.replica_headroom < 0 or not np.isfinite(policy.replica_headroom):
        raise ValueError("replica_headroom must be finite and non-negative")
    if not np.isfinite(latency_slo_ms) or latency_slo_ms <= 0 or not 0 <= error_slo_pct <= 100:
        raise ValueError("latency and error SLO thresholds are invalid")
    if marginal_billable_rate_per_replica_hour is not None and (
        not np.isfinite(marginal_billable_rate_per_replica_hour)
        or marginal_billable_rate_per_replica_hour < 0
    ):
        raise ValueError("marginal billable rate must be finite and non-negative")
    required = {"requests_per_second", "replicas", "cpu_pct", "memory_pct",
                "p95_latency_ms", "error_rate_pct"}
    data = _validated_window(telemetry, policy.observation_days, required)
    if any(data[c].notna().mean() < 0.95 for c in required):
        raise ValueError("scaling telemetry must have at least 95% coverage")
    if (data["requests_per_second"] < 0).any() or (data["replicas"] < 1).any():
        raise ValueError("request rate must be non-negative and replica count at least one")
    if ((data["p95_latency_ms"].dropna() < 0).any()
            or (data["error_rate_pct"].dropna() < 0).any()
            or (data["error_rate_pct"].dropna() > 100).any()):
        raise ValueError("latency/error telemetry is outside valid units")
    if ((data["cpu_pct"].dropna() < 0).any() or (data["cpu_pct"].dropna() > 100).any()
            or (data["memory_pct"].dropna() < 0).any()
            or (data["memory_pct"].dropna() > 100).any()):
        raise ValueError("CPU and memory utilization must be between 0 and 100 percent")
    demand_p99 = float(data["requests_per_second"].quantile(policy.demand_quantile))
    observed_replicas_p95 = int(ceil(float(data["replicas"].quantile(0.95))))
    safe_replicas = max(minimum_replicas,
                        int(ceil(demand_p99 * (1 + policy.replica_headroom) / safe_rps_per_replica)))
    latency_p95 = float(data["p95_latency_ms"].quantile(policy.latency_quantile))
    error_p95 = float(data["error_rate_pct"].quantile(policy.error_quantile))
    slo_pass = latency_p95 <= latency_slo_ms and error_p95 <= error_slo_pct
    config_valid = (isinstance(scaling_configuration, dict)
                    and {"min_replicas", "max_replicas", "target_cpu_utilization_pct"}
                    <= set(scaling_configuration))
    if config_valid:
        try:
            cfg_min = int(scaling_configuration["min_replicas"])
            cfg_max = int(scaling_configuration["max_replicas"])
            cfg_target = float(scaling_configuration["target_cpu_utilization_pct"])
            config_valid = cfg_min >= 1 and cfg_max >= cfg_min and 0 < cfg_target <= 100
        except (TypeError, ValueError):
            config_valid = False
    requests_valid = (isinstance(resource_requests, dict)
                      and {"cpu_request_cores", "memory_request_gb", "cpu_limit_cores",
                           "memory_limit_gb"} <= set(resource_requests))
    if requests_valid:
        try:
            requests_valid = all(np.isfinite(float(resource_requests[k])) and float(resource_requests[k]) > 0
                                 for k in ("cpu_request_cores", "memory_request_gb",
                                           "cpu_limit_cores", "memory_limit_gb"))
        except (TypeError, ValueError):
            requests_valid = False
    events_collected = scaling_events is not None
    model_valid = capacity_model_validated is True and config_valid and requests_valid and events_collected
    candidate = bool(model_valid and slo_pass and observed_replicas_p95 > safe_replicas)
    replicas_reducible = max(observed_replicas_p95 - safe_replicas, 0)
    monthly_savings = None
    if candidate and reduces_billable_capacity and marginal_billable_rate_per_replica_hour is not None:
        monthly_savings = (replicas_reducible * marginal_billable_rate_per_replica_hour * 730.0)
    reasons = []
    if not model_valid:
        reasons.append("capacity test, scaling configuration/events, or resource requests are missing/unvalidated")
    if not slo_pass:
        reasons.append("observed latency or error rate exceeds the configured SLO")
    if observed_replicas_p95 <= safe_replicas:
        reasons.append("observed replica count is within modeled safe capacity")
    if not reduces_billable_capacity:
        reasons.append("replica reduction does not release billable infrastructure capacity")
    return {
        "alert_type": "unnecessary_resource_scaling",
        "service_id": service_id,
        "candidate": candidate,
        "current_replicas_p95": observed_replicas_p95,
        "modeled_safe_replicas": safe_replicas,
        "capacity_model_version": capacity_model_version,
        "evidence": {
            "observation_days": policy.observation_days,
            "requests_per_second_p99": demand_p99,
            "validated_safe_rps_per_replica": float(safe_rps_per_replica),
            "replica_headroom": float(policy.replica_headroom),
            "observed_p95_latency_ms": latency_p95,
            "observed_p95_error_rate_pct": error_p95,
            "latency_slo_ms": latency_slo_ms,
            "error_slo_pct": error_slo_pct,
            "slo_pass": slo_pass,
            "capacity_model_validated": capacity_model_validated is True,
            "required_evidence_complete": model_valid,
            "scaling_configuration": scaling_configuration,
            "scaling_events_collected": events_collected,
            "scaling_event_count_in_window": len(scaling_events) if scaling_events is not None else None,
            "resource_requests_and_limits": resource_requests,
            "reduces_billable_capacity": bool(reduces_billable_capacity),
        },
        "confidence": None,
        "confidence_status": "uncalibrated; deterministic capacity comparison",
        "estimated_savings": {
            "gross_monthly": monthly_savings,
            "currency": currency if monthly_savings is not None else None,
            "basis": "replicas released × marginal billable rate × 730 hours",
            "verified": False,
        },
        "recommended_action": (
            f"Review scaling limits and target capacity; modeled safe floor is {safe_replicas} replicas."
            if candidate else "No scaling-policy change recommended."
        ),
        "safety": {
            "approval_required": True,
            "execution_mode": "dry_run",
            "do_not_scale_below": max(minimum_replicas, safe_replicas),
            "preconditions": ["review HPA min/max and resource requests", "confirm capacity model matches workload",
                              "apply during an approved change window"],
            "verification_conditions": ["latency and error SLOs hold", "replica count remains stable",
                                         "billable capacity is actually released"],
            "rollback": "Restore the previous HPA limits or replica count if SLOs degrade.",
        },
        "reasons_not_recommended": reasons,
    }
