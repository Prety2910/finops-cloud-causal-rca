"""Build the curated working copy data/processed/rcaeval/ from the Hugging Face Parquet mirror
(data/raw/rcaeval), patching the three cases where the mirror differs from the canonical Zenodo
archives in a way that is a mirror defect (see docs/DATA_AUDIT.md). Everything else is hard-linked.
Writes <out>/cases.parquet (same schema as the HF index, + `source`) and <out>/<case>/{metrics,logs,traces}.parquet
+ inject_time.txt. Usage: python -I scripts/build_rcaeval_processed.py"""
import os, shutil
from pathlib import Path
import pandas as pd

HF, ZEN, OUT = Path("data/raw/rcaeval"), Path("data/raw/zenodo"), Path("data/processed/rcaeval")

PATCHES = {
    # case: (what, zenodo dir)
    "re1ob_currencyservice_loss_1": ("inject_time", ZEN / "RE1-OB/currencyservice_loss/1"),
    "re1ob_productcatalogservice_cpu_3": ("metrics", ZEN / "RE1-OB/productcatalogservice_cpu/3"),
    "re2tt_ts-auth-service_cpu_1": ("logs", ZEN / "RE2-TT/ts-auth-service_cpu/1"),
}


def main():
    idx = pd.read_parquet(HF / "cases.parquet").set_index("case", drop=False)
    idx["source"] = "hf"
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for case in idx.index:
        d = OUT / case; d.mkdir()
        for f in (HF / case).iterdir():
            os.link(f, d / f.name)

    for case, (what, zdir) in PATCHES.items():
        d = OUT / case
        if what == "inject_time":
            (d / "inject_time.txt").unlink()
            (d / "inject_time.txt").write_text((zdir / "inject_time.txt").read_text().strip() + "\n")
            inj = int((d / "inject_time.txt").read_text())
            idx.loc[case, ["inject_time"]] = inj
            m = pd.read_parquet(d / "metrics.parquet")
            idx.loc[case, ["normal_timesteps", "faulty_timesteps"]] = [(m.time < inj).sum(), (m.time >= inj).sum()]
        elif what == "metrics":
            z = pd.read_csv(zdir / "data.csv")
            z = z.drop(columns=[c for c in z.columns if c.startswith("time.")])
            z = z.dropna(subset=["time"]).astype({"time": "int64"})
            h = pd.read_parquet(d / "metrics.parquet")
            assert list(z.columns) == list(h.columns), "column mismatch vs mirror"
            assert z.time.is_unique and z.time.is_monotonic_increasing
            (d / "metrics.parquet").unlink()
            z.to_parquet(d / "metrics.parquet", index=False)
            inj = int((d / "inject_time.txt").read_text())
            idx.loc[case, ["n_timesteps", "time_start", "time_end"]] = [len(z), z.time.min(), z.time.max()]
            idx.loc[case, "duration_minutes"] = round((z.time.max() - z.time.min()) / 60, 1)
            idx.loc[case, ["normal_timesteps", "faulty_timesteps"]] = [(z.time < inj).sum(), (z.time >= inj).sum()]
        elif what == "logs":
            l = pd.read_csv(zdir / "logs.csv", usecols=["timestamp", "container_name", "message"],
                            dtype=str, keep_default_na=False, low_memory=False)
            l["timestamp"] = l["timestamp"].astype("int64") // 10**9   # mirror stores unix seconds
            l.to_parquet(d / "logs.parquet", index=False)
            idx.loc[case, ["has_logs", "n_logs"]] = [True, len(l)]
        idx.loc[case, "source"] = f"hf+zenodo:{what}"

    for c in ["inject_time", "n_timesteps", "time_start", "time_end", "normal_timesteps", "faulty_timesteps", "n_logs"]:
        idx[c] = idx[c].astype("int64")
    idx["has_logs"] = idx["has_logs"].astype(bool)
    idx.reset_index(drop=True).to_parquet(OUT / "cases.parquet", index=False)
    print("built", len(idx), "cases ->", OUT, "| patched:", list(PATCHES))


main()
