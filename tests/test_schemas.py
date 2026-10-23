"""Phase 1 tests — schema validation.

Covers:
- Valid rule JSON (full clause form and shorthand)
- Invalid rules: unknown field, illegal op, 4 clauses, action BLOCK,
  out-of-bounds value, wrong type, extra keys
- Shorthand normalisation
- AttackSpec range ordering and field bounds
- Categorical-op restriction (== only for merchant_category / channel)
- Binary-op restriction (== / != only for is_new_device / geo_mismatch)
- extra="forbid" enforcement
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from redqueen.schemas import (
    ALLOWED_FIELDS,
    ALLOWED_OPS,
    AttackSpec,
    Clause,
    DefenseRule,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def valid_rule(**overrides) -> dict:
    base = {
        "clauses": [{"field": "velocity_1h", "op": ">=", "val": 4}],
        "action": "FLAG",
        "rationale": "High velocity is suspicious.",
    }
    base.update(overrides)
    return base


def valid_attack(**overrides) -> dict:
    base = {
        "name": "GiftCardBurst",
        "description": "Rapid gift-card purchases on new devices.",
        "target_merchant_categories": ["gift_card"],
        "amount_range": (50.0, 500.0),
        "hour_window": [0, 1, 2, 3],
        "velocity_1h_range": (5, 20),
        "account_age_range": (0, 30),
        "ip_age_range": (0, 7),
        "new_device_prob": 0.9,
        "geo_mismatch_prob": 0.7,
        "fraud_fraction": 0.05,
        "evasion_overlap": 0.2,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Valid rule — full clause form
# ===========================================================================

def test_valid_rule_full_form():
    rule = DefenseRule(**valid_rule())
    assert rule.action == "FLAG"
    assert len(rule.clauses) == 1
    assert rule.clauses[0].field == "velocity_1h"
    assert rule.clauses[0].op == ">="
    assert rule.clauses[0].val == 4


# ===========================================================================
# 2. Valid rule — shorthand normalisation
# ===========================================================================

def test_shorthand_normalisation():
    """Flat shorthand {field, op, val, action} must be promoted to clauses list."""
    shorthand = {
        "field": "velocity_1h",
        "op": ">=",
        "val": 4,
        "action": "FLAG",
        "rationale": "shorthand test",
    }
    rule = DefenseRule(**shorthand)
    assert len(rule.clauses) == 1
    assert rule.clauses[0].field == "velocity_1h"
    assert rule.clauses[0].val == 4


def test_shorthand_without_rationale():
    """Shorthand without explicit rationale should still parse (rationale defaults to '')."""
    shorthand = {
        "field": "amount",
        "op": ">",
        "val": 1000.0,
        "action": "FLAG",
    }
    rule = DefenseRule(**shorthand)
    assert rule.rationale == ""


# ===========================================================================
# 3. Valid multi-clause rule (up to 3)
# ===========================================================================

def test_valid_three_clause_rule():
    data = {
        "clauses": [
            {"field": "velocity_1h", "op": ">=", "val": 5},
            {"field": "amount", "op": ">", "val": 200.0},
            {"field": "is_new_device", "op": "==", "val": 1},
        ],
        "action": "FLAG",
        "rationale": "Multi-clause rule.",
    }
    rule = DefenseRule(**data)
    assert len(rule.clauses) == 3


# ===========================================================================
# 4. Invalid — unknown field
# ===========================================================================

def test_invalid_unknown_field():
    with pytest.raises(ValidationError, match="Unknown field"):
        DefenseRule(
            clauses=[{"field": "credit_score", "op": ">=", "val": 700}],
            action="FLAG",
            rationale="bad",
        )


# ===========================================================================
# 5. Invalid — illegal operator "contains"
# ===========================================================================

def test_invalid_op_contains():
    with pytest.raises(ValidationError, match="[Ii]llegal operator|Illegal operator"):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": "contains", "val": 3}],
            action="FLAG",
            rationale="bad",
        )


# ===========================================================================
# 6. Invalid — 4 clauses (exceeds max)
# ===========================================================================

def test_invalid_four_clauses():
    clauses = [
        {"field": "velocity_1h", "op": ">=", "val": 1},
        {"field": "velocity_24h", "op": ">=", "val": 1},
        {"field": "amount", "op": ">", "val": 100.0},
        {"field": "account_age_days", "op": "<", "val": 30},
    ]
    with pytest.raises(ValidationError, match="1.3 clauses|1–3"):
        DefenseRule(clauses=clauses, action="FLAG", rationale="four")


# ===========================================================================
# 7. Invalid — action BLOCK (must be FLAG)
# ===========================================================================

def test_invalid_action_block():
    with pytest.raises(ValidationError):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": ">=", "val": 4}],
            action="BLOCK",  # type: ignore[arg-type]
            rationale="bad action",
        )


# ===========================================================================
# 8. Invalid — out-of-bounds value
# ===========================================================================

def test_invalid_velocity_out_of_bounds():
    with pytest.raises(ValidationError, match="[Aa]bove maximum|maximum"):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": ">=", "val": 99}],  # max is 50
            action="FLAG",
            rationale="oob",
        )


def test_invalid_amount_negative():
    with pytest.raises(ValidationError, match="[Bb]elow minimum|minimum"):
        DefenseRule(
            clauses=[{"field": "amount", "op": ">", "val": -1.0}],
            action="FLAG",
            rationale="negative",
        )


# ===========================================================================
# 9. Invalid — wrong type (string where int expected)
# ===========================================================================

def test_invalid_wrong_type_string_for_int():
    with pytest.raises(ValidationError):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": ">=", "val": "high"}],
            action="FLAG",
            rationale="wrong type",
        )


# ===========================================================================
# 10. Invalid — extra keys (extra="forbid")
# ===========================================================================

def test_invalid_extra_key_on_rule():
    with pytest.raises(ValidationError):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": ">=", "val": 4}],
            action="FLAG",
            rationale="ok",
            extra_field="should_fail",  # type: ignore[call-arg]
        )


def test_invalid_extra_key_on_clause():
    with pytest.raises(ValidationError):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": ">=", "val": 4, "extra": "bad"}],
            action="FLAG",
            rationale="ok",
        )


# ===========================================================================
# 11. Categorical field — only == / != allowed
# ===========================================================================

def test_categorical_only_eq_ne_allowed():
    """merchant_category may only use == or !=."""
    rule = DefenseRule(
        clauses=[{"field": "merchant_category", "op": "==", "val": "crypto"}],
        action="FLAG",
        rationale="Crypto flagged.",
    )
    assert rule.clauses[0].val == "crypto"


def test_categorical_invalid_op_gt():
    with pytest.raises(ValidationError, match="categorical|categorical/binary"):
        DefenseRule(
            clauses=[{"field": "merchant_category", "op": ">", "val": "crypto"}],
            action="FLAG",
            rationale="bad",
        )


def test_categorical_invalid_value():
    with pytest.raises(ValidationError, match="categories|not in allowed"):
        DefenseRule(
            clauses=[{"field": "merchant_category", "op": "==", "val": "casino"}],
            action="FLAG",
            rationale="bad category",
        )


# ===========================================================================
# 12. Binary field — only == / != allowed
# ===========================================================================

def test_binary_field_eq_allowed():
    rule = DefenseRule(
        clauses=[{"field": "is_new_device", "op": "==", "val": 1}],
        action="FLAG",
        rationale="New device flag.",
    )
    assert rule.clauses[0].val == 1


def test_binary_field_invalid_op_ge():
    with pytest.raises(ValidationError, match="categorical/binary|categorical"):
        DefenseRule(
            clauses=[{"field": "geo_mismatch", "op": ">=", "val": 1}],
            action="FLAG",
            rationale="bad op on binary",
        )


# ===========================================================================
# 13. AttackSpec — range ordering
# ===========================================================================

def test_attack_spec_valid():
    spec = AttackSpec(**valid_attack())
    assert spec.name == "GiftCardBurst"
    assert spec.fraud_fraction == 0.05


def test_attack_spec_amount_range_inverted():
    with pytest.raises(ValidationError, match="low.*>.*high|low .* > high"):
        AttackSpec(**valid_attack(amount_range=(500.0, 50.0)))


def test_attack_spec_velocity_range_inverted():
    with pytest.raises(ValidationError, match="low.*>.*high|low .* > high"):
        AttackSpec(**valid_attack(velocity_1h_range=(20, 5)))


def test_attack_spec_account_age_range_inverted():
    with pytest.raises(ValidationError, match="low.*>.*high|low .* > high"):
        AttackSpec(**valid_attack(account_age_range=(100, 10)))


def test_attack_spec_fraud_fraction_too_low():
    with pytest.raises(ValidationError, match="fraud_fraction"):
        AttackSpec(**valid_attack(fraud_fraction=0.001))


def test_attack_spec_fraud_fraction_too_high():
    with pytest.raises(ValidationError, match="fraud_fraction"):
        AttackSpec(**valid_attack(fraud_fraction=0.5))


def test_attack_spec_invalid_merchant_category():
    with pytest.raises(ValidationError, match="merchant category|merchant_category"):
        AttackSpec(**valid_attack(target_merchant_categories=["casino"]))


def test_attack_spec_amount_out_of_bounds():
    with pytest.raises(ValidationError, match="bounds|bound"):
        AttackSpec(**valid_attack(amount_range=(0.0, 999_999.0)))


# ===========================================================================
# 14. Rationale length constraint
# ===========================================================================

def test_rationale_too_long():
    with pytest.raises(ValidationError, match="500"):
        DefenseRule(
            clauses=[{"field": "velocity_1h", "op": ">=", "val": 4}],
            action="FLAG",
            rationale="x" * 501,
        )


def test_rationale_exactly_500():
    rule = DefenseRule(
        clauses=[{"field": "velocity_1h", "op": ">=", "val": 4}],
        action="FLAG",
        rationale="x" * 500,
    )
    assert len(rule.rationale) == 500


# ===========================================================================
# 15. channel field (categorical)
# ===========================================================================

def test_channel_valid():
    rule = DefenseRule(
        clauses=[{"field": "channel", "op": "==", "val": "atm"}],
        action="FLAG",
        rationale="ATM rule.",
    )
    assert rule.clauses[0].val == "atm"


def test_channel_invalid_value():
    with pytest.raises(ValidationError):
        DefenseRule(
            clauses=[{"field": "channel", "op": "==", "val": "fax"}],
            action="FLAG",
            rationale="bad",
        )
