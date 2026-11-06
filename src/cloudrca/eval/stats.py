"""Bootstrap CIs and paired significance tests (plan §5)."""
from __future__ import annotations
import numpy as np
from scipy.stats import binomtest


def bootstrap_ci(values, n: int = 1000, alpha: float = 0.05, seed: int = 0):
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def paired_bootstrap(a, b, n: int = 1000, seed: int = 0):
    """Returns (mean diff a-b, p-value for H0: diff<=0 one-sided)."""
    d = np.asarray(a, float) - np.asarray(b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float((means <= 0).mean())


def mcnemar_exact(a_correct, b_correct) -> float:
    """Two-sided exact McNemar on paired 0/1 outcomes."""
    a, b = np.asarray(a_correct, int), np.asarray(b_correct, int)
    n01 = int(((a == 0) & (b == 1)).sum())
    n10 = int(((a == 1) & (b == 0)).sum())
    if n01 + n10 == 0:
        return 1.0
    return float(binomtest(n10, n10 + n01, 0.5).pvalue)
