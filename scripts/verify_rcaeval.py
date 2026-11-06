"""Verify the downloaded RCAEval data (every case) against cases.parquet and the published table.
Writes data/processed/rcaeval_verification.csv (one row per case) and exits non-zero on any failure.
Usage: python -I scripts/verify_rcaeval.py [data/raw/rcaeval]"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/rcaeval")
EXPECTED = {"RE1-OB": 125, "RE1-SS": 125, "RE1-TT": 125, "RE2-OB": 90, "RE2-SS": 90, "RE2-TT": 90,
            "RE3-OB": 30, "RE3-SS": 30, "RE3-TT": 30}
METRIC_RANGE = {"RE1-OB": (49, 59), "RE1-SS": (57, 63), "RE1-TT": (198, 238), "RE2-OB": (69, 77),
                "RE2-SS": (74, 82), "RE2-TT": (340, 376), "RE3-OB": (68, 101), "RE3-SS": (80, 107),
                "RE3-TT": (294, 322)}


def check(row):
    d = ROOT / row["case"]
    err = []
    out = dict(case=row["case"], dataset=row["dataset"])
    if row["case"] != f"{row['dataset'].lower().replace('-', '')}_{row['root_cause_service']}_{row['fault']}_{row['repetition']}":
        err.append("dirname!=index fields")
    for f, flag in [("metrics.parquet", True), ("inject_time.txt", True),
                    ("logs.parquet", row["has_logs"]), ("traces.parquet", row["has_traces"])]:
        if (d / f).exists() != bool(flag):
            err.append(f"file presence mismatch: {f}")
    try:
        inj = int((d / "inject_time.txt").read_text().strip())
        out["inject_matches_index"] = inj == row["inject_time"]
        if inj != row["inject_time"]:
            err.append("inject_time.txt != index")
        m = pd.read_parquet(d / "metrics.parquet")
        t = m["time"].to_numpy()
        out.update(n_rows=len(m), n_metric_cols=m.shape[1] - 1)
        if len(m) != row["n_timesteps"]:
            err.append("rows != n_timesteps")
        if m.shape[1] - 1 != row["n_metrics"]:
            err.append("cols != n_metrics")
        if t.min() != row["time_start"] or t.max() != row["time_end"]:
            err.append("time range != index")
        if not (t[0] < inj < t[-1]):
            err.append("inject outside data window")
        steps = np.diff(t)
        out["monotonic"] = bool((steps > 0).all())
        out["frac_1s_steps"] = float((steps == 1).mean())
        if not out["monotonic"]:
            err.append("time not strictly increasing")
        out["n_pre"], out["n_post"] = int((t < inj).sum()), int((t >= inj).sum())
        v = m.drop(columns="time")
        out["nan_frac"] = float(v.isna().to_numpy().mean())
        out["n_inf"] = int(np.isinf(v.to_numpy(dtype=float)).sum())
        out["n_const_cols"] = int((v.nunique() <= 1).sum())
        if out["nan_frac"] > 0.2:
            out["warn"] = f"high NaN frac {out['nan_frac']:.2f} (partial-NaN columns; ffill/fillna(0) as RCAEval does)"
        if out["n_inf"]:
            err.append("inf values")
        svc = row["root_cause_service"]
        out["rc_in_metric_cols"] = any(c.startswith(svc + "_") for c in v.columns)
        if not out["rc_in_metric_cols"]:
            err.append("root-cause service has no metric column (name mismatch?)")
        lo, hi = METRIC_RANGE[row["dataset"]]
        if not lo <= row["n_metrics"] <= hi:
            err.append("n_metrics outside published range")
    except Exception as e:
        err.append(f"metrics read error: {e}")
    if row["has_logs"]:
        try:
            pf = pq.ParquetFile(d / "logs.parquet")
            out["n_logs"] = pf.metadata.num_rows
            if pf.metadata.num_rows != row["n_logs"]:
                err.append("n_logs mismatch")
            if set(pf.schema.names) != {"timestamp", "container_name", "message"}:
                err.append("unexpected log columns")
        except Exception as e:
            err.append(f"logs read error: {e}")
    if row["has_traces"]:
        try:
            pf = pq.ParquetFile(d / "traces.parquet")
            out["n_traces"] = pf.metadata.num_rows
            if pf.metadata.num_rows != row["n_traces"]:
                err.append("n_traces mismatch")
            s = pd.read_parquet(d / "traces.parquet", columns=["spanID", "parentSpanID", "serviceName"])
            out["span_ids_unique"] = bool(s.spanID.is_unique)
            out["frac_spans_with_parent_in_trace"] = float(s.parentSpanID.isin(s.spanID).mean())
            out["n_trace_services"] = int(s.serviceName.nunique())
        except Exception as e:
            err.append(f"traces read error: {e}")
    out["errors"] = "; ".join(err)
    return out


def main():
    idx = pd.read_parquet(ROOT / "cases.parquet")
    problems = []
    got = idx.groupby("dataset").size().to_dict()
    if got != EXPECTED:
        problems.append(f"case counts differ from published table: {got}")
    dirs = {p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")}
    if dirs != set(idx.case):
        problems.append(f"dir/index mismatch: only on disk={sorted(dirs - set(idx.case))[:5]}, "
                        f"only in index={sorted(set(idx.case) - dirs)[:5]}")
    if idx.case.duplicated().any():
        problems.append("duplicate case ids in index")
    rows = idx.to_dict("records")
    with ProcessPoolExecutor(12) as ex:
        res = list(ex.map(check, rows, chunksize=8))
    r = pd.DataFrame(res)
    out = Path("data/processed"); out.mkdir(parents=True, exist_ok=True)
    r.to_csv(out / "rcaeval_verification.csv", index=False)
    bad = r[r.errors != ""]
    print(f"cases checked: {len(r)} | with errors: {len(bad)}")
    print(r.groupby("dataset").agg(n=("case", "size"), rows_min=("n_rows", "min"), rows_max=("n_rows", "max"),
          nan_max=("nan_frac", "max"), const_cols_max=("n_const_cols", "max"),
          frac1s_min=("frac_1s_steps", "min"), rc_ok=("rc_in_metric_cols", "mean")).to_string())
    for p in problems:
        print("PROBLEM:", p)
    if len(bad):
        print(bad.groupby("errors").size().sort_values(ascending=False).head(20).to_string())
    sys.exit(1 if problems or len(bad) else 0)


main()
