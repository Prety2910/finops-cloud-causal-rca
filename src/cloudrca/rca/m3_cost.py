"""M3a: counterfactual + Shapley cost attribution (plan §4.4)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from .shapley import exact_shapley


class LinearSCM:
    """Each node regressed on its parents in the pre-window (ridge). Simulate in
    topological order, with optional do() interventions on any node."""

    def __init__(self, graph, ridge_lambda: float = 1e-2):
        import networkx as nx
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("SCM graph must be a directed acyclic graph")
        if ridge_lambda < 0:
            raise ValueError("ridge_lambda must be non-negative")
        self.G, self.lam = graph.copy(), ridge_lambda
        self.order = list(nx.topological_sort(graph))
        self.models: dict = {}

    def fit(self, pre: pd.DataFrame):
        missing = set(self.G.nodes) - set(pre.columns)
        if missing:
            raise ValueError(f"pre-window data is missing graph nodes: {sorted(missing)}")
        if len(pre) < 2 or not pre[list(self.G.nodes)].apply(pd.to_numeric, errors="coerce").notna().all().all():
            raise ValueError("pre-window graph data must contain at least two complete numeric rows")
        for n in self.order:
            parents = list(self.G.predecessors(n))
            if parents:
                self.models[n] = (parents, Ridge(alpha=self.lam).fit(pre[parents].to_numpy(), pre[n].to_numpy()))
        return self

    def simulate(self, post: pd.DataFrame, do: dict | None = None) -> pd.DataFrame:
        """Propagate: root nodes keep observed post values; intervened nodes are fixed; others re-predicted."""
        if not self.models and any(self.G.in_degree(n) > 0 for n in self.order):
            raise RuntimeError("SCM must be fit before simulation")
        missing = set(self.G.nodes) - set(post.columns)
        if missing:
            raise ValueError(f"post-window data is missing graph nodes: {sorted(missing)}")
        do = do or {}
        if not set(do).issubset(self.G.nodes):
            raise ValueError("intervention contains a node outside the causal graph")
        for node, value in do.items():
            if np.isscalar(value) and not np.isfinite(value):
                raise ValueError(f"intervention for {node!r} must be finite")
        sim = post.copy()
        for n in self.order:
            if n in do:
                sim[n] = do[n]
            elif n in self.models:
                parents, m = self.models[n]
                sim[n] = m.predict(sim[parents].to_numpy())
        return sim


def attribute_cost(scm: LinearSCM, pre: pd.DataFrame, post: pd.DataFrame, candidates: list[str],
                   cost_node: str = "total_cost"):
    """Model-based cost allocation with an explicit interventional value function.

    ``v(T)`` is mean post-window model outcome under observed exogenous inputs
    minus its mean after intervening on each candidate to its pre-window mean.
    This is a *model counterfactual*, not observational proof of causality.
    Identification requires a correct DAG, adequate pre/post comparability,
    no unmodeled confounding, stable mechanisms, and a valid cost outcome.
    """
    if not candidates or len(set(candidates)) != len(candidates):
        raise ValueError("candidates must be a non-empty list of unique graph nodes")
    if cost_node not in scm.G or not set(candidates).issubset(scm.G.nodes):
        raise ValueError("cost_node and candidates must belong to the fitted graph")
    if cost_node in candidates:
        raise ValueError("cost outcome cannot be included as an intervention candidate")
    required = set(scm.G.nodes)
    for name, frame in (("pre", pre), ("post", post)):
        if len(frame) == 0 or required - set(frame.columns):
            raise ValueError(f"{name}-window data must be non-empty and contain every graph node")
        numeric = frame[list(required)].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(f"{name}-window graph data must be finite numeric values")
    if not scm.models and any(scm.G.in_degree(n) > 0 for n in scm.order):
        raise RuntimeError("SCM must be fit before attribution")
    observed = scm.simulate(post)[cost_node].mean()   # model-consistent baseline

    def v(T: frozenset) -> float:
        do = {c: pre[c].mean() for c in T}
        return float(observed - scm.simulate(post, do)[cost_node].mean())

    phi = exact_shapley(candidates, v)
    delta = float(post[cost_node].mean() - pre[cost_node].mean())
    explained = float(sum(phi.values()))
    return dict(
        phi=phi,
        observed_delta_cost=delta,
        modeled_post_cost=float(observed),
        modeled_counterfactual_explained=explained,
        modeled_unexplained=delta - explained,
        currency=None,
        provenance="model_estimate",
        causal_identification="not_established_by_model_fit_alone",
        assumptions=[
            "specified DAG and structural equations are adequate",
            "pre-window mechanisms transport to the post-window",
            "no unmodeled confounding of candidate causes and cost outcome",
            "pre/post periods are comparable apart from modeled causes",
            "cost_node uses consistent, non-overlapping billing units",
        ],
        value_function="mean model post cost under observed inputs minus mean after do(candidate=pre-window mean)",
    )
