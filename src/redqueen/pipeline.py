"""RedQueen — shared end-to-end orchestrator for CLI and dashboard.

Model proposals are bounded; independent Python owns final decisions.
Signatures are **frozen**; do not rename.

INVARIANTS:
- :class:`PipelineResult` never contains raw sealed or validation rows.
- The pipeline passes the sealed DataFrame opaquely to the verification gate
  and must not inspect sealed metrics itself.
"""
from __future__ import annotations

import time
from uuid import uuid4
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from redqueen.baseline import BaselineDetector
from redqueen.config import Settings
from redqueen.failure_analysis import build_evidence
from redqueen.schemas import (
    ALLOWED_FIELDS,
    AttackSpec,
    DefenseRule,
    Evidence,
    RunTelemetry,
    VerificationReport,
    ValidationFeedback,
)
from redqueen.simulator import generate_datasets

if TYPE_CHECKING:
    from redqueen.verification import VerificationGate


class SimulationBoundary:
    """Own simulation frames; route data by capability, never by row labels.

    Model/UI code can request sample evidence and counts, but receives no raw
    frames. Only gate methods receive held-out frames, and validation receives
    no sealed capability. This is an application interface boundary, not a
    security sandbox against arbitrary Python introspection.
    """

    def __init__(self, spec: AttackSpec, seed: int, settings: Settings) -> None:
        datasets = generate_datasets(spec, seed, settings)
        self.__sample = datasets["sample"]
        self.__validation = datasets["validation"]
        self.__sealed = datasets["sealed"]
        self.__settings = settings

    @property
    def metadata(self) -> dict[str, int]:
        """Return configured counts without reading held-out frame contents."""
        return {"sample": self.__settings.n_sample,
                "validation": self.__settings.n_validation,
                "sealed": self.__settings.n_sealed}

    def build_sample_evidence(self, baseline: BaselineDetector) -> Evidence:
        """Use only the sample capability, regardless of held-out split labels."""
        sample = self.__sample.copy(deep=True)
        return build_evidence(sample, baseline.predict(sample), self.__settings)

    def evaluate_validation(
        self, gate: VerificationGate, rule: DefenseRule, baseline: BaselineDetector,
    ) -> ValidationFeedback:
        """Pass only validation to the gate; sealed stays inaccessible here."""
        return gate.evaluate_validation(rule, {"validation": self.__validation}, baseline)

    def evaluate_final(
        self, gate: VerificationGate, rule: DefenseRule, baseline: BaselineDetector,
        approved_attacks: list[AttackSpec],
    ) -> VerificationReport:
        """Transfer the sealed capability only to the final gate method.

        One-shot finalization and target-positive evidence checks are owned
        by the independent gate.
        """
        return gate.evaluate_final(rule, {"sealed": self.__sealed}, baseline, approved_attacks)


