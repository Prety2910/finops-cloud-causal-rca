"""Synthetic change events for RCAEval cases (plan §2.2). Seeded + deterministic.
Rules (document these in the paper; they are the anti-label-leakage defence):
  * code-level faults: deploy on the true service at t_inject - U(0, offset_max); dropped w.p. p_miss
  * resource/network faults: no true change event
  * every case: K ~ Poisson(lambda_decoy) benign events on NON-root services in the look-back window
"""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd

CODE_FAULTS = {"code", "code-level"}


def _rng(seed: int, case_id: str) -> np.random.Generator:
    h = int(hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()[:8], 16)
    return np.random.default_rng(h)


def synth_changes(case_id: str, fault_type: str, root_service: str, services: list[str],
                  t_inject: float, *, seed: int = 0, lambda_decoy: float = 1.0, p_miss: float = 0.2,
                  offset_max_s: float = 120.0, lookback_s: float = 900.0, jitter_s: float = 0.0) -> pd.DataFrame:
    rng = _rng(seed, case_id)
    rows = []
    if fault_type.lower() in CODE_FAULTS and rng.random() >= p_miss:
        t = t_inject - rng.uniform(0, offset_max_s) + (rng.normal(0, jitter_s) if jitter_s else 0.0)
        rows.append(dict(event_id=f"{case_id}-true", ts=t, service=root_service, type="deploy", is_decoy=False))
    non_root = [s for s in services if s != root_service]
    for i in range(rng.poisson(lambda_decoy) if non_root else 0):
        rows.append(dict(
            event_id=f"{case_id}-decoy{i}", ts=t_inject - rng.uniform(0, lookback_s),
            service=str(rng.choice(non_root)), type=str(rng.choice(["deploy", "config"])), is_decoy=True))
    return pd.DataFrame(rows, columns=["event_id", "ts", "service", "type", "is_decoy"])
