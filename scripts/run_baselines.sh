#!/usr/bin/env bash
# Run RCAEval's own BARO/CIRCA/RCD on all 9 datasets, one isolated working dir per job
# (main.py writes ./output/ so jobs must not share a cwd). Usage: run_baselines.sh [JOBS=10]
set -uo pipefail
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
ROOT=$(cd "$(dirname "$0")/.." && pwd); R=$ROOT/third_party/RCAEval; OUT=$ROOT/results/baselines_reproduced
mkdir -p "$OUT" "$ROOT/results/_runs"
job() {
  m=$1; d=$2; w=$ROOT/results/_runs/${m}_${d}
  [ -f "$OUT/${m}_${d}.done" ] && exit 0
  rm -rf "$w"; mkdir -p "$w"; ln -s "$R/data" "$w/data"; cd "$w"
  py=$ROOT/.venv-rcaeval/bin/python; [ "$m" = rcd ] && py=$ROOT/.venv-rcd/bin/python
  s=$(date +%s)
  "$py" "$R/main.py" --method "$m" --dataset "$d" > "$OUT/${m}_${d}.log" 2>&1 && \
    { cp -r output/results "$OUT/${m}_${d}_results" 2>/dev/null; echo "$(( $(date +%s)-s ))" > "$OUT/${m}_${d}.done"; }
}
export -f job; export ROOT R OUT
for d in re2-tt re3-tt re1-tt re2-ob re2-ss re3-ob re3-ss re1-ob re1-ss; do for m in baro circa rcd; do echo "$m $d"; done; done \
  | xargs -P "${1:-10}" -L1 bash -c 'job $0 $1'
echo ALL_DONE > "$OUT/ALL_DONE"
