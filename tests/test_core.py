import numpy as np
import pandas as pd
from cloudrca.eval.metrics import ac_at_k, avg_at_k
from cloudrca.eval.stats import bootstrap_ci, paired_bootstrap, mcnemar_exact
from cloudrca.rca.shapley import exact_shapley
from cloudrca.rca.calibrate import softmax, fit_temperature, ece, brier
from cloudrca.detect.detector import first_anomaly
from cloudrca.detect.cost_spike import analyze_cost_series, detect_cost_spikes
from cloudrca.detect.cost_baseline import seasonal_ridge_expected
from cloudrca.detect.idle_resource import IdleResourcePolicy, assess_idle_resource
from cloudrca.detect.optimization import recommend_rightsize, recommend_scaling_policy
from cloudrca.detect.fleet import rank_fleet_opportunities
from cloudrca.actions.workflow import ActionWorkflow
from cloudrca.rca.m1_change import its_effect, temporal_weight
from cloudrca.ingest.synth_changes import synth_changes
from cloudrca.ingest.cost_model import usage_cost, resource_cost_breakdown
from cloudrca.ingest.rcaeval import iter_cases
from cloudrca.llm.signature import path_similarity, jaccard
from cloudrca.rca.base_baro import service_scores
from cloudrca.rca.m2_graph import allowed_edges, ranking_walk
from cloudrca.rca.m3_cost import LinearSCM, attribute_cost
from scripts.run_policy_demo import build_demo
from cloudrca.demo_dashboard import render_demo_dashboard
import networkx as nx


def test_acc():
    r = [["a", "b", "c"], ["b", "a", "c"]]
    t = ["a", "a"]
    assert ac_at_k(r, t, 1) == 0.5 and ac_at_k(r, t, 2) == 1.0
    assert 0.5 < avg_at_k(r, t, 3) <= 1.0


def test_stats():
    m, lo, hi = bootstrap_ci([1, 0, 1, 1, 0, 1] * 10)
    assert lo <= m <= hi
    d, p = paired_bootstrap([1] * 30, [0] * 30)
    assert d == 1 and p < 0.05
    assert mcnemar_exact([1, 1, 0], [1, 1, 0]) == 1.0


def test_shapley_efficiency_and_additivity():
    w = {"a": 3.0, "b": 1.0, "c": 0.0}
    phi = exact_shapley(list(w), lambda s: sum(w[x] for x in s))
    assert all(abs(phi[k] - w[k]) < 1e-9 for k in w)
    # interaction: v = 1 only when both present -> split equally, sums to v(all)
    phi = exact_shapley(["a", "b"], lambda s: 1.0 if len(s) == 2 else 0.0)
    assert abs(phi["a"] - 0.5) < 1e-9 and abs(sum(phi.values()) - 1.0) < 1e-9


def test_counterfactual_cost_attribution_is_explicit_model_estimate():
    rng = np.random.default_rng(11)
    graph = nx.DiGraph([("excess_capacity", "compute_cost")])
    pre_x = rng.normal(1.0, 0.1, 300)
    pre = pd.DataFrame({"excess_capacity": pre_x,
                        "compute_cost": 4.0 + 2.0 * pre_x + rng.normal(0, 0.05, 300)})
    post_x = rng.normal(4.0, 0.1, 100)
    post = pd.DataFrame({"excess_capacity": post_x,
                         "compute_cost": 4.0 + 2.0 * post_x + rng.normal(0, 0.05, 100)})
    scm = LinearSCM(graph).fit(pre)
    result = attribute_cost(scm, pre, post, ["excess_capacity"], cost_node="compute_cost")
    assert abs(result["phi"]["excess_capacity"] - 6.0) < 0.25
    assert result["provenance"] == "model_estimate"
    assert result["causal_identification"] == "not_established_by_model_fit_alone"
    assert "no unmodeled confounding of candidate causes and cost outcome" in result["assumptions"]


