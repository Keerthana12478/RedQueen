"""Gate tests exercise computed outcomes, boundaries and capability budgets."""
from unittest.mock import Mock

import pandas as pd
import pytest

from redqueen.baseline import BaselineDetector
from redqueen.config import Settings
from redqueen.replay import list_replay_scenarios, load_replay_validated
from redqueen.schemas import DefenseRule
from redqueen.simulator import DEFAULT_DEMO_SPEC, generate_datasets
from redqueen.verification import (SandboxState, SandboxActivationError, SealedAlreadyEvaluated,
    ValidationBudgetExceeded, VerificationGate)


@pytest.fixture(scope="module")
def demo():
    return generate_datasets(DEFAULT_DEMO_SPEC, 1337, Settings())


def rule(*clauses):
    return DefenseRule(clauses=list(clauses), action="FLAG", rationale="test")


def evaluate(candidate, data, **kwargs):
    return VerificationGate(spec=DEFAULT_DEMO_SPEC, **kwargs).evaluate_final(candidate, data, BaselineDetector(), [])


def good():
    return load_replay_validated("GiftCardNightBurst")["proposed_rule"]


def test_good_rule_and_auditable_metrics(demo):
    report = evaluate(good(), demo)
    assert report.verdict == "ACCEPTED", report.reason
    assert all(c.passed for c in report.checks)
    assert report.sealed_evaluated and report.target_fraud_count > 0
    assert report.recall_gain_pp == (report.target_patched_recall-report.target_baseline_recall)*100
    assert report.legit_flagged_per_10k == report.patched.fpr*10000
    assert report.patched.tp >= report.baseline.tp
    assert report.latency_ms < 3000


@pytest.mark.parametrize("candidate,first", [
    (rule({"field":"amount", "op":">=", "val":1}), "global_fpr"),
    (rule({"field":"amount", "op":">=", "val":49999}), "target_recall_gain"),
])
def test_broad_and_useless_rejected(demo, candidate, first):
    report = evaluate(candidate, demo)
    assert report.verdict == "REJECTED" and report.reason.startswith(first)


def test_segment_only_violation():
    fixture = load_replay_validated("CryptoNewAccountBurst")
    settings = Settings()
    data = generate_datasets(fixture["attack_spec"], settings.seed, settings)
    report = VerificationGate(settings, fixture["attack_spec"]).evaluate_final(fixture["proposed_rule"], data, BaselineDetector(), [])
    assert report.verdict == "REJECTED" and report.reason.startswith("segment_fpr")
    assert report.patched.fpr <= settings.global_fpr_ceiling


def test_malformed_does_not_touch_data():
    data = Mock()
    report = evaluate({"clauses":[{"field":"is_fraud", "op":"==", "val":1}]}, data)
    assert report.reason.startswith("rule_valid") and not report.sealed_evaluated
    data.__getitem__.assert_not_called() if hasattr(data, "__getitem__") else None


def test_mutated_rule_revalidated_without_consuming_data():
    candidate = good()
    candidate.clauses.clear()
    report = evaluate(candidate, {})
    assert report.verdict == "REJECTED" and not report.sealed_evaluated


def test_configured_complexity(demo):
    report = evaluate(good(), demo, settings=Settings(max_clauses=2))
    assert report.reason.startswith("rule_complexity")


def test_one_final_per_run_even_changed_rule(demo):
    gate = VerificationGate(spec=DEFAULT_DEMO_SPEC)
    gate.evaluate_final(good(), demo, BaselineDetector(), [])
    with pytest.raises(SealedAlreadyEvaluated):
        gate.evaluate_final(rule({"field":"amount", "op":">=", "val":100}), demo, BaselineDetector(), [])
    with pytest.raises(SealedAlreadyEvaluated):
        gate.evaluate_validation(good(), demo, BaselineDetector())


def test_validation_budget_and_coarse_only(demo):
    gate = VerificationGate(spec=DEFAULT_DEMO_SPEC)
    for _ in range(2):
        feedback = gate.evaluate_validation(good(), {"validation":demo["validation"]}, BaselineDetector())
        assert set(feedback.model_dump()) == {"recall_gain_bucket", "fpr_exceeded", "segment_violation"}
        assert not any(type(v) in (float, int) for v in feedback.model_dump().values())
    with pytest.raises(ValidationBudgetExceeded):
        gate.evaluate_validation(good(), demo, BaselineDetector())


def test_config_cannot_expand_revision_budget(demo):
    gate = VerificationGate(Settings(max_validation_retries=20), DEFAULT_DEMO_SPEC)
    for _ in range(2): gate.evaluate_validation(good(), demo, BaselineDetector())
    with pytest.raises(ValidationBudgetExceeded): gate.evaluate_validation(good(), demo, BaselineDetector())


