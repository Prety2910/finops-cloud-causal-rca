"""M3b: calibrated confidence (plan §4.5)."""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize_scalar


def softmax(scores, T: float = 1.0):
    z = np.asarray(scores, float) / T
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def fit_temperature(score_lists, true_idx, bounds=(0.01, 20.0)) -> float:
    """Minimise NLL of the true candidate over the calibration split."""
    def nll(T):
        return -sum(np.log(softmax(s, T)[i] + 1e-12) for s, i in zip(score_lists, true_idx))
    return float(minimize_scalar(nll, bounds=bounds, method="bounded").x)


def ece(conf, correct, n_bins: int = 15) -> float:
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    bins = np.linspace(0, 1, n_bins + 1)
    out = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        if m.any():
            out += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(out)


def brier(conf, correct) -> float:
    return float(np.mean((np.asarray(conf, float) - np.asarray(correct, float)) ** 2))


def reliability_curve(conf, correct, n_bins: int = 10):
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf >= lo) & (conf < hi if hi < 1 else conf <= hi)
        if m.any():
            rows.append((conf[m].mean(), correct[m].mean(), int(m.sum())))
    return rows  # (mean conf, accuracy, count)


def selective_accuracy(conf, correct, thresholds=None):
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    thresholds = np.linspace(0, 1, 21) if thresholds is None else thresholds
    rows = []
    for th in thresholds:
        m = conf >= th
        rows.append((float(th), float(m.mean()), float(correct[m].mean()) if m.any() else float("nan")))
    return rows  # (threshold, coverage, accuracy)
