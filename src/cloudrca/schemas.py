"""Common in-memory case format. One loader per source (RCAEval, testbed) must
produce this, so every method and evaluation script is source-agnostic."""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Case:
    case_id: str
    system: str                     # online_boutique | sock_shop | train_ticket
    dataset: str                    # RE1 | RE2 | RE3 | testbed
    fault_type: str                 # cpu | mem | disk | delay | loss | code | deploy | config ...
    root_cause_service: str
    root_cause_indicator: str | None
    t_inject: float                 # epoch seconds (labelled injection time)
    metrics: pd.DataFrame           # index = epoch seconds; columns = "<service>_<metric>"
    logs: pd.DataFrame | None = None
    spans: pd.DataFrame | None = None
    changes: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["event_id", "ts", "service", "type", "is_decoy"]))
    root_cause_change_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class Candidate:
    id: str
    type: str                       # "service" | "metric" | "change"
    service: str
    score: float
    confidence: float | None = None
    cost_share_inr: float | None = None
    evidence: dict = field(default_factory=dict)
