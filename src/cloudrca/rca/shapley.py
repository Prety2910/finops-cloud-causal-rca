"""Exact Shapley values for <= ~10 players (plan §4.4: top-k <= 5 -> 32 coalitions)."""
from __future__ import annotations
from itertools import combinations
from math import factorial
from typing import Callable, Hashable, Sequence


def exact_shapley(players: Sequence[Hashable], v: Callable[[frozenset], float]) -> dict:
    n = len(players)
    cache: dict[frozenset, float] = {}

    def val(s: frozenset) -> float:
        if s not in cache:
            cache[s] = v(s)
        return cache[s]

    phi = {p: 0.0 for p in players}
    for p in players:
        others = [q for q in players if q != p]
        for r in range(n):
            w = factorial(r) * factorial(n - r - 1) / factorial(n)
            for sub in combinations(others, r):
                s = frozenset(sub)
                phi[p] += w * (val(s | {p}) - val(s))
    return phi
