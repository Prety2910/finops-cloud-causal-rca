"""Main RCA benchmark runner (plan §5).
Writes results/<run_id>/{per_case.csv, summary.json}. per_case.csv has one row per
(method, case) with the ranking + hit@k so every table/CI is recomputable from it.

Methods are registered in METHODS; external baselines (BARO/RCD/CIRCA) should call
RCAEval's own implementations so numbers match the literature."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import pandas as pd
from cloudrca import config
from cloudrca.eval.metrics import ac_at_k, avg_at_k
from cloudrca.eval.stats import bootstrap_ci

METHODS: dict = {}   # name -> callable(case, services, t_a) -> ranked list[str]


def register(name):
    def deco(fn):
        METHODS[name] = fn
        return fn
    return deco


def summarise(df: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    rows = []
    for (method, ds), g in df.groupby(["method", "dataset"]):
        r = dict(method=method, dataset=ds, n=len(g), avg5=avg_at_k(g["ranking"], g["truth"], 5))
        for k in (1, 3, 5):
            hits = [int(t in rk[:k]) for rk, t in zip(g["ranking"], g["truth"])]
            m, lo, hi = bootstrap_ci(hits, n_boot, seed=seed)
            r.update({f"ac{k}": m, f"ac{k}_lo": lo, f"ac{k}_hi": hi})
        r["sec_per_case"] = g["seconds"].mean()
        rows.append(r)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/eval.yaml")
    ap.add_argument("--ablations", action="store_true")
    ap.add_argument("--split", default="test")
    a = ap.parse_args()
    cfg = config.load(a.config)
    # TODO: iterate cases from data/processed via the unified loader, restricted to --split,
    #       call each method in METHODS (or ablation variants), time it, collect rows.
    raise SystemExit("Loaders not implemented yet - see docs/NEXT_STEPS.md steps 3-5.")


if __name__ == "__main__":
    main()
