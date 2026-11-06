"""Simulated cost from resource usage (plan §2.4). NOT real billing.
Missing metric terms are dropped, never imputed; `components_used` is returned so
the paper can state exactly which terms entered each dataset's cost."""
from __future__ import annotations
import numpy as np
import pandas as pd
from cloudrca.config import load

# usage column -> (pricing key path, unit conversion handled below)
COMPONENTS = ["cpu", "mem", "iops", "net_tx", "requests"]


def usage_cost(usage: pd.DataFrame, dt_s: float, pricing: dict | None = None) -> pd.DataFrame:
    """usage columns (any subset): cpu_cores, mem_gb, iops, net_tx_gb, requests.
    Returns per-component INR per row (time step of dt_s seconds)."""
    p = pricing or load("configs/pricing.yaml")
    need = {
        "cpu": ("cpu_cores", lambda u: p["compute"]["vcpu_hour"] * u * dt_s / 3600),
        "mem": ("mem_gb", lambda u: p["compute"]["gb_ram_hour"] * u * dt_s / 3600),
        "iops": ("iops", lambda u: p["storage"]["iops_month"] * u * dt_s / (30 * 24 * 3600)),
        "net_tx": ("net_tx_gb", lambda u: p["network"]["egress_gb"] * u),
        "requests": ("requests", lambda u: p["requests"]["per_million_requests"] * u / 1e6),
    }
    out = {}
    for comp, (col, fn) in need.items():
        if col not in usage.columns:
            continue
        try:
            out[comp] = fn(usage[col])
        except TypeError as e:  # price still null in pricing.yaml
            raise ValueError(f"pricing for '{comp}' is not filled in configs/pricing.yaml") from e
    res = pd.DataFrame(out, index=usage.index)
    res.attrs["components_used"] = list(res.columns)
    return res


def resource_cost_breakdown(usage: pd.DataFrame, dt_s: float, *,
                           group_by: list[str], pricing: dict) -> dict:
    """Account modeled usage cost by explicit resource dimensions.

    The returned components use the same documented formulas as ``usage_cost``;
    grouping dimensions (for example provider/account/resource/service/region)
    must be present in ``usage``. This reports modeled cost only, not a provider
    invoice. Rows with missing dimensions are rejected so totals cannot silently
    disappear from a breakdown. Component totals reconcile to the row-level
    modeled total up to floating-point rounding.
    """
    if not group_by or len(set(group_by)) != len(group_by):
        raise ValueError("group_by must contain unique dimension columns")
    missing = set(group_by) - set(usage.columns)
    if missing:
        raise ValueError(f"usage is missing grouping dimensions: {sorted(missing)}")
    if usage.empty:
        raise ValueError("usage must contain at least one row")
    if usage[group_by].isna().any().any():
        raise ValueError("grouping dimensions cannot contain missing values")
    components = usage_cost(usage, dt_s, pricing)
    if components.empty:
        raise ValueError("usage contains no supported billable usage columns")
    if not np.isfinite(components.to_numpy(dtype=float)).all() or (components < 0).any().any():
        raise ValueError("modeled costs must be finite and non-negative")
    rows = usage[group_by].reset_index(drop=True).join(components.reset_index(drop=True))
    component_names = list(components.columns)
    rows["modeled_cost"] = rows[component_names].sum(axis=1)
    grouped = rows.groupby(group_by, dropna=False, sort=True)[component_names + ["modeled_cost"]].sum().reset_index()
    total = float(rows["modeled_cost"].sum())
    reconciled = float(grouped["modeled_cost"].sum())
    if not np.isclose(total, reconciled, rtol=1e-10, atol=1e-9):
        raise ArithmeticError("grouped modeled costs failed reconciliation")
    return {"breakdown": grouped, "currency": pricing.get("currency"),
            "provenance": "simulated", "components_used": component_names,
            "modeled_total": total, "reconciled_total": reconciled,
            "reconciliation_difference": reconciled - total,
            "billing_basis": "usage proxy formulas in cloudrca.ingest.cost_model; not provider invoice"}


def provisioned_cost(cpu_util: pd.Series, instance_hour: float, dt_s: float,
                     base_replicas: int = 1, threshold: float = 0.7, max_replicas: int = 10) -> pd.Series:
    """Step-shaped cost: replicas scale up when per-replica CPU util > threshold."""
    replicas, out = base_replicas, []
    total_load = cpu_util * base_replicas
    for load_t in total_load:
        while load_t / replicas > threshold and replicas < max_replicas:
            replicas += 1
        out.append(replicas * instance_hour * dt_s / 3600)
    return pd.Series(out, index=cpu_util.index)