def test_counterfactual_cost_attribution_rejects_cycles_and_invalid_candidates():
    cyclic = nx.DiGraph([("a", "b"), ("b", "a")])
    with np.testing.assert_raises(ValueError):
        LinearSCM(cyclic)
    graph = nx.DiGraph([("driver", "total_cost")])
    data = pd.DataFrame({"driver": [1.0, 2.0, 1.5], "total_cost": [3.0, 5.0, 4.0]})
    scm = LinearSCM(graph).fit(data)
    with np.testing.assert_raises(ValueError):
        attribute_cost(scm, data, data, ["unknown"])


def test_resource_cost_breakdown_reconciles_and_labels_simulated_cost():
    usage = pd.DataFrame({"resource_id": ["vm-a", "vm-a", "vm-b"],
                          "cpu_cores": [1.0, 2.0, 1.0],
                          "net_tx_gb": [0.1, 0.0, 0.2]})
    prices = {"currency": "USD", "compute": {"vcpu_hour": 0.4},
              "network": {"egress_gb": 0.1}}
    result = resource_cost_breakdown(usage, 3600, group_by=["resource_id"], pricing=prices)
    assert result["provenance"] == "simulated"
    assert result["modeled_total"] == result["reconciled_total"]
    assert result["modeled_total"] == 1.63
    assert set(result["breakdown"]["resource_id"]) == {"vm-a", "vm-b"}


def test_resource_cost_breakdown_rejects_missing_dimension_and_no_components():
    usage = pd.DataFrame({"resource_id": ["vm-a"], "cpu_cores": [1.0]})
    with np.testing.assert_raises(ValueError):
        resource_cost_breakdown(usage, 3600, group_by=["service"], pricing={})
    with np.testing.assert_raises(ValueError):
        resource_cost_breakdown(pd.DataFrame({"resource_id": ["vm-a"]}), 3600,
                                group_by=["resource_id"], pricing={})


def test_policy_demo_is_repeatable_and_labels_fixture_results():
    first, second = build_demo(17), build_demo(17)
    assert first["provenance"] == "synthetic_demo_only"
    assert first["cost_spike"]["alert_count"] == second["cost_spike"]["alert_count"] == 1
    assert first["idle_resource"]["candidate"] is True
    assert first["rightsizing"]["candidate"] is True
    assert first["scaling"]["candidate"] is True
    attribution = first["controlled_cost_attribution"]
    assert attribution["provenance"] == "model_estimate"
    assert attribution["separate_from_cost_spike_scenario"] is True
    assert 23.0 < attribution["phi"]["excess_replicas"] < 25.0
    assert first["fleet_ranking"]["estimated_monthly_savings_after_overlap"] == \
           second["fleet_ranking"]["estimated_monthly_savings_after_overlap"]
    assert "not calibrated probabilities" in first["interpretation"]


def test_offline_dashboard_renders_evidence_and_blocks_unlabeled_reports():
    report = build_demo(17)
    html = render_demo_dashboard(report)
    assert "SYNTHETIC DATA ONLY" in html
    assert "Separate controlled causal-attribution example" in html
    assert "Idle / zombie resource" in html
    assert "Unnecessary scaling" in html
    assert "does not explain that spike" in html
    with np.testing.assert_raises(ValueError):
        render_demo_dashboard({"provenance": "observed"})


def test_calibration_runs():
    rng = np.random.default_rng(0)
    scores = [rng.normal(size=5) + np.eye(5)[0] * 3 for _ in range(200)]
    T = fit_temperature(scores, [0] * 200)
    conf = [softmax(s, T).max() for s in scores]
    correct = [int(np.argmax(s) == 0) for s in scores]
    assert 0 <= ece(conf, correct) <= 1 and 0 <= brier(conf, correct) <= 1


def test_detector():
    x = pd.Series(np.r_[np.random.default_rng(0).normal(0, 1, 100), np.full(10, 20.0)])
    assert first_anomaly(x, window=30) == 100