def _validate_metadata(value: object) -> None:
    """Enforce the UI-facing counts-only contract recursively."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Dataset metadata keys must be strings")
            _validate_metadata(item)
    elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Dataset metadata may contain only non-negative integer counts")


@dataclass
class PipelineResult:
    """Bundled output of one full RedQueen run.

    Contains only sample-split evidence and metadata; never raw sealed or
    validation DataFrames.
    """

    spec: AttackSpec
    """The attack specification generated (or loaded in replay mode)."""

    rule: DefenseRule
    """The defense rule proposed by Gemma and verified by Python."""

    report: VerificationReport
    """Full verification report from the gate."""

    telemetry: RunTelemetry
    """Timing and bookkeeping for this run."""

    evidence: Evidence
    """Sample-split failure-analysis evidence (display only)."""

    dataset_metadata: dict = field(default_factory=dict)
    """Shape / split-size metadata (counts only, no raw rows)."""

    scenario: str = ""
    seed: int = 1337
    run_id: str = ""
    validation_feedback: list[ValidationFeedback] = field(default_factory=list)
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    step_telemetry: list[RunTelemetry] = field(default_factory=list)
    validation_retries: int = 0
    active_rule_count: int = 0

    def to_dict(self) -> dict:
        """Explicit JSON contract: no settings, credentials or raw held-out frames."""
        return {
            "scenario": self.scenario, "seed": self.seed, "run_id": self.run_id,
            "spec": self.spec.model_dump(mode="json"), "rule": self.rule.model_dump(mode="json"),
            "report": self.report.model_dump(mode="json"), "telemetry": self.telemetry.model_dump(mode="json"),
            "evidence": self.evidence.model_dump(mode="json"), "dataset_metadata": self.dataset_metadata,
            "validation_feedback": [f.model_dump(mode="json") for f in self.validation_feedback],
            "stage_timings_ms": self.stage_timings_ms,
            "step_telemetry": [t.model_dump(mode="json") for t in self.step_telemetry],
            "validation_retries": self.validation_retries, "active_rule_count": self.active_rule_count,
        }

    def __post_init__(self) -> None:
        _validate_metadata(self.dataset_metadata)
        allowed = set(self.evidence.permitted_fields)
        if not allowed.issubset(ALLOWED_FIELDS):
            raise ValueError("Evidence may contain only permitted features")
        for row in self.evidence.missed_fraud + self.evidence.lookalike_legit:
            if not set(row).issubset(allowed):
                raise ValueError("Evidence rows contain forbidden fields")
            if any(not isinstance(value, (str, int, float)) for value in row.values()):
                raise ValueError("Evidence features must be scalar values")
        # Summary statistics are aggregate JSON data, never arbitrary objects.
        self.evidence.model_dump_json()


class PipelineError(RuntimeError):
    """Named internal stage failure without underlying data or secrets."""
    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"Pipeline stage failed: {stage}")


def run_redqueen(scenario: str, settings: Settings, mode: str | None = None,
                 *, client=None, sandbox=None, on_stage=None) -> PipelineResult:
    """Shared CLI/UI flow: bounded proposals, one revision, one final evaluation."""
    from redqueen.attack_lab import _sanitize_scenario, generate_attack_spec
    from redqueen.defender_forge import propose_rule
    from redqueen.gemma_client import GemmaApiError, GemmaClient, MissingApiKeyError, resolve_mode
    from redqueen.verification import SandboxState, VerificationGate

    clean = _sanitize_scenario(scenario)
    requested = mode if mode is not None else settings.mode
    if requested not in {"live", "replay"}:
        raise ValueError("Mode must be live or replay")
    settings = settings.model_copy(update={"mode": requested})
    actual_mode = resolve_mode(settings)
    state = sandbox if sandbox is not None else SandboxState()
    run_id = uuid4().hex
    timings = {}
    telemetry = []

    def stage(name, operation):
        if on_stage is not None:
            on_stage(name)
        started = time.perf_counter()
        try:
            return operation()
        except (GemmaApiError, MissingApiKeyError):
            raise
        except Exception:
            raise PipelineError(name) from None
        finally:
            timings[name] = (time.perf_counter()-started)*1000

    if actual_mode == "live" and client is None:
        client = stage("Live API initialization", lambda: GemmaClient(settings))
    spec, attack_telemetry = stage("Attack Lab", lambda: generate_attack_spec(clean, client, actual_mode))
    telemetry.append(attack_telemetry)
    simulation = stage("Synthetic simulator", lambda: SimulationBoundary(spec, settings.seed, settings))
    baseline = BaselineDetector()
    evidence_detector = BaselineDetector()
    evidence_detector.rules.extend(state.active_rules)
    evidence = stage("Baseline failure evidence", lambda: simulation.build_sample_evidence(evidence_detector))
    gate = VerificationGate(settings, spec, active_rules=state.active_rules, run_id=run_id)

    def forge(feedback):
        rule, step = propose_rule(evidence, client, actual_mode, feedback,
                                  replay_scenario=attack_telemetry.replay_scenario)
        telemetry.append(step)
        return rule

    rule = stage("Defender Forge", lambda: forge(None))
    feedback = stage("Validation gate", lambda: simulation.evaluate_validation(gate, rule, baseline))
    feedbacks = [feedback]
    retry = settings.max_validation_retries > 0 and (
        feedback.recall_gain_bucket == "none" or feedback.fpr_exceeded or feedback.segment_violation)
    if retry:
        rule = stage("Defender Forge revision", lambda: forge(feedback))
        feedbacks.append(stage("Validation revision", lambda: simulation.evaluate_validation(gate, rule, baseline)))
    report = stage("Sealed verification (once)", lambda: simulation.evaluate_final(gate, rule, baseline, state.approved_attacks))
    if report.verdict == "ACCEPTED":
        stage("Sandbox activation", lambda: state.activate(rule, report, spec=spec))
    else:
        state.audit.append(report.model_dump(mode="json"))
    models = list(dict.fromkeys(t.model_used for t in telemetry if t.model_used))
    total = RunTelemetry(mode=actual_mode, model_used=", ".join(models) or None,
        model_latency_ms=sum(t.model_latency_ms or 0 for t in telemetry) if actual_mode=="live" else None,
        verification_latency_ms=report.latency_ms, attempts=sum(t.attempts for t in telemetry),
        replay_scenario=attack_telemetry.replay_scenario, replay_match=attack_telemetry.replay_match)
    return PipelineResult(spec=spec, rule=rule, report=report, telemetry=total, evidence=evidence,
        dataset_metadata=simulation.metadata, scenario=clean, seed=settings.seed, run_id=run_id,
        validation_feedback=feedbacks, stage_timings_ms=timings, step_telemetry=telemetry,
        validation_retries=int(retry), active_rule_count=len(state.active_rules))
