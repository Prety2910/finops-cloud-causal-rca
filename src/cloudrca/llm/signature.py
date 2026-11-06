"""Incident signature + similarity (plan §6.2)."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Signature:
    root_service: str
    candidate_type: str                  # change | metric
    change_type: str = "none"            # deploy | config | none
    fault_family: str | None = None
    anomalous_kinds: frozenset = field(default_factory=frozenset)   # e.g. {"cpu","latency"}
    path_kinds: tuple = ()               # e.g. ("rpc_out","cpu","latency")
    cost_bucket: int = 0
    summary: str = ""


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 1.0


def edit_distance(a, b) -> int:
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[len(b)]


def path_similarity(a, b) -> float:
    m = max(len(a), len(b))
    return 1.0 - edit_distance(a, b) / m if m else 1.0


def similarity(new: Signature, old: Signature, embed_cos: float = 0.0,
               w: dict | None = None) -> float:
    w = w or dict(jaccard=0.4, path=0.3, same_root_change=0.2, embed=0.1)
    same = float(new.root_service == old.root_service and new.change_type == old.change_type)
    return (w["jaccard"] * jaccard(new.anomalous_kinds, old.anomalous_kinds)
            + w["path"] * path_similarity(new.path_kinds, old.path_kinds)
            + w["same_root_change"] * same + w["embed"] * embed_cos)
