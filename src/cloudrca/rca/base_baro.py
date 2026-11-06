"""Base scorer (plan §4.1): BARO-style robust z. This is OUR re-implementation; before
trusting it, reproduce RCAEval's own BARO numbers (plan W9) and diff against them."""
from __future__ import annotations
import numpy as np
import pandas as pd


def metric_scores(df: pd.DataFrame, t_a: float) -> pd.Series:
    """z_{s,m} = max_{t in Q} |x - median_P| / IQR_P, one value per column."""
    pre, post = df[df.index < t_a], df[df.index >= t_a]
    med = pre.median()
    iqr = (pre.quantile(0.75) - pre.quantile(0.25)).replace(0, np.nan)
    z = ((post - med).abs() / iqr).max()
    return z.fillna(0.0)


def service_of(column: str, services: list[str]) -> str | None:
    """Map "<service>_<metric>" -> service by longest known-service prefix.
    TODO: verify RCAEval's real column naming (data/README.md) and adapt."""
    for s in sorted(services, key=len, reverse=True):
        if column.startswith(s + "_"):
            return s
    return None


def service_scores(df: pd.DataFrame, t_a: float, services: list[str]) -> pd.Series:
    z = metric_scores(df, t_a)
    svc = {c: service_of(c, services) for c in z.index}
    b = pd.Series({s: 0.0 for s in services})
    for c, s in svc.items():
        if s is not None:
            b[s] = max(b[s], z[c])
    return b


def minmax(s: pd.Series) -> pd.Series:
    rng = s.max() - s.min()
    return (s - s.min()) / rng if rng > 0 else s * 0.0
