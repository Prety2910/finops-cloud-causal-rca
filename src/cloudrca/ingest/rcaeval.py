"""Load the audited, curated RCAEval parquet layout into :class:`Case` objects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator

import pandas as pd
import yaml

from cloudrca.schemas import Case


def _known_services(config_dir: Path, system: str, manifest: pd.DataFrame) -> set[str]:
    """Return services positively associated with this system.

    The graph YAMLs are incomplete lower bounds. Root-cause labels in the
    manifest augment them; unknown services are retained by the caller.
    """
    path = config_dir / f"{system}.yaml"
    known: set[str] = set()
    if path.exists():
        cfg = yaml.safe_load(path.read_text()) or {}
        calls = cfg.get("calls", {})
        known.update(calls)
        known.update(s for values in calls.values() for s in (values or []))
    known.update(manifest.loc[manifest["system"].astype(str) == system,
                              "root_cause_service"].dropna().astype(str))
    return known


def _load_optional(path: Path, filename: str) -> pd.DataFrame | None:
    file = path / filename
    return pd.read_parquet(file) if file.exists() else None


def iter_cases(
    src: str = "data/processed/rcaeval",
    dataset: str | None = None,
    system: str | None = None,
    *,
    config_dir: str = "configs/systems",
) -> Iterator[Case]:
    """Yield cases from the curated RCAEval layout.

    ``dataset`` accepts manifest values such as ``RE1-OB``; ``system`` accepts
    ``ob``, ``ss`` or ``tt``. Metric time is converted to the Case index in
    epoch seconds. Non-finite metric values follow the upstream RCAEval
    preprocessing convention (forward-fill, then zero-fill). The dataset has
    no verified root-cause-indicator label, so this is always ``None``.
    """
    root = Path(src)
    manifest_path = root / "cases.parquet"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"RCAEval manifest not found: {manifest_path}")
    manifest = pd.read_parquet(manifest_path)
    required = {"case", "dataset", "system", "root_cause_service", "fault", "inject_time"}
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"RCAEval manifest missing columns: {sorted(missing)}")
    system_keys = set(manifest["system"].dropna().astype(str)) | {"ob", "ss", "tt"}
    services_by_system = {
        key: _known_services(Path(config_dir), key, manifest)
        for key in system_keys
    }
    rows = manifest
    if dataset is not None:
        rows = rows[rows["dataset"].astype(str).str.casefold() == dataset.casefold()]
    if system is not None:
        rows = rows[rows["system"].astype(str).str.casefold() == system.casefold()]
    for row in rows.itertuples(index=False):
        case_id = str(row.case)
        case_dir = root / case_id
        metrics_path = case_dir / "metrics.parquet"
        injection_path = case_dir / "inject_time.txt"
        if not metrics_path.is_file() or not injection_path.is_file():
            raise FileNotFoundError(f"Case {case_id} lacks metrics.parquet or inject_time.txt")

        raw = pd.read_parquet(metrics_path)
        if "time" not in raw.columns:
            raise ValueError(f"{metrics_path} has no 'time' column")
        times = pd.to_numeric(raw.pop("time"), errors="coerce")
        valid_time = times.notna()
        raw = raw.loc[valid_time].copy()
        times = times.loc[valid_time].astype("int64")
        if times.duplicated().any() or not times.is_monotonic_increasing:
            raise ValueError(f"{metrics_path} time values must be unique and increasing")

        known = services_by_system.get(str(row.system), set())
        other_known = set().union(*(v for k, v in services_by_system.items() if k != str(row.system)))
        columns = []
        for column in raw.columns:
            service = str(column).split("_", 1)[0]
            # Remove only columns positively identified as belonging to another
            # known RCAEval system. Preserve unknown same-system telemetry.
            if service not in other_known or service in known:
                columns.append(column)
        metrics = raw[columns].apply(pd.to_numeric, errors="coerce")
        metrics = metrics.replace([float("inf"), float("-inf")], pd.NA).ffill().fillna(0.0)
        metrics.index = pd.Index(times.astype(float), name="time")

        logs = _load_optional(case_dir, "logs.parquet")
        if logs is not None:
            logs = logs.rename(columns={"timestamp": "ts", "container_name": "service"})
        spans = _load_optional(case_dir, "traces.parquet")
        if spans is not None:
            spans = spans.rename(columns={"serviceName": "service", "spanID": "span_id",
                                          "parentSpanID": "parent_id", "traceID": "trace_id"})
            spans["service"] = spans["service"].replace({"frontendservice": "frontend"})

        t_inject = float(injection_path.read_text().strip())
        if int(t_inject) != int(row.inject_time):
            raise ValueError(f"{case_id}: manifest injection time disagrees with inject_time.txt")
        yield Case(
            case_id=case_id,
            system={"ob": "online_boutique", "ss": "sock_shop", "tt": "train_ticket"}.get(
                str(row.system), str(row.system)),
            dataset=str(row.dataset),
            fault_type=str(row.fault),
            root_cause_service=str(row.root_cause_service),
            root_cause_indicator=None,
            t_inject=t_inject,
            metrics=metrics,
            logs=logs,
            spans=spans,
            meta={"source": "curated RCAEval", "source_revision": getattr(row, "source", None),
                  "synthetic_or_real_billing": "RCAEval has no cloud billing ground truth"},
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="data/processed/rcaeval")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dataset", help="Optional manifest dataset, e.g. RE1-OB")
    ap.add_argument("--system", help="Optional system key: ob, ss, or tt")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for case in iter_cases(args.src, args.dataset, args.system):
        dest = out / case.case_id
        dest.mkdir(parents=True, exist_ok=True)
        case.metrics.rename_axis("time").reset_index().to_parquet(dest / "metrics.parquet", index=False)
        if case.logs is not None:
            case.logs.to_parquet(dest / "logs.parquet", index=False)
        if case.spans is not None:
            case.spans.to_parquet(dest / "spans.parquet", index=False)
        metadata = {"case_id": case.case_id, "system": case.system, "dataset": case.dataset,
                    "fault_type": case.fault_type, "root_cause_service": case.root_cause_service,
                    "root_cause_indicator": case.root_cause_indicator, "t_inject": case.t_inject,
                    "meta": case.meta}
        (dest / "case.json").write_text(json.dumps(metadata, indent=2) + "\n")
        count += 1
    print(f"Loaded {count} RCAEval cases into {out}")


if __name__ == "__main__":
    main()
