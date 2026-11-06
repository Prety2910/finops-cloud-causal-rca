"""Online anomaly detector: robust z-score with MAD over a sliding window (plan §3.3)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def robust_z(x: pd.Series, window: int) -> pd.Series:
    med = x.rolling(window, min_periods=window // 2).median().shift(1)
    mad = (x - med).abs().rolling(window, min_periods=window // 2).median().shift(1)
    return (x - med).abs() / (1.4826 * mad.replace(0, np.nan))


def first_anomaly(x: pd.Series, window: int, threshold: float = 4.0, consecutive: int = 3):
    """Index label of the first point that starts a run of >= `consecutive` exceedances, else None."""
    flag = (robust_z(x, window) > threshold).to_numpy()
    run = 0
    for i, f in enumerate(flag):
        run = run + 1 if f else 0
        if run >= consecutive:
            return x.index[i - consecutive + 1]
    return None