def test_cost_spike_requires_persistence_and_reports_excess():
    idx = pd.RangeIndex(6)
    expected = pd.Series([10.0] * 6, index=idx)
    actual = pd.Series([10.0, 15.0, 10.0, 15.0, 15.0, 15.0], index=idx)
    spikes = detect_cost_spikes(actual, expected, min_excess_per_period=4,
                                min_increase_pct=20, persistence=3,
                                provenance="simulated")
    assert len(spikes) == 1
    assert (spikes[0].start, spikes[0].end, spikes[0].periods) == (3, 5, 3)
    assert spikes[0].excess_cost == 15.0
    assert spikes[0].increase_pct == 50.0
    assert spikes[0].provenance == "simulated"


def test_cost_spike_zero_expected_uses_absolute_gate_and_nan_breaks_run():
    idx = pd.RangeIndex(4)
    expected = pd.Series([0.0, 0.0, 0.0, 0.0], index=idx)
    actual = pd.Series([3.0, 3.0, np.nan, 3.0], index=idx)
    spikes = detect_cost_spikes(actual, expected, min_excess_per_period=2,
                                min_increase_pct=100, persistence=2)
    assert len(spikes) == 1
    assert spikes[0].start == 0 and spikes[0].end == 1
    assert spikes[0].increase_pct is None


def test_cost_spike_rejects_misaligned_or_invalid_policy():
    a = pd.Series([1.0, 2.0], index=[0, 1])
    with np.testing.assert_raises(ValueError):
        detect_cost_spikes(a, pd.Series([1.0], index=[1]), min_excess_per_period=0)
    with np.testing.assert_raises(ValueError):
        detect_cost_spikes(a, a, min_excess_per_period=-1)


def test_seasonal_cost_baseline_fits_only_training_prefix():
    idx = pd.date_range("2026-01-01", periods=24 * 10, freq="h", tz="UTC")
    hour = idx.hour.to_numpy()
    values = 20 + 3 * np.sin(2 * np.pi * hour / 24)
    cutoff = idx[24 * 7]
    values[24 * 7:] += 15
    cost = pd.Series(values, index=idx)
    expected = seasonal_ridge_expected(cost, train_end=cutoff, min_train_samples=48)
    assert expected.iloc[:24 * 7].isna().all()
    assert expected.iloc[24 * 7:].notna().all()
    # Changing any post-cutoff actual values cannot affect the fitted baseline.
    changed = cost.copy()
    changed.loc[cutoff:] *= 10
    expected_changed = seasonal_ridge_expected(changed, train_end=cutoff, min_train_samples=48)
    np.testing.assert_allclose(expected.iloc[24 * 7:], expected_changed.iloc[24 * 7:])
    assert abs(expected.iloc[-1] - 20) < 2.0


def test_seasonal_cost_baseline_rejects_short_history():
    idx = pd.date_range("2026-01-01", periods=4, freq="h")
    cost = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)
    with np.testing.assert_raises(ValueError):
        seasonal_ridge_expected(cost, train_end=idx[3], min_train_samples=5)


def test_seasonal_cost_baseline_rejects_irregular_buckets():
    idx = pd.DatetimeIndex(["2026-01-01 00:00", "2026-01-01 01:00",
                            "2026-01-01 03:00", "2026-01-01 04:00"])
    cost = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)
    with np.testing.assert_raises(ValueError):
        seasonal_ridge_expected(cost, train_end=idx[3], min_train_samples=2)


def test_cost_analysis_runs_baseline_through_spike_detector():
    idx = pd.date_range("2026-01-01", periods=24 * 10, freq="h", tz="UTC")
    values = 30 + 4 * np.sin(2 * np.pi * idx.hour.to_numpy() / 24)
    cutoff = idx[24 * 7]
    values[24 * 7:] += 20
    result = analyze_cost_series(
        pd.Series(values, index=idx), train_end=cutoff,
        min_excess_per_period=8, min_increase_pct=20,
        persistence=6, min_train_samples=48, provenance="simulated",
    )
    assert result["method"] == "seasonal_ridge_past_only"
    assert result["expected"].iloc[:24 * 7].isna().all()
    assert result["alerts"]
    assert result["alerts"][0].provenance == "simulated"
    assert result["alerts"][0].excess_cost > 0


