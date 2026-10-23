import json
from time import perf_counter
import pytest
from redqueen.config import Settings
from redqueen.pipeline import PipelineError, run_redqueen
from redqueen.verification import SandboxState, VerificationGate


def test_replay_pipeline_and_session_state():
    sandbox = SandboxState()
    started = perf_counter()
    result = run_redqueen("GiftCardNightBurst", Settings(), "replay", sandbox=sandbox)
    assert result.report.verdict=="ACCEPTED", result.report.reason
    assert len(sandbox.active_rules)==result.active_rule_count==1
    assert result.telemetry.mode=="replay" and result.telemetry.attempts==0
    assert result.telemetry.model_used is result.telemetry.model_latency_ms is None
    assert result.dataset_metadata=={"sample":2000,"validation":5000,"sealed":10000}
    assert result.stage_timings_ms["Sealed verification (once)"]>0
    assert perf_counter()-started<5
    assert "GEMINI_API_KEY" not in json.dumps(result.to_dict())
    duplicate = run_redqueen("GiftCardNightBurst", Settings(), "replay", sandbox=sandbox)
    assert duplicate.report.verdict=="REJECTED"
    assert duplicate.report.recall_gain_pp==0
    assert len(sandbox.active_rules)==1
    assert duplicate.run_id!=result.run_id


@pytest.mark.parametrize("scenario", ["", "  ", "x"*601])
def test_invalid_input_precedes_api(scenario):
    with pytest.raises(ValueError): run_redqueen(scenario, Settings(), "live")


def test_one_final_after_revision(monkeypatch):
    observed = []
    original = VerificationGate.evaluate_final
    def spy(self, rule, datasets, baseline, approved):
        observed.append((self.validation_calls, rule))
        return original(self, rule, datasets, baseline, approved)
    monkeypatch.setattr(VerificationGate,"evaluate_final",spy)
    result = run_redqueen("HighAmountGeoMismatch", Settings(), "replay")
    assert result.validation_retries==1
    assert len(result.validation_feedback)==2
    assert len(observed)==1 and observed[0][0]==2
    assert result.active_rule_count==0


def test_typed_internal_stage_error(monkeypatch):
    import redqueen.pipeline as pipeline
    monkeypatch.setattr(pipeline,"generate_datasets",lambda *a: (_ for _ in ()).throw(RuntimeError("secret detail")))
    with pytest.raises(PipelineError) as error:
        run_redqueen("GiftCardNightBurst", Settings(), "replay")
    assert error.value.stage=="Synthetic simulator"
    assert "secret detail" not in str(error.value)
