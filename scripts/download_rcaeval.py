"""Download RE1/RE2/RE3 (Parquet mirror on Hugging Face) into data/raw/rcaeval/. Resumable."""
import sys
from huggingface_hub import snapshot_download

suites = sys.argv[1:] or ["re1", "re2", "re3"]
snapshot_download(repo_id="phamquiluan/RCAEval", repo_type="dataset",
                  allow_patterns=[f"{s}*" for s in suites] + ["cases.parquet", "README*"],
                  local_dir="data/raw/rcaeval", max_workers=8)
print("done")
