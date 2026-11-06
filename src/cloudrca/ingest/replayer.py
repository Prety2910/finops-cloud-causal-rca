"""Replay a Case into Postgres with timestamps shifted to 'now' at 1x-60x speed (plan §3.2).
TODO(W4): batch-insert metrics/logs/spans; emit change_events at their shifted times."""
from __future__ import annotations
from cloudrca.schemas import Case


def replay(case: Case, speed: float = 10.0, db_url: str | None = None) -> None:
    raise NotImplementedError
