"""Fixed baseline, useful/overbroad fixtures and overlap's recall implications."""
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from redqueen.baseline import BaselineDetector
from redqueen.config import Settings
from redqueen.metrics import compute_metrics, recall_gain_pp, segment_fpr, target_attack_recall
from redqueen.rule_engine import apply_rule, combine
from redqueen.schemas import AttackSpec, Clause, DefenseRule
from redqueen.simulator import DEFAULT_DEMO_SPEC, generate_datasets, generate_fraud, generate_legit_background


def test_fixed_thresholds_by_hand_and_display_rules():
    frame = pd.DataFrame({
        "amount": [5000.0, 4999.0, 10.0, 800.0, 799.0, 1000.0, 1000.0],
        "velocity_1h": [0, 0, 12, 0, 0, 0, 0],
        "geo_mismatch": [0, 0, 0, 1, 1, 0, 0],
        "is_new_device": [0, 0, 0, 1, 1, 0, 0],
        "account_age_days": [100, 100, 100, 100, 100, 2, 3],
    }, index=[7, 3, 4, 10, 8, 15, 12])
    before = frame.copy()
    detector = BaselineDetector()
    assert all(isinstance(rule, DefenseRule) for rule in detector.rules)
    assert detector.predict(frame).tolist() == [True, False, True, True, False, True, False]
    assert_frame_equal(frame, before)
    detector.rules.clear()
    assert len(BaselineDetector().rules) == 4


def test_baseline_fpr_on_large_legitimate_background():
    frame = generate_legit_background(100_000, 1337)
    result = compute_metrics(frame.is_fraud, BaselineDetector().predict(frame))
    assert 0.003 <= result.fpr <= 0.008
    assert result.fpr < 0.015


def test_default_sample_baseline_and_positive_negative_rule_fixtures():
    settings = Settings()
    # Inspect only sample; no held-out aggregate is used to tune fixtures.
    frame = generate_datasets(DEFAULT_DEMO_SPEC, settings.seed, settings)["sample"]
    detector = BaselineDetector()
    flags = detector.predict(frame)
    baseline = compute_metrics(frame.is_fraud, flags)
    target = target_attack_recall(frame, flags, DEFAULT_DEMO_SPEC.name)
    assert 0.20 < target < 0.50
    assert target < 0.60
    assert baseline.fpr < 0.015
    useful = DefenseRule(clauses=[
        Clause(field="merchant_category", op="==", val="gift_card"),
        Clause(field="velocity_1h", op=">=", val=6),
        Clause(field="ip_age_days", op="<=", val=3),
    ], action="FLAG", rationale="Gift-card burst on a young IP.")
    useful_flags = combine(flags, apply_rule(useful, frame))
    improved = compute_metrics(frame.is_fraud, useful_flags)
    assert recall_gain_pp(baseline, improved) >= settings.min_recall_gain_pp
    assert target_attack_recall(frame, useful_flags, DEFAULT_DEMO_SPEC.name) > target
    assert improved.fpr <= settings.global_fpr_ceiling
    segments = segment_fpr(frame, useful_flags,
                           ["merchant_category", "channel", "account_age_bucket"])
    assert all(group["fpr"] <= settings.segment_fpr_budget
               for groups in segments.values() for group in groups.values()
               if group["n_legit"] >= settings.min_segment_legit_count)
    # A broad rule is permitted JSON but fails the data-driven FPR budget.
    broad = DefenseRule(clauses=[Clause(field="amount", op=">=", val=0)],
                        action="FLAG", rationale="Overbroad negative fixture.")
    bad = compute_metrics(frame.is_fraud, combine(flags, apply_rule(broad, frame)))
    assert bad.fpr == 1.0
    assert bad.fpr > settings.global_fpr_ceiling
    # An overly narrow rule is valid but provides no gain on these amounts.
    narrow = DefenseRule(clauses=[Clause(field="amount", op=">", val=49_999)],
                         action="FLAG", rationale="No useful added detection.")
    no_gain = compute_metrics(frame.is_fraud, combine(flags, apply_rule(narrow, frame)))
    assert recall_gain_pp(baseline, no_gain) == 0.0


def test_full_evasion_reduces_baseline_and_signature_recall_to_legit_rate():
    frames = []
    for overlap in (0.0, 1.0):
        spec = AttackSpec.model_validate({
            **DEFAULT_DEMO_SPEC.model_dump(), "evasion_overlap": overlap})
        frames.append(generate_fraud(spec, 20_000, 1337))
    detector = BaselineDetector()
    recalls = [target_attack_recall(f, detector.predict(f), DEFAULT_DEMO_SPEC.name) for f in frames]
    assert recalls[0] > 0.25
    assert recalls[1] < 0.015
    assert recalls[0] > recalls[1] + 0.20
    signature = DefenseRule(clauses=[
        Clause(field="merchant_category", op="==", val="gift_card"),
        Clause(field="velocity_1h", op=">=", val=6),
        Clause(field="ip_age_days", op="<=", val=3),
    ], action="FLAG", rationale="")
    signature_recalls = [
        target_attack_recall(f, apply_rule(signature, f), DEFAULT_DEMO_SPEC.name) for f in frames]
    assert signature_recalls[0] == 1.0
    assert signature_recalls[1] < 0.005


def test_baseline_empty_input():
    frame = generate_legit_background(0, 1)
    flags = BaselineDetector().predict(frame)
    assert flags.empty and flags.dtype == bool
