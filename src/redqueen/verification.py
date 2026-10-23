"""RedQueen — deterministic verification gate (stub).

Phase 4 implements this module.  Signatures are **frozen**; do not rename.

INVARIANTS:
- Sealed data is consumed **only** inside :meth:`VerificationGate.evaluate_final`.
- The gate never exposes sealed rows to the model, dashboard, or retry logic.
- All metrics are computed from simulator output — no hardcoded PPT numbers.
"""
from __future__ import annotations

import pandas as pd

from redqueen.baseline import BaselineDetector
from redqueen.schemas import (
    DefenseRule,
    ValidationFeedback,
    VerificationReport,
)


class VerificationGate:
    """Pure-Python verification gate — no model calls, no ``eval``/``exec``."""

    def evaluate_validation(
        self,
        rule: DefenseRule,
        datasets: dict[str, pd.DataFrame],
        baseline: BaselineDetector,
    ) -> ValidationFeedback:
        """Evaluate a candidate rule on the **validation split** only.

        Returns coarse signal (no exact metrics) to avoid overfitting.

        Args:
            rule: Candidate defense rule.
            datasets: Dict with at least a ``"validation"`` key.
            baseline: Fitted baseline detector.

        Returns:
            A :class:`~redqueen.schemas.ValidationFeedback` with coarse buckets.

        Raises:
            NotImplementedError: Until Phase 4 is implemented.
        """
        raise NotImplementedError(
            "VerificationGate.evaluate_validation: implemented in Phase 4"
        )

    def evaluate_final(
        self,
        rule: DefenseRule,
        datasets: dict[str, pd.DataFrame],
        baseline: BaselineDetector,
        approved_attacks: list[str],
    ) -> VerificationReport:
        """Evaluate the final candidate on the **sealed split** (one-shot only).

        Sealed rows are never returned to callers; only aggregate metrics are
        exposed via :class:`~redqueen.schemas.VerificationReport`.

        Args:
            rule: The rule to evaluate (must have passed validation).
            datasets: Dict with at least a ``"sealed"`` key.
            baseline: Fitted baseline detector.
            approved_attacks: Attack names that the rule is expected to address.

        Returns:
            A :class:`~redqueen.schemas.VerificationReport`.

        Raises:
            NotImplementedError: Until Phase 4 is implemented.
        """
        raise NotImplementedError(
            "VerificationGate.evaluate_final: implemented in Phase 4"
        )
