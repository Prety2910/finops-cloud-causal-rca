"""Evidence and safety assessment for suspected idle billable compute."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from cloudrca.config import load
from cloudrca.detect.cost_baseline import seasonal_ridge_predict_with_residuals


@dataclass(frozen=True)
class IdleResourcePolicy:
    observation_window_hours: float = 24.0
    cpu_floor_pct: float = 5.0
    minimum_idle_ratio: float = 0.80
    request_rps_max: float = 0.01
    network_mbps_max: float = 0.01
    minimum_seasonal_drop_pp: float = 2.0
    mad_scale_factor: float = 1.4826
    minimum_negative_z: float = 1.5
    cusum_drift: float = 0.25
    cusum_threshold: float = 5.0
    minimum_window_samples: int = 12
    minimum_history_samples: int = 48

    @classmethod
    def from_config(cls, config: dict | None = None) -> "IdleResourcePolicy":
        """Load configured A1 policy values, rejecting unknown keys."""
        cfg = config if config is not None else load("configs/alerts.yaml")
        values = cfg.get("idle_resource", cfg)
        return cls(**values)


def assess_idle_resource(
    resource_id: str,
    telemetry: pd.DataFrame,
    *,
    billable_active: bool | None,
    hourly_compute_rate: float | None = None,
    currency: str = "INR",
    business_critical: bool | None = None,
    scheduled_active: bool | None = None,
    active_jobs: bool | None = None,
    dependencies_clear: bool | None = None,
    owner: str | None = None,
    policy: IdleResourcePolicy | None = None,
) -> dict[str, Any]:
    """Assess one resource for an idle candidate and guarded stop suggestion.

    Required telemetry columns are ``cpu_pct`` and ``memory_pct`` plus at
    least one of ``requests_per_second`` or ``network_mbps``. Thus low CPU by
    itself cannot raise this alert. The most recent observation window is
    compared with a seasonal Ridge baseline fitted only on earlier samples
    when enough history is available; short-history fallback still requires
    all the rule-based evidence above.

    Cost impact is a modeled upper bound on billable spend during the observed
    idle portion of the window. It is not a verified saving or a causal effect.
    The function never executes a cloud action; stopping always requires human
    approval and explicit safe-to-propose checks.
    """
    policy = policy or IdleResourcePolicy.from_config()
    if not resource_id:
        raise ValueError("resource_id is required")
    if not isinstance(telemetry.index, pd.DatetimeIndex):
        raise TypeError("telemetry must use a DatetimeIndex")
    if telemetry.index.has_duplicates or not telemetry.index.is_monotonic_increasing:
        raise ValueError("telemetry timestamps must be unique and increasing")
    intervals = np.diff(telemetry.index.asi8)
    if len(intervals) and np.any(intervals != intervals[0]):
        raise ValueError("telemetry timestamps must use a regular interval")
    required = {"cpu_pct", "memory_pct"}
    missing = required - set(telemetry.columns)
    if missing:
        raise ValueError(f"telemetry missing required columns: {sorted(missing)}")
    activity_cols = [c for c in ("requests_per_second", "network_mbps") if c in telemetry]
    if not activity_cols:
        raise ValueError("at least one workload signal is required: requests_per_second or network_mbps")
    if policy.observation_window_hours <= 0 or not 0 < policy.minimum_idle_ratio <= 1:
        raise ValueError("observation window and idle ratio policy are invalid")
    if policy.minimum_window_samples < 1 or policy.minimum_history_samples < 2:
        raise ValueError("sample requirements are invalid")
    if hourly_compute_rate is not None and (not np.isfinite(hourly_compute_rate) or hourly_compute_rate < 0):
        raise ValueError("hourly_compute_rate must be finite and non-negative")

    numeric = telemetry.apply(pd.to_numeric, errors="coerce")
    end = telemetry.index[-1] if len(telemetry) else None
    if end is None:
        raise ValueError("telemetry is empty")
    start = end - pd.Timedelta(hours=policy.observation_window_hours)
    # Keep exactly the buckets ending in (end - window, end], avoiding an
    # extra endpoint bucket on inclusive hourly indices.
    window = numeric.loc[numeric.index > start]
    if len(window) < policy.minimum_window_samples:
        raise ValueError("not enough telemetry samples in the observation window")
    cpu = window["cpu_pct"].to_numpy(dtype=float)
    mem = window["memory_pct"].to_numpy(dtype=float)
    finite_cpu = np.isfinite(cpu)
    finite_mem = np.isfinite(mem)
    if finite_cpu.mean() < policy.minimum_idle_ratio or finite_mem.mean() < policy.minimum_idle_ratio:
        raise ValueError("CPU and memory telemetry must cover the observation window")
    if np.any((cpu[finite_cpu] < 0) | (cpu[finite_cpu] > 100)):
        raise ValueError("cpu_pct values must be between 0 and 100")
    if np.any((mem[finite_mem] < 0) | (mem[finite_mem] > 100)):
        raise ValueError("memory_pct values must be between 0 and 100")

    cpu_idle = finite_cpu & (cpu < policy.cpu_floor_pct)
    cpu_idle_ratio = float(cpu_idle.sum() / finite_cpu.sum())
    workload_ratios: dict[str, float] = {}
    for col in activity_cols:
        vals = window[col].to_numpy(dtype=float)
        finite = np.isfinite(vals)
        if finite.mean() < policy.minimum_idle_ratio:
            raise ValueError(f"{col} telemetry does not cover the observation window")
        if np.any(vals[finite] < 0):
            raise ValueError(f"{col} values must be non-negative")
        limit = policy.request_rps_max if col == "requests_per_second" else policy.network_mbps_max
        workload_ratios[col] = float((finite & (vals <= limit)).sum() / finite.sum())
    workload_quiet = all(ratio >= policy.minimum_idle_ratio for ratio in workload_ratios.values())

    history = numeric.loc[numeric.index < start, "cpu_pct"]
    history = history[np.isfinite(history.to_numpy(dtype=float))]
    expected_cpu = None
    seasonal_drop_pp = None
    seasonal_used = False
    median_residual_z = None
    negative_cusum_max = None
    drift_confirmed = False
    if len(history) >= policy.minimum_history_samples:
        full_cpu = numeric["cpu_pct"]
        try:
            expected, training_residuals = seasonal_ridge_predict_with_residuals(
                full_cpu, predict_from=start, min_train_samples=policy.minimum_history_samples,
                output_name="expected_cpu_pct",
            )
            expected_cpu = expected.loc[window.index]
            pairs = np.isfinite(expected_cpu.to_numpy(dtype=float)) & finite_cpu
            if pairs.mean() >= policy.minimum_idle_ratio:
                seasonal_drop_pp = float(np.median(expected_cpu.to_numpy(dtype=float)[pairs]
                                                   - cpu[pairs]))
                seasonal_used = True
                residual_values = training_residuals.to_numpy(dtype=float)
                residual_center = float(np.median(residual_values))
                residual_mad = float(np.median(np.abs(residual_values - residual_center)))
                scale = max(policy.mad_scale_factor * residual_mad, 0.1)
                z = (cpu[pairs] - expected_cpu.to_numpy(dtype=float)[pairs]) / scale
                median_residual_z = float(np.median(z))
                cusum = 0.0
                cusum_max = 0.0
                for value in z:
                    cusum = max(0.0, cusum - float(value) - policy.cusum_drift)
                    cusum_max = max(cusum_max, cusum)
                negative_cusum_max = float(cusum_max)
                drift_confirmed = (median_residual_z <= -policy.minimum_negative_z
                                   or negative_cusum_max >= policy.cusum_threshold)
        except ValueError:
            # Fall back to the explicitly reported short-history rule path.
            pass

    seasonal_drop_ok = (not seasonal_used or (
        seasonal_drop_pp is not None
        and seasonal_drop_pp >= policy.minimum_seasonal_drop_pp
        and drift_confirmed
    ))
    is_candidate = bool(
        billable_active is True
        and cpu_idle_ratio >= policy.minimum_idle_ratio
        and workload_quiet
        and seasonal_drop_ok
    )

    checks = {
        "billable_active": billable_active is True,
        "not_business_critical": business_critical is False,
        "not_scheduled_active": scheduled_active is False,
        "no_active_jobs": active_jobs is False,
        "dependencies_clear": dependencies_clear is True,
        "owner_known": bool(owner and owner.strip()),
    }
    safe_to_propose_stop = all(checks.values())
    seconds_per_bucket = float((telemetry.index[1] - telemetry.index[0]).total_seconds()) if len(intervals) else 0.0
    observed_idle_hours = cpu_idle.sum() * seconds_per_bucket / 3600.0
    cost_estimate = None
    if hourly_compute_rate is not None and billable_active is True:
        cost_estimate = float(observed_idle_hours * hourly_compute_rate)

    reasons = []
    if billable_active is not True:
        reasons.append("billable active state is absent or unknown")
    if cpu_idle_ratio < policy.minimum_idle_ratio:
        reasons.append("CPU idle ratio is below policy threshold")
    if not workload_quiet:
        reasons.append("request or network activity is not consistently quiet")
    if seasonal_used and not seasonal_drop_ok:
        reasons.append("CPU is not sufficiently below its seasonal baseline")
    if not activity_cols:
        reasons.append("no workload activity signal")
    return {
        "alert_type": "idle_zombie_compute",
        "resource_id": resource_id,
        "candidate": is_candidate,
        "severity": "medium" if is_candidate else "none",
        "detection_confidence": None,
        "confidence_status": "uncalibrated; rule evidence only",
        "causal_verification": {
            "status": "not_run",
            "confidence": None,
            "reason": "No validated causal graph or intervention estimate is available in this detector.",
        },
        "evidence": {
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "observation_window_hours": float(policy.observation_window_hours),
            "cpu_floor_pct": float(policy.cpu_floor_pct),
            "cpu_idle_ratio": cpu_idle_ratio,
            "cpu_median_pct": float(np.nanmedian(cpu)),
            "memory_median_pct": float(np.nanmedian(mem)),
            "memory_p95_pct": float(np.nanpercentile(mem, 95)),
            "workload_quiet_ratios": workload_ratios,
            "seasonal_baseline_used": seasonal_used,
            "seasonal_cpu_drop_percentage_points": seasonal_drop_pp,
            "median_standardized_cpu_residual": median_residual_z,
            "negative_cusum_max": negative_cusum_max,
            "negative_drift_confirmed": drift_confirmed if seasonal_used else None,
        },
        "estimated_cost_impact": {
            "amount": cost_estimate,
            "currency": currency if cost_estimate is not None else None,
            "basis": "upper-bound billable spend during observed CPU-idle buckets; not verified savings",
            "billable_idle_hours": float(observed_idle_hours),
        },
        "recommended_action": (
            "Human review; consider a scheduled stop/deallocation after confirming service health."
            if is_candidate and safe_to_propose_stop else
            "Investigate the listed safety checks before considering a stop or deallocation."
            if is_candidate else "No idle-resource action recommended."
        ),
        "safety": {
            "checks": checks,
            "safe_to_propose_stop": safe_to_propose_stop,
            "approval_required": True,
            "execution_mode": "dry_run",
            "rollback": "Restart or redeploy the resource using its recorded prior configuration.",
            "rollback_triggers": ["service health degrades", "workload fails", "dependent service fails"],
            "verification_conditions": [
                "service health remains within its SLO after the action",
                "requests and scheduled jobs complete successfully",
                "dependencies remain healthy",
                "billable compute charges decrease as modeled",
            ],
        },
        "reasons_not_flagged": reasons,
    }
