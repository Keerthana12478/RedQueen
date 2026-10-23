"""RedQueen — defense rule proposer (stub).

Phase 3 implements this module.  Signatures are **frozen**; do not rename.
"""
from __future__ import annotations

from redqueen.gemma_client import GemmaClient
from redqueen.schemas import DefenseRule, Evidence, RunTelemetry, ValidationFeedback


def propose_rule(
    evidence: Evidence,
    client: GemmaClient | None,
    mode: str,
    feedback: ValidationFeedback | None,
) -> tuple[DefenseRule, RunTelemetry]:
    """Ask Gemma to propose a declarative :class:`DefenseRule` given evidence.

    Gemma proposes; Python verifies.  Gemma never grades its own rule.

    Args:
        evidence: Failure analysis from the sample split.
        client: Live client or ``None`` for replay.
        mode: ``"live"`` or ``"replay"``.
        feedback: Optional coarse validation feedback from a prior attempt
            (used during the optional retry).

    Returns:
        A ``(DefenseRule, RunTelemetry)`` tuple.

    Raises:
        NotImplementedError: Until Phase 3 is implemented.
    """
    raise NotImplementedError("propose_rule: implemented in Phase 3")
