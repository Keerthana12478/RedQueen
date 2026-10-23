"""Tests for replay.py — Phase 3."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from redqueen.replay import (
    _tokenize,
    _overlap,
    list_replay_scenarios,
    load_replay,
    load_replay_validated,
)
from redqueen.schemas import AttackSpec, DefenseRule


# ---------------------------------------------------------------------------
# list_replay_scenarios
# ---------------------------------------------------------------------------

class TestListReplayScenarios:
    def test_returns_list_of_strings(self):
        names = list_replay_scenarios()
        assert isinstance(names, list)
        assert len(names) >= 3, "Expected at least 3 replay scenarios"
        for name in names:
            assert isinstance(name, str)

    def test_known_scenario_present(self):
        names = list_replay_scenarios()
        assert "GiftCardNightBurst" in names

    def test_all_three_scenarios_present(self):
        names = list_replay_scenarios()
        assert "GiftCardNightBurst" in names
        assert "CryptoNewAccountBurst" in names
        assert "HighAmountGeoMismatch" in names


# ---------------------------------------------------------------------------
# load_replay — exact match
# ---------------------------------------------------------------------------

class TestLoadReplayExactMatch:
    def test_exact_match_gift_card(self):
        data = load_replay("GiftCardNightBurst")
        assert data["name"] == "GiftCardNightBurst"
        assert data["_match_type"] == "exact"
        assert data["_matched_name"] == "GiftCardNightBurst"

    def test_exact_match_case_insensitive(self):
        data = load_replay("giftcardnightburst")
        assert data["_match_type"] == "exact"

    def test_exact_match_crypto(self):
        data = load_replay("CryptoNewAccountBurst")
        assert data["_match_type"] == "exact"

    def test_exact_match_geo(self):
        data = load_replay("HighAmountGeoMismatch")
        assert data["_match_type"] == "exact"

    def test_label_is_replay(self):
        data = load_replay("GiftCardNightBurst")
        assert data["label"] == "REPLAY"

    def test_has_required_keys(self):
        data = load_replay("GiftCardNightBurst")
        for key in ("name", "scenario_text", "attack_spec", "proposed_rule", "label"):
            assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# load_replay — keyword fallback
# ---------------------------------------------------------------------------

class TestLoadReplayKeywordFallback:
    def test_free_text_matches_gift_card(self):
        data = load_replay("night gift card purchases high velocity")
        assert data["_matched_name"] == "GiftCardNightBurst"
        assert data["_match_type"] == "closest"

    def test_free_text_matches_crypto(self):
        data = load_replay("new accounts buying crypto business hours")
        assert data["_matched_name"] == "CryptoNewAccountBurst"

    def test_unknown_name_returns_closest(self):
        # Should not raise; returns best match
        data = load_replay("completely unknown random scenario xyz")
        assert "_matched_name" in data
        assert data["_match_type"] == "closest"


# ---------------------------------------------------------------------------
# load_replay_validated — schema validation
# ---------------------------------------------------------------------------

class TestLoadReplayValidated:
    def test_attack_spec_is_pydantic(self):
        data = load_replay_validated("GiftCardNightBurst")
        assert isinstance(data["attack_spec"], AttackSpec)

    def test_defense_rule_is_pydantic(self):
        data = load_replay_validated("GiftCardNightBurst")
        assert isinstance(data["proposed_rule"], DefenseRule)

    def test_all_scenarios_validate(self):
        for name in list_replay_scenarios():
            data = load_replay_validated(name)
            assert isinstance(data["attack_spec"], AttackSpec)
            assert isinstance(data["proposed_rule"], DefenseRule)

    def test_label_replay_required(self, tmp_path, monkeypatch):
        """A scenario file missing label:REPLAY must raise ValueError."""
        from redqueen import replay as replay_mod
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({
            "name": "BadScenario",
            "scenario_text": "test",
            "label": "LIVE",  # wrong!
            "attack_spec": {
                "name": "Test",
                "description": "test",
                "target_merchant_categories": ["crypto"],
                "amount_range": [100.0, 200.0],
                "hour_window": [10],
                "velocity_1h_range": [1, 5],
                "account_age_range": [0, 30],
                "ip_age_range": [0, 30],
                "new_device_prob": 0.5,
                "geo_mismatch_prob": 0.1,
                "fraud_fraction": 0.05,
                "evasion_overlap": 0.1,
            },
            "proposed_rule": {
                "clauses": [{"field": "velocity_1h", "op": ">=", "val": 5}],
                "action": "FLAG",
                "rationale": "test",
            },
        }), encoding="utf-8")
        monkeypatch.setattr(replay_mod, "_REPLAY_DIR", tmp_path)
        with pytest.raises(ValueError, match="REPLAY"):
            load_replay_validated("BadScenario")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestInternals:
    def test_tokenize_strips_stopwords(self):
        tokens = _tokenize("the gift card at night")
        assert "the" not in tokens
        assert "at" not in tokens
        assert "gift" in tokens
        assert "card" in tokens
        assert "night" in tokens

    def test_overlap_correct(self):
        a = frozenset({"gift", "card", "night"})
        b = frozenset({"gift", "card", "fraud"})
        assert _overlap(a, b) == 2

    def test_overlap_zero(self):
        a = frozenset({"abc"})
        b = frozenset({"xyz"})
        assert _overlap(a, b) == 0
