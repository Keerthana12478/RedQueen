"""RedQueen — top-level pipeline orchestrator (stub).

Phase 5 completes the orchestration; Phase 6 hardens it.
Signatures are **frozen**; do not rename.

INVARIANTS:
- :class:`PipelineResult` never contains raw sealed or validation rows.
- The pipeline passes the sealed DataFrame opaquely to the verification gate
  and must not inspect sealed metrics itself.
"""
from __future__ import annotations

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
        approved_attacks: list[str],
    ) -> VerificationReport:
        """Transfer the sealed capability only to the final gate method.

        One-shot evaluation and rejection of zero target positives belong to
        the Phase 4 gate, whose implementation remains out of Phase 2 scope.
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


def run_redqueen(
    scenario: str,
    settings: Settings,
    mode: str | None = None,
) -> PipelineResult:
    """Run the full RedQueen pipeline end-to-end.

    Steps (orchestrated here; each step is implemented in its own module):
    1. Generate or load :class:`~redqueen.schemas.AttackSpec` (attack_lab).
    2. Synthesise datasets (simulator).
    3. Fit and run baseline detector (baseline).
    4. Build failure-analysis evidence from sample split (failure_analysis).
    5. Propose defense rule via Gemma (defender_forge).
    6. Validate on validation split; optionally retry (verification).
    7. Final sealed evaluation (verification).
    8. Return :class:`PipelineResult`.

    Args:
        scenario: Natural-language fraud scenario description.
        settings: Application settings.
        mode: Override for ``settings.mode`` (``"live"`` or ``"replay"``).

    Returns:
        A :class:`PipelineResult` with all outputs.

    Raises:
        NotImplementedError: Until Phase 5 is implemented.
    """
    raise NotImplementedError("run_redqueen: implemented in Phase 5")
