"""All replay scenarios use real simulation and verification, without a model."""
import json
import pytest
from redqueen.config import Settings
from redqueen.gemma_client import GemmaClient
from redqueen.pipeline import run_redqueen
from redqueen.replay import list_replay_scenarios
from redqueen.verification import SandboxState


def deterministic(result):
    report=result.report.model_dump(exclude={"latency_ms","run_id"})
    return result.spec, result.rule, report, result.evidence


@pytest.mark.parametrize("name",list_replay_scenarios())
def test_replay_end_to_end_without_api(name, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY","")
    def forbidden(*args): raise AssertionError("Replay attempted to access API")
    monkeypatch.setattr(GemmaClient,"_make_client",forbidden)
    state=SandboxState()
    left=run_redqueen(name,Settings(),"replay",sandbox=state)
    right=run_redqueen(name,Settings(),"replay")
    assert deterministic(left)==deterministic(right)
    assert left.telemetry.mode=="replay" and left.telemetry.replay_scenario==name
    assert left.telemetry.attempts==0 and left.telemetry.model_latency_ms is None
    assert left.report.sealed_evaluated
    for value in [left.report.baseline.recall,left.report.patched.recall,left.report.patched.fpr]:
        assert isinstance(value,float) and 0<=value<=1
    assert left.report.recall_gain_pp==(left.report.target_patched_recall-left.report.target_baseline_recall)*100
    assert len(state.active_rules)==(1 if left.report.verdict=="ACCEPTED" else 0)
    assert 0<=left.validation_retries<=1
    assert "GEMINI_API_KEY" not in json.dumps(left.to_dict())


def test_replay_verdict_mix():
    results=[run_redqueen(n,Settings(),"replay") for n in list_replay_scenarios()]
    assert {r.report.verdict for r in results}=={"ACCEPTED","REJECTED"}
    assert {r.report.reason.split(":")[0] for r in results if r.report.verdict=="REJECTED"}=={"global_fpr","segment_fpr"}
