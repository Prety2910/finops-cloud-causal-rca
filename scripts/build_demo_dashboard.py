#!/usr/bin/env python3
"""Build a self-contained HTML dashboard from a synthetic policy demo JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cloudrca.demo_dashboard import render_demo_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("results/demo/policy_demo.json"))
    parser.add_argument("--output", type=Path, default=Path("results/demo/index.html"))
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    html = render_demo_dashboard(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"Wrote offline demo dashboard: {args.output}")


if __name__ == "__main__":
    main()