def test_idle_resource_requires_independent_workload_evidence_and_safety():
    idx = pd.date_range("2026-01-01", periods=24 * 15, freq="h", tz="UTC")
    cpu = 15 + 5 * np.sin(2 * np.pi * idx.hour.to_numpy() / 24)
    cpu[-24:] = 2.0
    requests = np.ones(len(idx))
    network = np.full(len(idx), 0.5)
    requests[-24:] = 0.0
    network[-24:] = 0.0
    telemetry = pd.DataFrame({"cpu_pct": cpu, "memory_pct": 75.0,
                              "requests_per_second": requests, "network_mbps": network}, index=idx)
    policy = IdleResourcePolicy(minimum_history_samples=48)
    assessed = assess_idle_resource(
        "vm-07", telemetry, billable_active=True, hourly_compute_rate=0.5,
        business_critical=False, scheduled_active=False, active_jobs=False,
        dependencies_clear=True, owner="analytics", policy=policy,
    )
    assert assessed["candidate"] is True
    assert assessed["evidence"]["cpu_idle_ratio"] == 1.0
    assert assessed["evidence"]["seasonal_baseline_used"] is True
    assert assessed["estimated_cost_impact"]["amount"] == 12.0
    assert assessed["safety"]["safe_to_propose_stop"] is True
    assert assessed["safety"]["approval_required"] is True

    # The same low CPU must not trigger when workload remains active.
    active_work = telemetry.copy()
    active_work.loc[active_work.index[-24:], "requests_per_second"] = 1.0
    suppressed = assess_idle_resource(
        "vm-07", active_work, billable_active=True, policy=policy,
    )
    assert suppressed["candidate"] is False
    assert suppressed["reasons_not_flagged"]


def test_idle_resource_blocks_stop_recommendation_when_safety_is_unknown():
    idx = pd.date_range("2026-01-01", periods=24 * 15, freq="h", tz="UTC")
    cpu = 15 + 5 * np.sin(2 * np.pi * idx.hour.to_numpy() / 24)
    cpu[-24:] = 2.0
    req = np.ones(len(idx)); req[-24:] = 0.0
    telemetry = pd.DataFrame({"cpu_pct": cpu, "memory_pct": 40.0,
                              "requests_per_second": req}, index=idx)
    result = assess_idle_resource("vm-unknown", telemetry, billable_active=True,
                                  policy=IdleResourcePolicy(minimum_history_samples=48))
    assert result["candidate"] is True
    assert result["safety"]["safe_to_propose_stop"] is False
    assert result["safety"]["approval_required"] is True


def test_idle_resource_rejects_cpu_only_evidence():
    idx = pd.date_range("2026-01-01", periods=30, freq="h")
    telemetry = pd.DataFrame({"cpu_pct": 1.0, "memory_pct": 30.0}, index=idx)
    with np.testing.assert_raises(ValueError):
        assess_idle_resource("vm-1", telemetry, billable_active=True)


def test_idle_policy_loads_configured_thresholds():
    policy = IdleResourcePolicy.from_config({"idle_resource": {"cpu_floor_pct": 4.0,
                                                                  "minimum_window_samples": 8}})
    assert policy.cpu_floor_pct == 4.0
    assert policy.minimum_window_samples == 8


