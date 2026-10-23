"""Essential Phase 3 contracts: fixture pairing and truthful request telemetry."""
from unittest.mock import MagicMock

import pytest

from redqueen.attack_lab import generate_attack_spec
from redqueen.defender_forge import propose_rule
from redqueen.gemma_client import GemmaClient
from redqueen.config import Settings
from redqueen.replay import list_replay_scenarios, load_replay_validated
from redqueen.schemas import DefenseRule, Evidence


@pytest.mark.parametrize("name", list_replay_scenarios())
def test_replay_selection_stays_paired(name):
    spec, attack = generate_attack_spec(name, None, "replay")
    evidence = Evidence(missed_fraud=[], lookalike_legit=[], permitted_fields=[], summary_stats={})
    rule, forge = propose_rule(evidence, None, "replay", None, replay_scenario=attack.replay_scenario)
    assert spec == load_replay_validated(name)["attack_spec"]
    assert rule == load_replay_validated(name)["proposed_rule"]
    assert attack.replay_scenario == forge.replay_scenario == name
    assert attack.attempts == forge.attempts == 0
    assert attack.model_latency_ms is forge.model_latency_ms is None


def test_actual_retries_reach_forge_telemetry(monkeypatch):
    from pydantic import SecretStr
    client = GemmaClient(Settings(api_key=SecretStr("test-only")))
    sdk = MagicMock()
    rule = load_replay_validated("GiftCardNightBurst")["proposed_rule"]
    sdk.models.generate_content.side_effect = [MagicMock(text="broken"), MagicMock(text=rule.model_dump_json())]
    monkeypatch.setattr(client, "_make_client", lambda: sdk)
    evidence = Evidence(missed_fraud=[], lookalike_legit=[], permitted_fields=[], summary_stats={})
    _, telemetry = propose_rule(evidence, client, "live", None)
    assert telemetry.attempts == client.last_attempts == sdk.models.generate_content.call_count == 2
    assert client.total_api_calls == 2


def test_closest_replay_is_identified():
    _, telemetry = generate_attack_spec("night gift card burst", None, "replay")
    assert telemetry.replay_match == "closest"
    assert telemetry.replay_scenario == "GiftCardNightBurst"
