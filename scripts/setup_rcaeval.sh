#!/usr/bin/env bash
# Clone RCAEval into third_party/ (git-ignored). Dataset download links are in its README (Zenodo).
set -euo pipefail
mkdir -p third_party
[ -d third_party/RCAEval ] || git clone https://github.com/phamquiluan/RCAEval third_party/RCAEval
echo "Next: follow third_party/RCAEval/README.md to install and download RE1/RE2/RE3 into data/raw/rcaeval/"