def test_rightsizing_selects_compatible_capacity_and_calculates_catalog_savings():
    idx = pd.date_range("2026-01-01", periods=24 * 7 + 1, freq="h", tz="UTC")
    telemetry = pd.DataFrame({"cpu_pct": 30.0, "memory_working_set_gb": 5.0,
                              "p95_latency_ms": 60.0, "error_rate_pct": 0.1}, index=idx)
    catalog = [
        {"instance_type": "c8", "vcpu": 8, "memory_gb": 32, "hourly_price": 2.0,
         "price_unit": "instance_hour", "currency": "USD",
         "family": "compute", "region": "r1", "architecture": "x86", "cpu_credit_model": None},
        {"instance_type": "c4", "vcpu": 4, "memory_gb": 8, "hourly_price": 1.0,
         "price_unit": "instance_hour", "currency": "USD",
         "family": "compute", "region": "r1", "architecture": "x86", "cpu_credit_model": None},
        {"instance_type": "m2", "vcpu": 2, "memory_gb": 16, "hourly_price": 0.5,
         "price_unit": "instance_hour", "currency": "USD",
         "family": "memory", "region": "r1", "architecture": "x86", "cpu_credit_model": None},
    ]
    result = recommend_rightsize(
        "vm-a", telemetry, current_instance="c8", catalog=catalog,
        catalog_version="fixture-2026-01", currency="USD", latency_slo_ms=100,
        error_slo_pct=1.0, transition_cost=50.0,
    )
    assert result["candidate"] is True
    assert result["proposed_instance"] == "c4"
    assert result["estimated_savings"]["gross_monthly"] == 730.0
    assert result["estimated_savings"]["net_first_month"] == 680.0
    assert result["safety"]["approval_required"] is True
    assert result["estimated_savings"]["verified"] is False


def test_rightsizing_slo_breach_blocks_candidate():
    idx = pd.date_range("2026-01-01", periods=24 * 7 + 1, freq="h")
    telemetry = pd.DataFrame({"cpu_pct": 20.0, "memory_working_set_gb": 4.0,
                              "p95_latency_ms": 150.0, "error_rate_pct": 0.1}, index=idx)
    catalog = [{"instance_type": "c8", "vcpu": 8, "memory_gb": 32, "hourly_price": 2,
                "price_unit": "instance_hour", "currency": "USD",
                "family": "c", "region": "r1", "architecture": "x86", "cpu_credit_model": None},
               {"instance_type": "c4", "vcpu": 4, "memory_gb": 8, "hourly_price": 1,
                "price_unit": "instance_hour", "currency": "USD",
                "family": "c", "region": "r1", "architecture": "x86", "cpu_credit_model": None}]
    result = recommend_rightsize("vm-a", telemetry, current_instance="c8", catalog=catalog,
                                 catalog_version="v1", currency="USD", latency_slo_ms=100,
                                 error_slo_pct=1)
    assert result["candidate"] is False
    assert result["evidence"]["slo_pass"] is False


def test_scaling_counterfactual_requires_validated_model_and_billed_capacity_release():
    idx = pd.date_range("2026-01-01", periods=24 * 7 + 1, freq="h", tz="UTC")
    telemetry = pd.DataFrame({"requests_per_second": 1000.0, "replicas": 20,
                              "cpu_pct": 50.0, "memory_pct": 60.0,
                              "p95_latency_ms": 80.0, "error_rate_pct": 0.1}, index=idx)
    base = dict(service_id="checkout", telemetry=telemetry, minimum_replicas=5,
                safe_rps_per_replica=100, capacity_model_version="loadtest-7",
                capacity_model_validated=True,
                scaling_configuration={"min_replicas": 5, "max_replicas": 20,
                                       "target_cpu_utilization_pct": 70},
                scaling_events=[], resource_requests={"cpu_request_cores": 0.5,
                                                      "memory_request_gb": 1.0,
                                                      "cpu_limit_cores": 1.0,
                                                      "memory_limit_gb": 2.0},
                latency_slo_ms=100, error_slo_pct=1,
                reduces_billable_capacity=False)
    result = recommend_scaling_policy(**base)
    assert result["candidate"] is True
    assert result["modeled_safe_replicas"] == 13
    assert result["estimated_savings"]["gross_monthly"] is None
    paid = recommend_scaling_policy(**(base | {"reduces_billable_capacity": True,
                                                "marginal_billable_rate_per_replica_hour": 0.2}))
    assert abs(paid["estimated_savings"]["gross_monthly"] - 1022.0) < 1e-9
    unvalidated = recommend_scaling_policy(**(base | {"capacity_model_validated": False,
                                                       "reduces_billable_capacity": True,
                                                       "marginal_billable_rate_per_replica_hour": 0.2}))
    assert unvalidated["candidate"] is False
    assert unvalidated["estimated_savings"]["gross_monthly"] is None


