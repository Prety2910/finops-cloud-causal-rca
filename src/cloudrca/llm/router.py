"""Tier router T1/T2/T3 (plan §6.3). Thresholds from configs/llm.yaml, tuned on the calibration split.
TODO(W18): T1 template fill (0 LLM cost); T2 small model adapt; T3 large model; write-back; token/latency logging."""
from __future__ import annotations


def choose_tier(sim: float, matched_fix_ok: bool, confidence: float, cfg: dict) -> int:
    r = cfg["router"]
    if confidence < r["abstain_conf"] or sim < r["tau_partial"]:
        return 3
    if sim >= r["tau_hit"] and matched_fix_ok:
        return 1
    return 2
