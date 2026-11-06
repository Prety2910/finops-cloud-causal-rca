"""RCA engine: composes base + M1 + M2 + M3 and emits the JSON contract (plan §4.7).
Module switches come from configs/rca.yaml so ablations are config-only."""
from __future__ import annotations
import pandas as pd
from cloudrca.schemas import Case
from . import base_baro as base
from . import m1_change as m1


def run_case(case: Case, services: list[str], t_a: float, cfg: dict, call_graph: dict | None = None) -> dict:
    """Service-level ranking. Returns {"ranking": [service,...], "candidates": [...], "module_scores": {...}}."""
    b = base.service_scores(case.metrics, t_a, services)
    b_hat = base.minmax(b)
    score = cfg["combine"]["alpha"] * b_hat
    mod = {"base": b_hat.to_dict()}
    candidates = []

    if cfg["m1"]["enabled"] and len(case.changes):
        def cols_for(service):
            near = {service} | set(call_graph.get(service, [])) if call_graph else {service}
            return [c for c in case.metrics.columns if base.service_of(c, services) in near]
        ev = m1.score_events(case.metrics, case.changes, t_a, cols_for, cfg["m1"])
        boost = ev.groupby("service")["score"].max() if len(ev) else pd.Series(dtype=float)
        score = score.add(cfg["m1"]["lam"] * boost.reindex(score.index).fillna(0.0), fill_value=0.0)
        mod["m1"] = boost.to_dict()
        candidates += [dict(id=r.event_id, type="change", service=r.service, score=r.score) for r in ev.itertuples()]

    if cfg["m2"]["enabled"]:
        pass  # TODO(W11): discover graph -> ranking_walk -> r_hat; score += beta * r_hat
    if cfg["m3"]["enabled"]:
        pass  # TODO(W13-14): SCM attribution + temperature scaling -> confidence, cost_share_inr

    ranking = score.sort_values(ascending=False).index.tolist()
    return dict(ranking=ranking, candidates=candidates, module_scores=mod)