def test_fleet_ranking_deduplicates_overlap_and_excludes_unestimated_savings():
    opportunities = [
        {"resource_id": "vm-a", "alert_type": "overprovisioned_vm",
         "estimated_monthly_savings": 100.0, "evidence_score": 0.8, "operational_risk": 0.1,
         "overlap_group": "service-a-capacity"},
        {"resource_id": "svc-a", "alert_type": "unnecessary_resource_scaling",
         "estimated_monthly_savings": 80.0, "evidence_score": 0.9, "operational_risk": 0.2,
         "overlap_group": "service-a-capacity"},
        {"resource_id": "vm-b", "alert_type": "overprovisioned_vm",
         "estimated_monthly_savings": None},
        {"resource_id": "vm-c", "alert_type": "overprovisioned_vm",
         "estimated_monthly_savings": 50.0, "evidence_score": 0.7,
         "operational_risk": 0.3},
    ]
    result = rank_fleet_opportunities(opportunities, currency="USD")
    assert result["estimated_monthly_savings_after_overlap"] == 150.0
    assert result["selected_opportunities"] == 2
    assert result["excluded_without_positive_monthly_estimate"] == 1
    assert result["overlap_groups_with_multiple_candidates"] == 1
    assert result["opportunities"][0]["resource_id"] == "vm-a"


def test_action_workflow_requires_allowlisted_approval_and_only_simulates(tmp_path):
    workflow = ActionWorkflow(tmp_path / "actions.db", authorized_approvers={"reviewer@example.test"})
    kwargs = dict(idempotency_key="idem-001", recommendation_id="rec-1", resource_id="vm-a",
                  alert_type="overprovisioned_vm", action_kind="resize_vm",
                  payload={"from": "c8", "to": "c4"})
    planned = workflow.plan(**kwargs)
    assert planned["status"] == "planned"
    assert workflow.plan(**kwargs)["action_id"] == planned["action_id"]
    with np.testing.assert_raises(PermissionError):
        workflow.approve(planned["action_id"], "unlisted@example.test")
    with np.testing.assert_raises(ValueError):
        workflow.run_dry_run(planned["action_id"])
    approved = workflow.approve(planned["action_id"], "reviewer@example.test")
    assert approved["status"] == "approved"
    dry_run = workflow.run_dry_run(planned["action_id"])
    assert dry_run["status"] == "dry_run_complete"
    assert dry_run["outcome"]["executed"] is False
    result = workflow.record_simulated_verification(
        planned["action_id"], {"policy_check": True, "slo_check": False})
    assert result["status"] == "simulation_failed"
    assert result["outcome"]["live_change_verified"] is False
    rolled_back = workflow.record_simulated_rollback(planned["action_id"], "SLO check failed")
    assert rolled_back["status"] == "simulated_rolled_back"
    assert rolled_back["outcome"]["live_resource_changed"] is False
    assert [event["event"] for event in result["audit"]] == [
        "planned", "approved", "dry_run_complete", "simulation_failed"]


def test_action_workflow_rejects_secret_fields_and_idempotency_conflicts(tmp_path):
    workflow = ActionWorkflow(tmp_path / "actions.db", authorized_approvers={"reviewer"})
    base = dict(idempotency_key="idem-2", recommendation_id="rec", resource_id="vm",
                alert_type="idle_zombie_compute", action_kind="schedule_stop")
    with np.testing.assert_raises(ValueError):
        workflow.plan(**base, payload={"access_token": "do-not-store"})
    created = workflow.plan(**base, payload={"schedule": "business-hours"})
    with np.testing.assert_raises(ValueError):
        workflow.plan(**(base | {"resource_id": "different-vm"}),
                      payload={"schedule": "business-hours"})


