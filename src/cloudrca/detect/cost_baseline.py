"""Eco-FinOps-inspired seasonal Ridge baseline for costs or telemetry.

This predicts future buckets from a historical training prefix and does not
fit on the prediction period.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


def _seasonal_features(index: pd.DatetimeIndex, origin: pd.Timestamp,
                       trend_scale_s: float) -> np.ndarray:
    hour = (index.hour.to_numpy(dtype=float)
            + index.minute.to_numpy(dtype=float) / 60.0
            + index.second.to_numpy(dtype=float) / 3600.0
            + index.microsecond.to_numpy(dtype=float) / 3_600_000_000.0)
    weekday = index.dayofweek.to_numpy(dtype=float)
    elapsed_s = (index - origin) / pd.Timedelta(seconds=1)
    trend = np.asarray(elapsed_s, dtype=float) / trend_scale_s
    return np.column_stack((
        np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
        np.sin(2 * np.pi * weekday / 7), np.cos(2 * np.pi * weekday / 7),
        trend,
    ))


def _fit_seasonal_ridge(
    values_series: pd.Series,
    *,
    predict_from: object,
    alpha: float = 1.0,
    min_train_samples: int = 24,
    output_name: str = "prediction",
) -> tuple[pd.Series, pd.Series]:
    """Fit seasonal Ridge on a series prefix and predict after a cutoff.

    ``values_series`` must contain one consistently bucketed numeric value per
    timestamp and use a unique, increasing ``DatetimeIndex``. Missing/nonfinite
    training values are ignored. The result shares the input index; values
    before the cutoff are NaN to avoid in-sample leakage.

    Features are daily and weekly sine/cosine terms plus a linear trend. This
    is a lightweight seasonal Ridge baseline inspired by Eco-FinOps; it is not
    an exact replication of that paper's benchmark implementation. It can be
    applied to costs or utilization series; callers must choose relevant units.
    """
    if not isinstance(values_series, pd.Series):
        raise TypeError("values_series must be a pandas Series")
    if not isinstance(values_series.index, pd.DatetimeIndex):
        raise TypeError("values_series must have a DatetimeIndex")
    if values_series.index.has_duplicates or not values_series.index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and increasing")
    intervals = np.diff(values_series.index.asi8)
    if len(intervals) and np.any(intervals != intervals[0]):
        raise ValueError("timestamps must use a regular bucket interval")
    if not np.isfinite(alpha) or alpha < 0:
        raise ValueError("alpha must be a finite non-negative value")
    if min_train_samples < 2:
        raise ValueError("min_train_samples must be at least 2")

    cutoff = pd.Timestamp(predict_from)
    if values_series.index.tz is not None:
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize(values_series.index.tz)
        else:
            cutoff = cutoff.tz_convert(values_series.index.tz)
    elif cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)

    values = pd.to_numeric(values_series, errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(values)
    train = np.asarray(values_series.index < cutoff, dtype=bool) & finite
    predict = np.asarray(values_series.index >= cutoff, dtype=bool)
    n_train = int(train.sum())
    if n_train < min_train_samples:
        raise ValueError(f"need at least {min_train_samples} finite training samples; got {n_train}")
    if not predict.any():
        raise ValueError("predict_from must leave at least one timestamp to predict")

    origin = values_series.index[train][0]
    span_s = max((values_series.index[train][-1] - origin).total_seconds(), 1.0)
    X = _seasonal_features(values_series.index, origin, span_s)
    model = Ridge(alpha=float(alpha))
    model.fit(X[train], values[train])

    result = np.full(len(values_series), np.nan, dtype=float)
    result[predict] = model.predict(X[predict])
    prediction = pd.Series(result, index=values_series.index, name=output_name)
    train_residuals = pd.Series(
        values[train] - model.predict(X[train]),
        index=values_series.index[train], name="training_residual",
    )
    return prediction, train_residuals


def seasonal_ridge_predict(
    values_series: pd.Series,
    *,
    predict_from: object,
    alpha: float = 1.0,
    min_train_samples: int = 24,
    output_name: str = "prediction",
) -> pd.Series:
    """Return past-only seasonal Ridge predictions after a cutoff."""
    prediction, _ = _fit_seasonal_ridge(
        values_series, predict_from=predict_from, alpha=alpha,
        min_train_samples=min_train_samples, output_name=output_name,
    )
    return prediction


def seasonal_ridge_predict_with_residuals(
    values_series: pd.Series,
    *,
    predict_from: object,
    alpha: float = 1.0,
    min_train_samples: int = 24,
    output_name: str = "prediction",
) -> tuple[pd.Series, pd.Series]:
    """Return future predictions and in-sample training residuals for MAD scaling."""
    return _fit_seasonal_ridge(
        values_series, predict_from=predict_from, alpha=alpha,
        min_train_samples=min_train_samples, output_name=output_name,
    )


def seasonal_ridge_expected(
    cost: pd.Series,
    *,
    train_end: object,
    alpha: float = 1.0,
    min_train_samples: int = 24,
) -> pd.Series:
    """Fit on historical cost before ``train_end`` and predict afterward."""
    return seasonal_ridge_predict(cost, predict_from=train_end, alpha=alpha,
                                  min_train_samples=min_train_samples,
                                  output_name="expected_cost")
