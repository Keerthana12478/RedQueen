"""Hand-computed comparisons, schema revalidation and monotonic properties."""
from time import perf_counter

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from redqueen.rule_engine import RuleExecutionError, apply_rule, combine
from redqueen.schemas import Clause, DefenseRule
from redqueen.simulator import generate_legit_background


def rule(field="amount", op=">=", val=2):
    return DefenseRule(clauses=[Clause(field=field, op=op, val=val)],
                       action="FLAG", rationale="test")


@pytest.mark.parametrize("op,expected", [
    (">", [False, False, True]), (">=", [False, True, True]),
    ("<", [True, False, False]), ("<=", [True, True, False]),
    ("==", [False, True, False]), ("!=", [True, False, True]),
])
def test_every_operator_by_hand(op, expected):
    frame = pd.DataFrame({"amount": [1.0, 2.0, 3.0]}, index=[5, 2, 9])
    actual = apply_rule(rule(op=op), frame)
    assert_series_equal(actual, pd.Series(expected, index=frame.index))


@pytest.mark.parametrize("field,op,val,expected", [
    ("merchant_category", "==", "gift_card", [True, False, True]),
    ("merchant_category", "!=", "gift_card", [False, True, False]),
    ("is_new_device", "==", 1, [True, False, False]),
    ("is_new_device", "!=", 1, [False, True, True]),
])
def test_categorical_and_binary_comparisons(field, op, val, expected):
    frame = pd.DataFrame({
        "merchant_category": ["gift_card", "grocery", "gift_card"],
        "is_new_device": [1, 0, 0],
    })
    assert apply_rule(rule(field, op, val), frame).tolist() == expected


def test_three_clauses_are_anded_without_mutation():
    frame = pd.DataFrame({"amount": [450.0, 450.0, 450.0, 10.0],
                          "velocity_1h": [6, 2, 6, 6],
                          "merchant_category": ["gift_card", "gift_card", "grocery", "gift_card"]})
    original = frame.copy(deep=True)
    candidate = DefenseRule(clauses=[
        Clause(field="amount", op=">=", val=400),
        Clause(field="velocity_1h", op=">=", val=6),
        Clause(field="merchant_category", op="==", val="gift_card"),
    ], action="FLAG", rationale="")
    assert apply_rule(candidate, frame).tolist() == [True, False, False, False]
    assert_frame_equal(frame, original)


@pytest.mark.parametrize("clause", [
    {"field": "txn_id", "op": "==", "val": "S0"},
    {"field": "amount", "op": "contains", "val": 1},
    {"field": "amount", "op": ">=", "val": -1},
    {"field": "velocity_1h", "op": ">=", "val": 2.5},
    {"field": "merchant_category", "op": ">", "val": "gift_card"},
    {"field": "is_new_device", "op": ">", "val": 0},
    {"field": "amount", "op": ">=", "val": float("nan")},
    {"field": "amount", "op": ">=", "val": float("inf")},
])
def test_constructed_invalid_models_raise_typed_error(clause):
    candidate = DefenseRule.model_construct(
        clauses=[Clause.model_construct(**clause)], action="FLAG", rationale="")
    with pytest.raises(RuleExecutionError):
        apply_rule(candidate, pd.DataFrame({"amount": [1.0]}))


@pytest.mark.parametrize("change", [
    {"clauses": []}, {"clauses": [Clause(field="amount", op=">", val=1)] * 4},
    {"action": "BLOCK"}, {"rationale": "x" * 501},
])
def test_constructed_invalid_rule_rejected(change):
    candidate = rule().model_copy(update=change)
    with pytest.raises(RuleExecutionError):
        apply_rule(candidate, pd.DataFrame({"amount": [1.0]}))


def test_mutable_nested_clause_list_is_revalidated():
    candidate = rule()
    candidate.clauses.append(Clause.model_construct(field="unknown", op=">", val=2))
    with pytest.raises(RuleExecutionError):
        apply_rule(candidate, pd.DataFrame({"amount": [1.0]}))


@pytest.mark.parametrize("frame", [
    pd.DataFrame({"other": [1]}),
    pd.DataFrame({"amount": [None]}),
    pd.DataFrame([[1, 2]], columns=["amount", "amount"]),
    pd.DataFrame({"amount": ["bad"]}),
])
def test_bad_input_data_raises_typed_error(frame):
    with pytest.raises(RuleExecutionError):
        apply_rule(rule(), frame)


def test_empty_frame_boolean_output():
    result = apply_rule(rule(), pd.DataFrame({"amount": pd.Series([], dtype=float)}))
    assert result.empty
    assert result.dtype == bool


def test_combine_truth_table_and_monotonic_random_rules():
    assert combine(pd.Series([False, False, True, True]),
                   pd.Series([False, True, False, True])).tolist() == [False, True, True, True]
    rng = np.random.default_rng(1337)
    frame = generate_legit_background(2500, 24)
    baseline = pd.Series(rng.random(len(frame)) < 0.2, index=frame.index)
    before = baseline.copy()
    for _ in range(75):
        clauses = [
            Clause(field="amount", op=">=", val=float(rng.uniform(0, 10_000))),
            Clause(field="hour_of_day", op="<=", val=int(rng.integers(0, 24))),
            Clause(field="velocity_1h", op=">=", val=int(rng.integers(0, 51))),
        ][:int(rng.integers(1, 4))]
        candidate = DefenseRule(clauses=clauses, action="FLAG", rationale="")
        flags = apply_rule(candidate, frame)
        patched = combine(baseline, flags)
        assert patched[baseline].all()
        np.testing.assert_array_equal(patched, baseline.to_numpy() | flags.to_numpy())
    assert_series_equal(baseline, before)


@pytest.mark.parametrize("left,right", [
    (pd.Series([True], index=[0]), pd.Series([False], index=[1])),
    (pd.Series([True, False]), pd.Series([True])),
    (pd.Series([True, False], index=[0, 1]), pd.Series([False, True], index=[1, 0])),
    (pd.Series([1]), pd.Series([False])),
    (pd.Series([None], dtype="boolean"), pd.Series([False])),
])
def test_combine_rejects_ambiguous_or_misaligned_inputs(left, right):
    with pytest.raises(RuleExecutionError):
        combine(left, right)


def test_rule_evaluation_10k_performance():
    frame = generate_legit_background(10_000, 1337)
    candidate = DefenseRule(clauses=[
        Clause(field="amount", op=">=", val=400),
        Clause(field="merchant_category", op="==", val="gift_card"),
        Clause(field="velocity_1h", op=">=", val=6),
    ], action="FLAG", rationale="")
    start = perf_counter()
    flags = apply_rule(candidate, frame)
    elapsed = perf_counter() - start
    assert len(flags) == 10_000
    assert elapsed < 0.1, f"10k rule evaluation took {elapsed:.4f}s"
