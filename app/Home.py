"""Presentation dashboard for the saved FinOps policy demo report."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "results" / "demo" / "policy_demo.json"


def _money(value, currency="USD"):
    return "Unavailable" if value is None else f"{currency} {float(value):,.2f}"


st.set_page_config(page_title="FinOps Causal RCA", layout="wide")
st.title("FinOps for Cloud with Causal Root Cause Analysis")
st.caption("Research prototype · evidence-gated cost optimization")

report_path = Path(st.sidebar.text_input("Demo report", str(DEFAULT_REPORT))).expanduser()
if not report_path.is_absolute():
    report_path = ROOT / report_path
if not report_path.is_file():
    st.warning("No demo report found. Generate the deterministic fixture with `./.venv/bin/python scripts/run_policy_demo.py`.")
    st.stop()

try:
    report = json.loads(report_path.read_text())
except (OSError, json.JSONDecodeError) as exc:
    st.error(f"Could not read report: {exc}")
    st.stop()

if report.get("provenance") != "synthetic_demo_only":
    st.error("This view is configured for explicitly labeled demo reports; provenance is missing or unexpected.")
    st.stop()

st.warning(
    "SYNTHETIC DEMO DATA: telemetry, prices and capacity inputs are fixtures. "
    "Savings are estimates, not measured results. No cloud actions were executed."
)

spikes = report.get("cost_spike", {}).get("alerts", [])
fleet = report.get("fleet_ranking", {})
currency = fleet.get("currency", "USD")
total_excess = sum(float(item.get("excess_cost", 0)) for item in spikes)
monthly_savings = fleet.get("estimated_monthly_savings_after_overlap")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Persistent modeled cost spikes", len(spikes))
col2.metric("Modeled excess in detected intervals", _money(total_excess, currency))
col3.metric("Fleet monthly savings estimate", _money(monthly_savings, currency))
col4.metric("Resources / services assessed", 3)

st.subheader("Cost spike evidence")
if not spikes:
    st.info("No persistent cost spike met the configured demo thresholds.")
else:
    st.dataframe([{
        "Start": str(item.get("start")),
        "End": str(item.get("end")),
        "Periods": item.get("periods"),
        "Actual cost": item.get("actual_cost"),
        "Expected cost": item.get("expected_cost"),
        "Excess cost": item.get("excess_cost"),
        "Increase %": item.get("increase_pct"),
        "Provenance": item.get("provenance"),
    } for item in spikes], use_container_width=True, hide_index=True)

st.subheader("Controlled cost-attribution example")
attribution = report.get("controlled_cost_attribution", {})
if attribution:
    st.info("This separately injected SCM example demonstrates counterfactual allocation; it does not explain the cost-spike scenario above.")
    attr_cols = st.columns(3)
    attr_cols[0].metric("Observed synthetic cost delta", _money(
        attribution.get("observed_delta_cost"), "USD / bucket"))
    allocation = attribution.get("phi", {}).get(attribution.get("injected_cause"))
    attr_cols[1].metric("Model-attributed effect", _money(allocation, "USD / bucket"))
    attr_cols[2].metric("Unexplained model residual", _money(
        attribution.get("modeled_unexplained"), "USD / bucket"))
    with st.expander("SCM definition and identification assumptions"):
        st.write(f"Value function: {attribution.get('value_function')}")
        st.write("Assumptions")
        st.write(attribution.get("assumptions", []))
        st.caption(f"Status: {attribution.get('causal_identification')}; provenance: {attribution.get('provenance')}")
else:
    st.info("No controlled attribution fixture is present in this report.")

st.subheader("Primary cost optimization alerts")
alert_specs = [
    ("Idle / zombie resource", "idle_resource", "estimated_cost_impact"),
    ("Overprovisioned VM", "rightsizing", "estimated_savings"),
    ("Unnecessary scaling", "scaling", "estimated_savings"),
]
cards = st.columns(3)
for col, (label, key, estimate_key) in zip(cards, alert_specs):
    item = report.get(key, {})
    estimate = item.get(estimate_key, {})
    amount = estimate.get("gross_monthly")
    if amount is None:
        amount = estimate.get("amount")
    with col:
        st.markdown(f"### {label}")
        st.metric("Policy result", "Candidate" if item.get("candidate") else "No candidate")
        st.write(item.get("recommended_action", "No action recommendation"))
        st.caption(f"Estimated impact: {_money(amount, estimate.get('currency') or currency)}")
        st.caption(f"Confidence: {item.get('confidence_status', 'not reported')}")
        with st.expander("Evidence and safety"):
            st.json({"evidence": item.get("evidence", {}),
                     "safety": item.get("safety", {}),
                     "estimated_savings": estimate})

st.subheader("Fleet opportunities")
opportunities = fleet.get("opportunities", [])
if opportunities:
    st.dataframe([{
        "Resource": item.get("resource_id"),
        "Alert": item.get("alert_type"),
        "Monthly estimate": item.get("estimated_monthly_savings"),
        "Priority score (heuristic)": item.get("priority_score"),
        "Overlap group": item.get("overlap_group"),
        "Evidence score (uncalibrated)": item.get("evidence_score"),
        "Operational risk (heuristic)": item.get("operational_risk"),
    } for item in opportunities], use_container_width=True, hide_index=True)
    st.caption(fleet.get("priority_policy", "Priority policy unavailable"))
else:
    st.info("The report contains no rankable positive monthly savings estimates.")

with st.expander("Method and research limitations"):
    st.write(report.get("interpretation", "Limitations were not supplied in the report."))
    st.markdown(
        "- Cost-spike detection flags deviation from a past-only seasonal Ridge baseline; it does not establish a cause.\n"
        "- SCM/Shapley output is a model counterfactual and requires causal identification assumptions.\n"
        "- Approval workflow is local simulation only; this dashboard has no cloud write controls.\n"
        "- RCAEval supports service-level RCA, not cloud billing ground truth."
    )
