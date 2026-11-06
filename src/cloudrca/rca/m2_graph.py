"""M2: topology-constrained causal graph + ranking walk (plan §4.3)."""
from __future__ import annotations
import networkx as nx

# metric "kinds" used for intra-service allowed edges: resource -> latency -> errors
RESOURCE = {"cpu", "mem", "disk", "net"}


def allowed_edges(call_graph: dict[str, list[str]], kinds_by_service: dict[str, set[str]]):
    """Return the set of allowed directed edges between (service, kind) nodes.
    Faults propagate callee -> caller; inside a service resource -> latency -> error."""
    edges = set()
    for caller, callees in call_graph.items():
        for callee in callees:
            for k_src in kinds_by_service.get(callee, ()):
                for k_dst in kinds_by_service.get(caller, ()):
                    edges.add(((callee, k_src), (caller, k_dst)))
    for s, kinds in kinds_by_service.items():
        for r in kinds & RESOURCE:
            if "latency" in kinds:
                edges.add(((s, r), (s, "latency")))
        if "latency" in kinds and "error" in kinds:
            edges.add(((s, "latency"), (s, "error")))
    return edges


def discover_pc(data, node_names, allowed: set, alpha: float = 0.05):
    """PC with BackgroundKnowledge forbidding every non-allowed edge.
    TODO(W11): implement with causal-learn:
        from causallearn.search.ConstraintBased.PC import pc
        from causallearn.utils.PCUtils.BackgroundKnowledge import BackgroundKnowledge
    Run on differenced, standardised series; return a networkx.DiGraph with |partial corr| weights."""
    raise NotImplementedError


def discover_granger(data, node_names, allowed: set, maxlag: int = 3, p: float = 0.05):
    """TODO(W11): statsmodels grangercausalitytests only on allowed pairs."""
    raise NotImplementedError


def ranking_walk(G: nx.DiGraph, anomaly_scores: dict, damping: float = 0.85) -> dict:
    """Personalised PageRank on the REVERSED graph, personalised by anomaly z of SLO nodes."""
    if G.number_of_nodes() == 0:
        return {}
    pers = {n: max(anomaly_scores.get(n, 0.0), 0.0) for n in G}
    if sum(pers.values()) == 0:
        pers = None
    return nx.pagerank(G.reverse(copy=True), alpha=damping, personalization=pers, weight="weight")
