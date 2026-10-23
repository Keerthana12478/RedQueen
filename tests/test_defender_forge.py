"""Tests for defender_forge.py — Phase 3.

API is never called; GemmaClient is mocked throughout.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from redqueen.defender_forge import (
    _validate_evidence_for_model,
    propose_rule,
)
from redqueen.gemma_client import GemmaClient, GemmaOutputError
from redqueen.schemas import (
    DefenseRule,
    Evidence,
    RunTelemetry,
    ValidationFeedback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evidence(
    missed_fraud: list | None = None,
    lookalike_legit: list | None = None,
    permitted_fields: list | None = None,
    summary_stats: dict | None = None,
) -> Evidence:
    if permitted_fields is None:
        permitted_fields = ["amount", "velocity_1h", "merchant_category"]
    if missed_fraud is None:
        missed_fraud = [
            {"amount": 450.0, "velocity_1h": 8, "merchant_category": "gift_card"},
        ]
    if lookalike_legit is None:
        lookalike_legit = [
            {"amount": 420.0, "velocity_1h": 1, "merchant_category": "gift_card"},
        ]
    if summary_stats is None:
        summary_stats = {
            "n_missed_fraud": len(missed_fraud),
            "n_lookalike_legit": len(lookalike_legit),
        }
    return Evidence(
        missed_fraud=missed_fraud,
        lookalike_legit=lookalike_legit,
        permitted_fields=permitted_fields,
        summary_stats=summary_stats,
    )


_VALID_RULE_DICT = {
    "clauses": [
        {"field": "velocity_1h", "op": ">=", "val": 6},
        {"field": "merchant_category", "op": "==", "val": "gift_card"},
    ],
    "action": "FLAG",
    "rationale": "Flags high-velocity gift-card purchases.",
}


def _mock_client(return_value=None, raise_exc=None) -> GemmaClient:
    client = GemmaClient.__new__(GemmaClient)
    client._model = "gemma-test"
    client._fallback = "gemma-fallback"
    client._key = "fake"
    client._probe_cache = None
    client.last_attempts = 1

    if raise_exc is not None:
        client.generate_json = MagicMock(side_effect=raise_exc)
    else:
        rule = DefenseRule.model_validate(_VALID_RULE_DICT)
        client.generate_json = MagicMock(return_value=(rule, 100.0, "gemma-test"))
    return client


# ---------------------------------------------------------------------------
# Evidence guard
# ---------------------------------------------------------------------------

class TestEvidenceGuard:
    def test_valid_evidence_passes(self):
        ev = _make_evidence()
        _validate_evidence_for_model(ev)  # should not raise

    def test_forbidden_key_is_fraud_rejected(self):
        ev = _make_evidence(
            missed_fraud=[{"amount": 100.0, "is_fraud": 1}],
            permitted_fields=["amount"],
        )
        with pytest.raises(ValueError, match="is_fraud"):
            _validate_evidence_for_model(ev)

    def test_forbidden_key_txn_id_rejected(self):
        ev = _make_evidence(
            missed_fraud=[{"amount": 100.0, "txn_id": "S001"}],
            permitted_fields=["amount"],
        )
        with pytest.raises(ValueError, match="txn_id"):
            _validate_evidence_for_model(ev)

    def test_forbidden_key_attack_name_rejected(self):
        ev = _make_evidence(
            missed_fraud=[{"amount": 100.0}],          # clean row
            lookalike_legit=[{"amount": 100.0, "attack_name": "SomeAttack"}],
            permitted_fields=["amount"],
        )
        with pytest.raises(ValueError, match="attack_name"):
            _validate_evidence_for_model(ev)

    def test_forbidden_key_split_rejected(self):
        ev = _make_evidence(
            missed_fraud=[{"amount": 100.0, "split": "validation"}],
            permitted_fields=["amount"],
        )
        with pytest.raises(ValueError, match="split"):
            _validate_evidence_for_model(ev)

    def test_key_outside_permitted_rejected(self):
        ev = _make_evidence(
            missed_fraud=[{"amount": 100.0, "unknown_col": 99}],
            permitted_fields=["amount"],
        )
        with pytest.raises(ValueError, match="unknown_col"):
            _validate_evidence_for_model(ev)

    def test_permitted_field_outside_allowed_fields_rejected(self):
        ev = _make_evidence(
            permitted_fields=["amount", "completely_invalid_field"],
        )
        with pytest.raises(ValueError, match="ALLOWED_FIELDS"):
            _validate_evidence_for_model(ev)


# ---------------------------------------------------------------------------
# propose_rule — replay mode
# ---------------------------------------------------------------------------

class TestProposeRuleReplay:
    def test_replay_returns_rule(self):
        ev = _make_evidence()
        rule, telemetry = propose_rule(ev, client=None, mode="replay", feedback=None)
        assert isinstance(rule, DefenseRule)
        assert isinstance(telemetry, RunTelemetry)

    def test_replay_telemetry_mode(self):
        ev = _make_evidence()
        _, telemetry = propose_rule(ev, client=None, mode="replay", feedback=None)
        assert telemetry.mode == "replay"
        assert telemetry.model_used is None

    def test_replay_no_client_required(self):
        ev = _make_evidence()
        rule, _ = propose_rule(ev, client=None, mode="replay", feedback=None)
        assert isinstance(rule, DefenseRule)

    def test_replay_never_calls_generate_json(self):
        ev = _make_evidence()
        client = _mock_client()
        propose_rule(ev, client=client, mode="replay", feedback=None)
        client.generate_json.assert_not_called()


# ---------------------------------------------------------------------------
# propose_rule — live mode
# ---------------------------------------------------------------------------

class TestProposeRuleLive:
    def test_live_returns_rule_and_telemetry(self):
        ev = _make_evidence()
        client = _mock_client()
        rule, telemetry = propose_rule(ev, client=client, mode="live", feedback=None)
        assert isinstance(rule, DefenseRule)
        assert telemetry.mode == "live"
        assert telemetry.model_used == "gemma-test"

    def test_live_calls_generate_json_once(self):
        ev = _make_evidence()
        client = _mock_client()
        propose_rule(ev, client=client, mode="live", feedback=None)
        client.generate_json.assert_called_once()

    def test_live_requires_client(self):
        ev = _make_evidence()
        with pytest.raises(ValueError, match="client"):
            propose_rule(ev, client=None, mode="live", feedback=None)

    def test_live_with_feedback_calls_model(self):
        ev = _make_evidence()
        client = _mock_client()
        feedback = ValidationFeedback(
            recall_gain_bucket="none",
            fpr_exceeded=False,
            segment_violation=False,
        )
        propose_rule(ev, client=client, mode="live", feedback=feedback)
        client.generate_json.assert_called_once()

    def test_live_output_error_propagates(self):
        ev = _make_evidence()
        client = _mock_client(raise_exc=GemmaOutputError("bad"))
        with pytest.raises(GemmaOutputError):
            propose_rule(ev, client=client, mode="live", feedback=None)

    def test_invalid_mode_raises(self):
        ev = _make_evidence()
        with pytest.raises(NotImplementedError):
            propose_rule(ev, client=None, mode="unknown", feedback=None)

    def test_rule_schema_validation(self):
        """Rule returned by mock must pass DefenseRule validation."""
        ev = _make_evidence()
        client = _mock_client()
        rule, _ = propose_rule(ev, client=client, mode="live", feedback=None)
        # Accepted ops and fields
        for clause in rule.clauses:
            assert clause.field in ["velocity_1h", "merchant_category", "amount",
                                    "hour_of_day", "account_age_days", "ip_age_days",
                                    "is_new_device", "geo_mismatch", "velocity_24h",
                                    "amount_ratio_to_avg", "channel"]
        assert rule.action == "FLAG"

    def test_source_file_has_no_sealed_reference(self):
        """defender_forge must not import or access sealed/validation data."""
        import inspect
        import redqueen.defender_forge as forge_mod
        source = inspect.getsource(forge_mod)
        assert "datasets[\"sealed\"]" not in source
        assert "datasets[\"validation\"]" not in source

    def test_evidence_guard_runs_before_model(self):
        """Guard fires even when mode=live, before generate_json is called."""
        ev = _make_evidence(
            missed_fraud=[{"amount": 100.0, "is_fraud": 1}],
            permitted_fields=["amount"],
        )
        client = _mock_client()
        with pytest.raises(ValueError, match="is_fraud"):
            propose_rule(ev, client=client, mode="live", feedback=None)
        client.generate_json.assert_not_called()


# ---------------------------------------------------------------------------
# DefenseRule — schema restrictions via propose_rule round-trip mock
# ---------------------------------------------------------------------------

class TestRuleSchemaRestrictions:
    """Verify that schema-invalid rules from the model are rejected."""

    def _make_client_returning(self, raw_dict: dict) -> GemmaClient:
        client = GemmaClient.__new__(GemmaClient)
        client._model = "gemma-test"
        client._fallback = "gemma-fallback"
        client._key = "fake"
        client._probe_cache = None
        # generate_json will try to validate; feed the raw dict through DefenseRule
        from redqueen.schemas import DefenseRule
        from pydantic import ValidationError

        def mock_generate_json(prompt, schema_model, **kwargs):
            # Simulate model returning raw_dict: validate it
            result = schema_model.model_validate(raw_dict)
            return result, 50.0, "gemma-test"

        client.generate_json = mock_generate_json
        return client

    def test_unknown_field_rejected(self):
        from pydantic import ValidationError
        ev = _make_evidence()
        client = self._make_client_returning({
            "clauses": [{"field": "unknown_field_xyz", "op": ">=", "val": 10}],
            "action": "FLAG",
            "rationale": "test",
        })
        with pytest.raises((ValidationError, ValueError)):
            propose_rule(ev, client=client, mode="live", feedback=None)

    def test_invalid_op_rejected(self):
        from pydantic import ValidationError
        ev = _make_evidence()
        client = self._make_client_returning({
            "clauses": [{"field": "amount", "op": "matches", "val": 100}],
            "action": "FLAG",
            "rationale": "test",
        })
        with pytest.raises((ValidationError, ValueError)):
            propose_rule(ev, client=client, mode="live", feedback=None)

    def test_four_clauses_rejected(self):
        from pydantic import ValidationError
        ev = _make_evidence()
        client = self._make_client_returning({
            "clauses": [
                {"field": "amount", "op": ">=", "val": 100},
                {"field": "velocity_1h", "op": ">=", "val": 3},
                {"field": "account_age_days", "op": "<", "val": 30},
                {"field": "ip_age_days", "op": "<", "val": 7},
            ],
            "action": "FLAG",
            "rationale": "too many clauses",
        })
        with pytest.raises((ValidationError, ValueError)):
            propose_rule(ev, client=client, mode="live", feedback=None)

    def test_action_block_rejected(self):
        from pydantic import ValidationError
        ev = _make_evidence()
        client = self._make_client_returning({
            "clauses": [{"field": "amount", "op": ">=", "val": 100}],
            "action": "BLOCK",  # not allowed
            "rationale": "test",
        })
        with pytest.raises((ValidationError, ValueError)):
            propose_rule(ev, client=client, mode="live", feedback=None)
