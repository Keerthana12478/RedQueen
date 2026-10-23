"""Confusion arithmetic, undefined denominators and segment/target isolation."""
import numpy as np
import pandas as pd
import pytest

from redqueen.metrics import (
    compute_metrics, legit_flagged_per_10k, recall_gain_pp, segment_fpr, target_attack_recall,
)


def test_confusion_matrix_and_absolute_recall_gain():
    truth = pd.Series([1, 1, 1, 0, 0, 0, 0])
    base = compute_metrics(truth, pd.Series([True, False, False, True, False, False, False]))
    patched = compute_metrics(truth, pd.Series([True, True, False, True, False, False, False]))
    assert (base.tp, base.fp, base.tn, base.fn) == (1, 1, 3, 2)
    assert base.recall == pytest.approx(1 / 3)
    assert base.precision == 0.5
    assert base.fpr == 0.25
    assert recall_gain_pp(base, patched) == pytest.approx(100 / 3)
    assert legit_flagged_per_10k(base.fp, base.fp + base.tn) == 2500


@pytest.mark.parametrize("truth,pred,expected", [
    ([], [], (0.0, 0.0, 0.0, 0, 0, 0, 0)),
    ([0, 0], [False, False], (0.0, 0.0, 0.0, 0, 0, 2, 0)),
    ([1, 1], [False, False], (0.0, 0.0, 0.0, 0, 0, 0, 2)),
    ([1, 1], [True, False], (0.5, 1.0, 0.0, 1, 0, 0, 1)),
    ([0, 0], [True, True], (0.0, 0.0, 1.0, 0, 2, 0, 0)),
    ([1, 0], [True, False], (1.0, 1.0, 0.0, 1, 0, 1, 0)),
])
def test_empty_denominator_policy(truth, pred, expected):
    actual = compute_metrics(pd.Series(truth, dtype=int), pd.Series(pred, dtype=bool))
    assert (actual.recall, actual.precision, actual.fpr,
            actual.tp, actual.fp, actual.tn, actual.fn) == expected


def test_zero_recall_baseline_does_not_divide_by_zero():
    base = compute_metrics([1, 1], [False, False])
    patched = compute_metrics([1, 1], [True, False])
    assert recall_gain_pp(base, patched) == 50.0
    assert legit_flagged_per_10k(0, 0) == 0.0


@pytest.mark.parametrize("truth,pred", [
    ([0, 1], [True]), ([0, 2], [False, True]), ([0, 1], [0, 2]),
    ([0, np.nan], [False, True]), ([[0, 1]], [[False, True]]),
    (pd.Series([0, 1], index=[1, 2]), pd.Series([False, True], index=[2, 1])),
])
def test_invalid_metrics_inputs_rejected(truth, pred):
    with pytest.raises(ValueError):
        compute_metrics(truth, pred)


@pytest.mark.parametrize("fp,n_legit", [(-1, 10), (11, 10), (1, 0), (0, -1)])
def test_invalid_per_10k_counts(fp, n_legit):
    with pytest.raises(ValueError):
        legit_flagged_per_10k(fp, n_legit)


@pytest.fixture
def segment_frame():
    return pd.DataFrame({
        "is_fraud": [0, 0, 0, 0, 1, 1],
        "attack_name": ["none", "none", "none", "none", "target", "background"],
        "merchant_category": ["gift_card", "gift_card", "grocery", "grocery", "crypto", "crypto"],
        "channel": ["web", "mobile", "web", "mobile", "atm", "atm"],
        "account_age_days": [29, 30, 365, 366, 1, 800],
    }, index=[5, 3, 9, 11, 12, 14])


def test_segments_by_hand_include_legit_counts_and_age_boundaries(segment_frame):
    flags = pd.Series([True, False, True, False, True, True], index=segment_frame.index)
    original = segment_frame.copy(deep=True)
    result = segment_fpr(segment_frame, flags,
                         ["merchant_category", "channel", "account_age_bucket"])
    assert result["merchant_category"]["gift_card"] == {"fpr": 0.5, "fp": 1, "n_legit": 2}
    assert result["merchant_category"]["crypto"] == {"fpr": 0.0, "fp": 0, "n_legit": 0}
    assert result["channel"]["web"] == {"fpr": 1.0, "fp": 2, "n_legit": 2}
    assert result["channel"]["atm"]["n_legit"] == 0
    assert result["account_age_bucket"]["<30"] == {"fpr": 1.0, "fp": 1, "n_legit": 1}
    assert result["account_age_bucket"]["30-365"] == {"fpr": 0.5, "fp": 1, "n_legit": 2}
    assert result["account_age_bucket"][">365"] == {"fpr": 0.0, "fp": 0, "n_legit": 1}
    pd.testing.assert_frame_equal(segment_frame, original)


def test_all_fraud_and_empty_segments(segment_frame):
    for frame in (segment_frame[segment_frame.is_fraud.eq(1)], segment_frame.iloc[:0]):
        flags = pd.Series(True, index=frame.index)
        result = segment_fpr(frame, flags,
                             ["merchant_category", "channel", "account_age_bucket"])
        assert all(group == {"fpr": 0.0, "fp": 0, "n_legit": 0}
                   for groups in result.values() for group in groups.values())


def test_unknown_segment_rejected(segment_frame):
    with pytest.raises(ValueError):
        segment_fpr(segment_frame, pd.Series(False, index=segment_frame.index), ["split"])


def test_segment_and_target_flags_require_index_alignment(segment_frame):
    flags = pd.Series(False, index=segment_frame.index[::-1])
    with pytest.raises(ValueError):
        segment_fpr(segment_frame, flags, ["channel"])
    with pytest.raises(ValueError):
        target_attack_recall(segment_frame, flags, "target")


def test_target_attack_recall_excludes_generic_and_legitimate_names(segment_frame):
    flags = pd.Series([True, False, False, False, False, True], index=segment_frame.index)
    assert compute_metrics(segment_frame.is_fraud, flags).recall == 0.5
    assert target_attack_recall(segment_frame, flags, "target") == 0.0
    assert target_attack_recall(segment_frame, flags, "background") == 1.0
    assert target_attack_recall(segment_frame, flags, "absent") == 0.0
    assert target_attack_recall(segment_frame, flags, "none") == 0.0