def test_zero_target_insufficient_evidence(demo):
    df = demo["sealed"].copy()
    df.loc[df.attack_name.eq(DEFAULT_DEMO_SPEC.name), "attack_name"] = "background"
    report = evaluate(good(), {"sealed":df}, settings=Settings(min_recall_gain_pp=0))
    assert report.verdict == "REJECTED"
    assert "zero target" in next(c.detail for c in report.checks if c.name=="target_recall_gain")


def test_no_legitimate_rows_rejected(demo):
    df = demo["sealed"]
    report = evaluate(good(), {"sealed":df[df.is_fraud.eq(1)].copy()})
    assert report.verdict == "REJECTED"
    assert not next(c.passed for c in report.checks if c.name=="global_fpr")


def test_small_segments_are_reported(demo):
    report = evaluate(good(), demo, settings=Settings(min_segment_legit_count=100000))
    assert report.verdict == "REJECTED"
    assert all(r["status"] == "insufficient data" for r in report.segment_results)
    assert "insufficient data" in next(c.detail for c in report.checks if c.name=="segment_fpr")


def test_threshold_equality_passes_and_just_above_fails(demo):
    observed = evaluate(good(), demo).patched.fpr
    exact = evaluate(good(), demo, settings=Settings(global_fpr_ceiling=observed))
    assert next(c.passed for c in exact.checks if c.name=="global_fpr")
    below = evaluate(good(), demo, settings=Settings(global_fpr_ceiling=observed-1e-9))
    assert not next(c.passed for c in below.checks if c.name=="global_fpr")


def test_elementwise_monotonic_check(demo, monkeypatch):
    import redqueen.verification as module
    monkeypatch.setattr(module, "combine", lambda left, right: pd.Series(False, index=left.index))
    report = evaluate(good(), demo)
    assert report.reason.startswith("monotonic")


def test_sandbox_binds_candidate_and_preexisting_state(demo):
    state = SandboxState()
    report = evaluate(good(), demo)
    different = rule({"field":"amount", "op":">=", "val":1})
    with pytest.raises(SandboxActivationError): state.activate(different, report)
    state.activate(good(), report, spec=DEFAULT_DEMO_SPEC)
    assert len(state.active_rules) == 1
    with pytest.raises(SandboxActivationError): state.activate(good(), report)
    rejected = evaluate(different, demo)
    with pytest.raises(SandboxActivationError): state.activate(different, rejected)
    assert len(state.active_rules) == 1
    flags = BaselineDetector().predict(demo["sample"])
    assert (~flags | state.predict(demo["sample"])).all()
    snapshot = state.active_rules
    snapshot[0].clauses.clear()
    assert len(state.active_rules[0].clauses)==3


def test_cumulative_gain_and_fpr(demo):
    report = evaluate(good(), demo, active_rules=[good()])
    assert report.verdict == "REJECTED" and report.recall_gain_pp == 0
    assert report.baseline == report.patched
    assert report.candidate_only is not None and report.original_baseline is not None


def test_existing_broad_patch_cannot_be_hidden(demo):
    broad = rule({"field":"amount", "op":">=", "val":1})
    report = evaluate(good(), demo, active_rules=[broad])
    assert report.reason.startswith("global_fpr")
    assert "already exceeds" in report.reason


def test_regression_evaluates_previously_approved_specs(demo):
    report = VerificationGate(spec=DEFAULT_DEMO_SPEC).evaluate_final(good(), demo, BaselineDetector(), [DEFAULT_DEMO_SPEC])
    assert next(c.passed for c in report.checks if c.name=="regression")


def test_overfit_rule_must_work_on_heldout(demo):
    candidate = rule({"field":"amount", "op":"==", "val":float(demo["sample"].loc[demo["sample"].is_fraud.eq(1),"amount"].iloc[0])})
    assert evaluate(candidate, demo).reason.startswith("target_recall_gain")


def test_deterministic_reports_except_timing_and_run_id(demo):
    left, right = evaluate(good(), demo), evaluate(good(), demo)
    assert left.model_dump(exclude={"latency_ms", "run_id"}) == right.model_dump(exclude={"latency_ms", "run_id"})


def test_stratified_merchant_sampling_preserves_burst_lookalikes():
    from redqueen.simulator import generate_legit_background
    df = generate_legit_background(100000, 1337)
    for mask in (df.velocity_1h.ge(4), df.velocity_1h.lt(4)):
        assert abs(df.loc[mask, "merchant_category"].eq("crypto").mean() - 0.01) < 0.002
        assert abs(df.loc[mask, "merchant_category"].eq("gift_card").mean() - 0.02) < 0.002
    assert (df.merchant_category.eq("crypto") & df.velocity_1h.ge(12)).any()
