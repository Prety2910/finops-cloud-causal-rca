"""Transparent fleet ranking with explicit savings overlap controls."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def rank_fleet_opportunities(opportunities: list[dict], *, currency: str,
                             limit: int | None = None) -> dict[str, Any]:
    """Rank monthly savings opportunities and avoid summing declared overlaps.

    Each item requires ``resource_id``, ``alert_type``, and
    ``estimated_monthly_savings``. ``evidence_score`` and ``operational_risk``
    are required caller-supplied heuristic inputs in [0, 1], never
    probabilities. Missing values are not silently replaced with optimistic
    defaults.
    Recommendations sharing an ``overlap_group`` compete; only the largest
    gross monthly savings estimate in each group contributes to the fleet
    total. Items without a defensible monthly estimate are counted and omitted.
    If no group is supplied, recommendations for the same resource are assumed
    to overlap; different resources need an explicit shared-capacity group to
    capture cross-resource overlap.
    """
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive or None")
    if not currency:
        raise ValueError("currency is required; all estimates must use it")
    grouped: dict[str, list[dict]] = defaultdict(list)
    excluded = 0
    for raw in opportunities:
        if not raw.get("resource_id") or not raw.get("alert_type"):
            raise ValueError("each opportunity needs resource_id and alert_type")
        amount = raw.get("estimated_monthly_savings")
        if amount is None or not np.isfinite(float(amount)) or float(amount) <= 0:
            excluded += 1
            continue
        if "evidence_score" not in raw or "operational_risk" not in raw:
            raise ValueError("rankable opportunities require explicit evidence_score and operational_risk inputs")
        evidence = float(raw["evidence_score"])
        risk = float(raw["operational_risk"])
        if not np.isfinite(evidence) or not 0 <= evidence <= 1:
            raise ValueError("evidence_score must be a heuristic in [0, 1]")
        if not np.isfinite(risk) or not 0 <= risk <= 1:
            raise ValueError("operational_risk must be in [0, 1]")
        item = dict(raw)
        item["estimated_monthly_savings"] = float(amount)
        item["evidence_score"] = evidence
        item["operational_risk"] = risk
        item["priority_score"] = float(amount) * evidence * (1.0 - risk)
        group = str(raw.get("overlap_group") or f"resource:{raw['resource_id']}")
        item["overlap_group"] = group
        grouped[group].append(item)

    selected = []
    overlap_groups = 0
    for group, items in grouped.items():
        if len(items) > 1:
            overlap_groups += 1
        # Keep the largest savings once per overlap group; risk is applied for
        # priority ordering, not to manufacture a fractional savings amount.
        winner = max(items, key=lambda x: (x["estimated_monthly_savings"], x["priority_score"]))
        selected.append(winner)
    selected.sort(key=lambda x: (-x["priority_score"], -x["estimated_monthly_savings"],
                                 str(x["resource_id"]), str(x["alert_type"])))
    total = float(sum(x["estimated_monthly_savings"] for x in selected))
    category_totals: dict[str, float] = defaultdict(float)
    for item in selected:
        category_totals[str(item["alert_type"])] += item["estimated_monthly_savings"]
    visible = selected if limit is None else selected[:limit]
    return {
        "currency": currency,
        "estimated_monthly_savings_after_overlap": total,
        "selected_opportunities": len(selected),
        "excluded_without_positive_monthly_estimate": excluded,
        "overlap_groups_with_multiple_candidates": overlap_groups,
        "category_totals": dict(category_totals),
        "priority_policy": "monthly savings × evidence heuristic × (1 - operational risk); not causal or calibrated",
        "opportunities": visible,
    }