def test_rcaeval_loader_reads_manifest_and_filters_foreign_service(tmp_path):
    root = tmp_path / "rcaeval"
    case_dir = root / "re1ob_checkoutservice_cpu_1"
    case_dir.mkdir(parents=True)
    pd.DataFrame({"time": [100, 101, 102], "checkoutservice_cpu": [0.2, np.nan, 0.4],
                  "ts-order-service_cpu": [9.0, 9.0, 9.0]}).to_parquet(case_dir / "metrics.parquet")
    (case_dir / "inject_time.txt").write_text("101\n")
    pd.DataFrame([{"case": "re1ob_checkoutservice_cpu_1", "dataset": "RE1-OB", "system": "ob",
                   "root_cause_service": "checkoutservice", "fault": "cpu", "inject_time": 101,
                   "source": "hf"}]).to_parquet(root / "cases.parquet", index=False)
    cfg = tmp_path / "systems"
    cfg.mkdir()
    (cfg / "ob.yaml").write_text("calls: {checkoutservice: []}\n")
    (cfg / "tt.yaml").write_text("calls: {ts-order-service: []}\n")

    cases = list(iter_cases(str(root), config_dir=str(cfg)))
    assert len(cases) == 1
    case = cases[0]
    assert case.system == "online_boutique" and case.dataset == "RE1-OB"
    assert case.t_inject == 101.0 and case.root_cause_indicator is None
    assert list(case.metrics.columns) == ["checkoutservice_cpu"]
    assert case.metrics.iloc[:, 0].tolist() == [0.2, 0.2, 0.4]


def test_its_detects_step_and_ignores_noise():
    rng = np.random.default_rng(1)
    t = np.arange(200.0)
    step = pd.Series(rng.normal(0, 1, 200) + 8 * (t >= 100), index=t)
    flat = pd.Series(rng.normal(0, 1, 200), index=t)
    assert its_effect(step, 100)["p"] < 1e-3
    assert its_effect(flat, 100)["p"] > 0.01
    assert temporal_weight(100, 120, 300) == 0.0 and temporal_weight(100, 40, 300) > 0


def test_synth_changes_deterministic_and_no_leak_on_resource_faults():
    a = synth_changes("c1", "cpu", "svcA", ["svcA", "svcB", "svcC"], 1000.0, seed=3, lambda_decoy=4)
    b = synth_changes("c1", "cpu", "svcA", ["svcA", "svcB", "svcC"], 1000.0, seed=3, lambda_decoy=4)
    assert a.equals(b)
    assert not (a.service == "svcA").any()          # decoys never on the root service
    code = synth_changes("c2", "code", "svcA", ["svcA", "svcB"], 1000.0, seed=3, lambda_decoy=0, p_miss=0)
    assert len(code) == 1 and not code.is_decoy.iloc[0]


def test_cost_model_drops_missing_terms():
    pricing = dict(compute=dict(vcpu_hour=2.0, gb_ram_hour=0.5),
                   storage=dict(iops_month=0.1), network=dict(egress_gb=1.0),
                   requests=dict(per_million_requests=10.0))
    u = pd.DataFrame(dict(cpu_cores=[1.0, 2.0]))
    c = usage_cost(u, dt_s=3600, pricing=pricing)
    assert list(c.columns) == ["cpu"] and c["cpu"].tolist() == [2.0, 4.0]


def test_signature_helpers():
    assert path_similarity(("a", "b"), ("a", "b")) == 1.0
    assert jaccard({"cpu"}, {"cpu", "mem"}) == 0.5


def test_base_scorer_finds_shifted_service():
    rng = np.random.default_rng(0)
    idx = np.arange(300.0)
    df = pd.DataFrame({"svcA_cpu": rng.normal(0, 1, 300), "svcB_cpu": rng.normal(0, 1, 300)}, index=idx)
    df.loc[idx >= 200, "svcB_cpu"] += 10
    s = service_scores(df, 200.0, ["svcA", "svcB"])
    assert s.idxmax() == "svcB"


def test_m2_edges_and_walk():
    e = allowed_edges({"fe": ["db"]}, {"fe": {"latency"}, "db": {"cpu", "latency"}})
    assert (("db", "cpu"), ("fe", "latency")) in e and (("db", "cpu"), ("db", "latency")) in e
    G = nx.DiGraph([("db_cpu", "fe_lat")])
    r = ranking_walk(G, {"fe_lat": 5.0})
    assert r["db_cpu"] > 0
