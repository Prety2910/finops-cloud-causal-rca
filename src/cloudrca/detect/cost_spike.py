"""Persistent cost-spike detection against an explicit expected-cost series.

Values are per-bucket amounts in the same currency and billing model. This
module does not infer prices or turn utilization metrics into billed cost.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd
from cloudrca.detect.cost_baseline import seasonal_ridge_expected


Provenance = Literal["observed", "simulated", "estimated"]


@dataclass(frozen=True)
class CostSpike:
    start: object
    end: object
    periods: int
    actual_cost: float
    expected_cost: float
    excess_cost: float
    increase_pct: float | None
    provenance: Provenance
    evidence: dict

    def to_dict(self) -> dict:
        return asdict(self)


def detect_cost_spikes(
    actual: pd.Series,
    expected: pd.Series,
    *,
    min_excess_per_period: float,
    min_increase_pct: float = 0.0,
    persistence: int = 3,
    provenance: Provenance = "estimated",
) -> list[CostSpike]:
    """Return consecutive intervals exceeding absolute and relative gates.

    Each input value must represent one period's cost in the same currency.
    A period qualifies when its excess is at least ``min_excess_per_period``
    and, when expected cost is positive, its percentage increase reaches
    ``min_increase_pct``. When expected cost is zero or negative, the absolute
    gate alone is used to avoid division by zero or a misleading percentage.

    ``persistence`` is the minimum number of adjacent qualifying periods.
    Missing/non-finite pairs break an interval. A result's aggregate excess is
    the sum of positive actual-minus-expected differences across that interval.
    This is a threshold detector, not a causal attribution or calibrated
    probability estimate.
    """
    if not isinstance(actual, pd.Series) or not isinstance(expected, pd.Series):
        raise TypeError("actual and expected must be pandas Series")
    if not actual.index.equals(expected.index):
        raise ValueError("actual and expected must have identical indexes")
    if actual.index.has_duplicates or not actual.index.is_monotonic_increasing:
        raise ValueError("cost index must be unique and increasing")
    if min_excess_per_period < 0 or min_increase_pct < 0:
        raise ValueError("cost thresholds must be non-negative")
    if persistence < 1:
        raise ValueError("persistence must be at least one period")
    if provenance not in {"observed", "simulated", "estimated"}:
        raise ValueError("provenance must be observed, simulated, or estimated")

    a = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    e = pd.to_numeric(expected, errors="coerce").to_numpy(dtype=float)
    residual = a - e
    finite = np.isfinite(a) & np.isfinite(e)
    pct = np.divide(
        residual * 100.0,
        e,
        out=np.full_like(residual, np.nan),
        where=e > 0,
    )
    qualifies = finite & (residual >= min_excess_per_period)
    qualifies &= (e <= 0) | (pct >= min_increase_pct)

    results: list[CostSpike] = []
    start: int | None = None

    def emit(stop: int) -> None:
        nonlocal start
        if start is None or stop - start < persistence:
            start = None
            return
        sl = slice(start, stop)
        sum_actual = float(np.sum(a[sl]))
        sum_expected = float(np.sum(e[sl]))
        excess = float(np.maximum(residual[sl], 0.0).sum())
        increase = (100.0 * excess / sum_expected) if sum_expected > 0 else None
        results.append(CostSpike(
            start=actual.index[start], end=actual.index[stop - 1],
            periods=stop - start, actual_cost=sum_actual,
            expected_cost=sum_expected, excess_cost=excess,
            increase_pct=increase, provenance=provenance,
            evidence={
                "min_excess_per_period": float(min_excess_per_period),
                "min_increase_pct": float(min_increase_pct),
                "persistence_required": int(persistence),
                "qualifying_periods": int(stop - start),
            },
        ))
        start = None

    for i, flag in enumerate(qualifies):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            emit(i)
    if start is not None:
        emit(len(qualifies))
    return results


def analyze_cost_series(
    actual: pd.Series,
    *,
    train_end: object,
    min_excess_per_period: float,
    min_increase_pct: float = 0.0,
    persistence: int = 3,
    alpha: float = 1.0,
    min_train_samples: int = 24,
    provenance: Provenance = "estimated",
) -> dict:
    """Fit a past-only seasonal baseline and detect deviations after cutoff.

    Returns the full-index expected-cost series plus interval alerts. Periods
    before ``train_end`` have no expected value and are excluded from alerting.
    The caller remains responsible for ensuring actual costs are in consistent
    units and that the chosen provenance is accurate.
    """
    expected = seasonal_ridge_expected(
        actual, train_end=train_end, alpha=alpha,
        min_train_samples=min_train_samples,
    )
    valid = expected.notna()
    alerts = detect_cost_spikes(
        actual.loc[valid], expected.loc[valid],
        min_excess_per_period=min_excess_per_period,
        min_increase_pct=min_increase_pct,
        persistence=persistence,
        provenance=provenance,
    )
    return {"expected": expected, "alerts": alerts,
            "method": "seasonal_ridge_past_only"}
