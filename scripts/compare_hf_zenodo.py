"""Cross-check the Hugging Face Parquet mirror (data/raw/rcaeval) against the canonical Zenodo
archives (data/raw/zenodo) for every case: inject time, metric frame (time, columns, values), and
log/trace row counts. Writes data/processed/rcaeval_hf_vs_zenodo.csv; exit 1 if any case differs.
Usage: python -I scripts/compare_hf_zenodo.py"""
import re, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd

HF, ZEN = Path("data/raw/rcaeval"), Path("data/raw/zenodo")
PAT = re.compile(r"^(re\d)(ob|ss|tt)_(.+)_([a-z0-9]+)_(\d+)$")


def zdir(case):
    s, sys_, svc, fault, rep = PAT.match(case).groups()
    base = ZEN / f"{s.upper()}-{sys_.upper()}"
    d = base / f"{svc}_{fault}" / rep
    if not d.is_dir() and int(rep) > 3 and (base / f"{svc}_{fault}_1").is_dir():
        # Zenodo stores RE3-TT ts-route-service_f3 repetitions 4-6 under "<svc>_<fault>_1/{1,2,3}"
        d = base / f"{svc}_{fault}_1" / str(int(rep) - 3)
    return d


def nrows(csv):
    with open(csv, "rb") as f:
        return sum(1 for _ in f) - 1   # NB: multi-line messages would inflate this; compared loosely


def cmp(case):
    h, z = HF / case, zdir(case)
    r = dict(case=case, zenodo_dir_exists=z.is_dir())
    if not z.is_dir():
        return r | dict(status="MISSING_IN_ZENODO")
    r["inject_equal"] = (h / "inject_time.txt").read_text().strip() == (z / "inject_time.txt").read_text().strip()
    hm = pd.read_parquet(h / "metrics.parquet")
    best = None
    for fn in ("simple_data.csv", "simple_metrics.csv", "data.csv", "metrics.csv"):
        if not (z / fn).exists():
            continue
        zm = pd.read_csv(z / fn)
        zm = zm.drop(columns=[c for c in zm.columns if c.startswith("time.")])  # duplicated index col in some RE1-OB files
        ok_cols = list(zm.columns) == list(hm.columns)
        ok_time = len(zm) == len(hm) and (zm["time"].to_numpy() == hm["time"].to_numpy()).all()
        ok_val = False
        if ok_cols and ok_time:
            a, b = zm.drop(columns="time").to_numpy(float), hm.drop(columns="time").to_numpy(float)
            ok_val = bool(np.allclose(a, b, equal_nan=True, rtol=1e-6, atol=1e-9))
        cand = dict(zen_metrics_file=fn, cols_equal=ok_cols, time_equal=ok_time, values_equal=ok_val,
                    zen_rows=len(zm), hf_rows=len(hm), zen_cols=zm.shape[1] - 1, hf_cols=hm.shape[1] - 1)
        if best is None or (ok_cols, ok_time, ok_val) > (best["cols_equal"], best["time_equal"], best["values_equal"]):
            best = cand
    r |= best or dict(zen_metrics_file=None)
    for kind in ("logs", "traces"):
        hp, zp = h / f"{kind}.parquet", z / f"{kind}.csv"
        r[f"{kind}_presence_equal"] = hp.exists() == zp.exists()
        if hp.exists() and zp.exists():
            import pyarrow.parquet as pq
            n_hf = pq.ParquetFile(hp).metadata.num_rows
            zdf = pd.read_csv(zp, usecols=[0], dtype=str, low_memory=False)
            r[f"{kind}_rows_hf"], r[f"{kind}_rows_zen"] = n_hf, len(zdf)
    bad = []
    if not r["inject_equal"]: bad.append("inject")
    if not (r.get("cols_equal") and r.get("time_equal") and r.get("values_equal")): bad.append("metrics")
    for kind in ("logs", "traces"):
        if not r[f"{kind}_presence_equal"]: bad.append(f"{kind}_presence")
        if r.get(f"{kind}_rows_hf") != r.get(f"{kind}_rows_zen"): bad.append(f"{kind}_rows")
    r["status"] = "OK" if not bad else "DIFF:" + ",".join(bad)
    return r


if __name__ == "__main__":
    cases = sorted(pd.read_parquet(HF / "cases.parquet").case)
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(cmp, cases, chunksize=4))
    df = pd.DataFrame(res)
    Path("data/processed").mkdir(exist_ok=True)
    df.to_csv("data/processed/rcaeval_hf_vs_zenodo.csv", index=False)
    print(df.status.value_counts().to_string())
    print(df.groupby(df.case.str[:5]).zen_metrics_file.value_counts().to_string())
    print(df[df.status != "OK"][["case", "status", "zen_rows", "hf_rows", "zen_cols", "hf_cols"]].head(40).to_string())
    sys.exit(0 if (df.status == "OK").all() else 1)
