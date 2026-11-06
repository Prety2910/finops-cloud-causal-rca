"""Ranking metrics. For headline numbers prefer RCAEval's own evaluator so results
are comparable with the literature; use these for our own methods/ablations and
cross-check that both agree on the baselines."""
from __future__ import annotations
from typing import Sequence


def ac_at_k(rankings: Sequence[Sequence[str]], truths: Sequence[str], k: int) -> float:
    hits = [t in list(r)[:k] for r, t in zip(rankings, truths)]
    return sum(hits) / len(hits)


def avg_at_k(rankings, truths, k: int = 5) -> float:
    return sum(ac_at_k(rankings, truths, i) for i in range(1, k + 1)) / k


def per_case_hits(rankings, truths, k: int) -> list[int]:
    return [int(t in list(r)[:k]) for r, t in zip(rankings, truths)]
