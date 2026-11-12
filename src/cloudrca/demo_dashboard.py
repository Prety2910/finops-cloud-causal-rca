"""Render the saved synthetic policy demo as a self-contained HTML dashboard."""
from __future__ import annotations

from html import escape
import json
from typing import Any


def _money(amount: Any, currency: str = "USD") -> str:
    if amount is None:
        return "Unavailable"
    return f"{escape(currency)} {float(amount):,.2f}"


def render_demo_dashboard(report: dict) -> str:
    """Return an offline, dependency-free dashboard for the demo report."""
    if report.get("provenance") != "synthetic_demo_only":
        raise ValueError("dashboard accepts only reports labeled synthetic_demo_only")
    spikes = report.get("cost_spike", {}).get("alerts", [])
    fleet = report.get("fleet_ranking", {})
    currency = fleet.get("currency") or "USD"
    excess = sum(float(item.get("excess_cost") or 0) for item in spikes)
    total_savings = fleet.get("estimated_monthly_savings_after_overlap")
    categories = [
        ("Idle / zombie resource", "idle_resource", "estimated_cost_impact"),
        ("Overprovisioned VM", "rightsizing", "estimated_savings"),
        ("Unnecessary scaling", "scaling", "estimated_savings"),
    ]
    cards = []
    for title, key, estimate_key in categories:
        item = report.get(key, {})
        estimate = item.get(estimate_key, {})
        amount = estimate.get("gross_monthly", estimate.get("amount"))
        status = "Candidate" if item.get("candidate") else "No candidate"
        evidence = escape(json.dumps({"evidence": item.get("evidence", {}),
            "safety": item.get("safety", {}), "estimated_impact": estimate}, indent=2, default=str))
        cards.append(f"""<article class="card"><div class="eyebrow">PRIMARY ALERT</div>
<h2>{escape(title)}</h2><span class="status">{status}</span>
<p>{escape(str(item.get('recommended_action', 'No recommendation supplied.')))}</p>
<p><b>Estimated impact:</b> {_money(amount, estimate.get('currency') or currency)}</p>
<p class="muted">Confidence: {escape(str(item.get('confidence_status', 'not reported')))}</p>
<details><summary>Evidence and safety checks</summary><pre>{evidence}</pre></details></article>""")

    spike_rows = []
    for spike in spikes:
        spike_rows.append("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in (
            spike.get("start"), spike.get("end"), spike.get("periods"),
            _money(spike.get("actual_cost"), currency),
            _money(spike.get("expected_cost"), currency),
            _money(spike.get("excess_cost"), currency),
            f"{spike.get('increase_pct'):.1f}%" if spike.get("increase_pct") is not None else "N/A",
        )) + "</tr>")

    opportunities = fleet.get("opportunities", [])
    fleet_rows = []
    for item in opportunities:
        fleet_rows.append("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in (
            item.get("resource_id"), item.get("alert_type"),
            _money(item.get("estimated_monthly_savings"), currency),
            f"{float(item.get('priority_score', 0)):.2f}",
            item.get("overlap_group"),
        )) + "</tr>")

    attribution = report.get("controlled_cost_attribution", {})
    cause = attribution.get("injected_cause", "cause")
    attributed = attribution.get("phi", {}).get(cause)
    attribution_html = f"""<section class="panel"><h2>Separate synthetic SCM attribution illustration</h2>
<p>This injected SCM scenario is separate from the cost-spike series; it does not explain that spike.</p>
<p><b>Interpretation:</b> this illustrates model-based allocation under the fixture's assumed graph and injected mechanism. It does not establish a real-world causal effect.</p>
<div class="kpis"><div><span>Synthetic fixture cost delta</span><b>{_money(attribution.get('observed_delta_cost'), 'USD / bucket')}</b></div>
<div><span>SCM allocation for {escape(str(cause))}</span><b>{_money(attributed, 'USD / bucket')}</b></div>
<div><span>Unexplained model residual</span><b>{_money(attribution.get('modeled_unexplained'), 'USD / bucket')}</b></div></div>
<details><summary>Value function and identification assumptions</summary>
<p>{escape(str(attribution.get('value_function', 'Not supplied')))}</p>
<pre>{escape(json.dumps(attribution.get('assumptions', []), indent=2))}</pre></details></section>""" if attribution else ""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FinOps Demo Dashboard</title>
<style>
:root{{--bg:#f3f6fb;--ink:#162238;--muted:#61718a;--line:#dce4ef;--blue:#2457c5;--white:#fff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1220px;margin:auto;padding:30px 22px 60px}}h1{{font-size:32px;margin:0}}h2{{font-size:20px;margin:6px 0 12px}}
.sub,.muted{{color:var(--muted)}}.banner{{margin:22px 0;padding:14px 18px;background:#fff4d6;border:1px solid #ebcd77;border-radius:12px;color:#694f08;font-weight:650}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0 26px}}.kpis>div,.panel,.card{{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 3px 12px #243c6010}}
.kpis span{{display:block;color:var(--muted);font-size:13px}}.kpis b{{display:block;font-size:23px;margin-top:7px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
.eyebrow{{font-size:11px;letter-spacing:.1em;color:var(--blue);font-weight:750}}.status{{display:inline-block;background:#e9f3ed;color:#17643a;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:700}}
section{{margin-top:26px}}table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden}}th,td{{padding:11px 12px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}}th{{background:#edf2f9;color:#42536d}}
details{{margin-top:12px}}summary{{cursor:pointer;color:var(--blue);font-weight:650}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;border-radius:9px;padding:12px;font-size:12px;max-height:390px;overflow:auto}}
.panel{{margin-top:18px}}footer{{color:var(--muted);font-size:12px;margin-top:30px}}@media(max-width:850px){{.grid{{grid-template-columns:1fr}}.kpis{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<div class="eyebrow">RESEARCH PROTOTYPE · FINOPS</div><h1>FinOps for Cloud with Causal Root Cause Analysis</h1>
<p class="sub">Offline dashboard generated from a fixed-seed policy demonstration report.</p>
<div class="banner">SYNTHETIC DATA ONLY — no real cloud bill, calibrated probability, executed action, or verified savings.</div>
<div class="kpis"><div><span>Persistent cost-spike intervals</span><b>{len(spikes)}</b></div>
<div><span>Excess in detected intervals</span><b>{_money(excess, currency)}</b></div>
<div><span>Fleet monthly savings estimate</span><b>{_money(total_savings, currency)}</b></div>
<div><span>Primary policies assessed</span><b>3</b></div></div>
<section><h2>Cost-spike evidence</h2><div style="overflow:auto"><table><thead><tr><th>Start</th><th>End</th><th>Periods</th><th>Actual</th><th>Expected</th><th>Excess</th><th>Increase</th></tr></thead>
<tbody>{''.join(spike_rows) if spike_rows else '<tr><td colspan="7">No intervals detected</td></tr>'}</tbody></table></div></section>
<section><h2>Primary cost alerts</h2><div class="grid">{''.join(cards)}</div></section>
{attribution_html}
<section><h2>Fleet opportunities</h2><div style="overflow:auto"><table><thead><tr><th>Resource</th><th>Alert</th><th>Monthly estimate</th><th>Priority heuristic</th><th>Overlap group</th></tr></thead>
<tbody>{''.join(fleet_rows) if fleet_rows else '<tr><td colspan="5">No rankable opportunities</td></tr>'}</tbody></table>
<p class="muted">{escape(str(fleet.get('priority_policy', 'Priority policy unavailable')))}</p></section>
<section class="panel"><h2>Data provenance and limits</h2>
<p><b>CloudTrail:</b> {escape(str(report.get('data_sources', {}).get('cloudtrail', {}).get('note', 'No CloudTrail provenance supplied.')))}</p>
<p><b>Cost data:</b> {escape(str(report.get('data_sources', {}).get('cost', 'Not reported.')))}</p>
<p><b>Utilization data:</b> {escape(str(report.get('data_sources', {}).get('utilization', 'Not reported.')))}</p>
<p>{escape(str(report.get('interpretation', 'No interpretation supplied.')))}</p>
<p>RCAEval is for service-level RCA and does not supply cloud billing ground truth. Model-based causal estimates depend on a justified graph and defensible identification assumptions; this synthetic example does not establish causality. The action workflow is simulated; this page cannot modify cloud resources.</p></section>
<footer>Generated locally from {escape(str(report.get('provenance')))} · Seed {escape(str(report.get('seed')))} · For demonstration only</footer>
</main></body></html>"""
