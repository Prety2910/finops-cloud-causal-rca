"""Incident knowledge graph (plan §6.1): NetworkX in memory, ig_nodes/ig_edges in Postgres.
TODO(W17): load/save, add_incident, nearest(sig, k), write_back(explanation), mark_outcome(fail)."""
import networkx as nx

NODE_KINDS = {"service", "metric", "change", "incident", "root_cause", "fix", "explanation"}
EDGE_KINDS = {"HAS_ANOMALY", "CAUSED_BY", "ON", "VIA_PATH", "RESOLVED_BY", "SIMILAR_TO", "CALLS"}


class IncidentGraph:
    def __init__(self):
        self.g = nx.MultiDiGraph()
