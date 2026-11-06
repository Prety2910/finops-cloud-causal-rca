"""M1: change-event anchoring (plan §4.2)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import mannwhitneyu


def its_effect(y: pd.Series, t_e: float, hac_lags: int | None = None) -> dict:
    """Interrupted time series: y = b0 + b1 t + b2 D + b3 (t-t_e) D, HAC (Newey-West) SEs.
    Returns the larger of |t-stat(b2)|, |t-stat(b3)| and its p-value."""
    y = y.dropna()
    t = y.index.to_numpy(dtype=float)
    D = (t >= t_e).astype(float)
    if D.sum() < 5 or (1 - D).sum() < 5:
        return dict(delta=0.0, p=1.0)
    X = sm.add_constant(np.column_stack([t - t_e, D, (t - t_e) * D]))
    lags = hac_lags if hac_lags is not None else max(1, int(len(y) ** 0.25))
    try:
        res = sm.OLS(y.to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    except Exception:
        return dict(delta=0.0, p=1.0)
    tv = np.abs(res.tvalues[2:4])
    pv = res.pvalues[2:4]
    k = int(np.nanargmax(tv))
    return dict(delta=float(tv[k]), p=float(pv[k]))


def mannwhitney_effect(y: pd.Series, t_e: float, window_s: float = 300.0) -> dict:
    pre = y[(y.index >= t_e - window_s) & (y.index < t_e)].dropna()
    post = y[(y.index >= t_e) & (y.index < t_e + window_s)].dropna()
    if len(pre) < 5 or len(post) < 5:
        return dict(delta=0.0, p=1.0)
    u = mannwhitneyu(pre, post, alternative="two-sided")
    return dict(delta=float(abs(np.log10(max(u.pvalue, 1e-300)))), p=float(u.pvalue))


def temporal_weight(t_a: float, t_e: float, tau_s: float) -> float:
    return float(np.exp(-(t_a - t_e) / tau_s)) if t_e <= t_a else 0.0


def change_score(delta: float, p: float, t_a: float, t_e: float, *,
                 tau_s: float, alpha: float, delta0: float, n_events: int = 1) -> float:
    """c_e = w_e * sigmoid(delta - delta0), gated by Bonferroni-corrected p < alpha."""
    if p >= alpha / max(n_events, 1):
        return 0.0
    return temporal_weight(t_a, t_e, tau_s) / (1.0 + np.exp(-(delta - delta0)))


def score_events(df: pd.DataFrame, events: pd.DataFrame, t_a: float, cols_for_service, cfg: dict) -> pd.DataFrame:
    """Score each change event. cols_for_service(service) -> metric columns to test
    (the service itself + 1-hop call-graph neighbours, per plan)."""
    test = its_effect if cfg.get("test", "its_hac") == "its_hac" else mannwhitney_effect
    n = len(events)
    out = []
    for e in events.itertuples():
        best = dict(delta=0.0, p=1.0)
        for c in cols_for_service(e.service):
            r = test(df[c], e.ts)
            if r["delta"] > best["delta"]:
                best = r
        out.append(dict(event_id=e.event_id, service=e.service, **best,
                        score=change_score(best["delta"], best["p"], t_a, e.ts, tau_s=cfg["tau_s"],
                                           alpha=cfg["alpha"], delta0=cfg["delta0"], n_events=n)))
    return pd.DataFrame(out)
