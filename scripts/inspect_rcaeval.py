"""Print the structure of a downloaded RCAEval folder so the format can be documented
(data/README.md) before the loader is written. Usage: python scripts/inspect_rcaeval.py data/raw/rcaeval"""
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
exts = Counter(p.suffix for p in root.rglob("*") if p.is_file())
print("file types:", dict(exts))
for d in sorted(p for p in root.rglob("*") if p.is_dir())[:60]:
    files = [f.name for f in d.iterdir() if f.is_file()]
    print(f"{d.relative_to(root)}/  ({len(files)} files) e.g. {files[:4]}")
try:
    import pandas as pd
    for csv in list(root.rglob("*.csv"))[:1]:
        df = pd.read_csv(csv, nrows=3)
        print("\nsample csv:", csv.relative_to(root))
        print("columns (first 25):", list(df.columns)[:25])
        print(df.head(3).to_string()[:1200])
except Exception as e:
    print("pandas unavailable or csv unreadable:", e)
