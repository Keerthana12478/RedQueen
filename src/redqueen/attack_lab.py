"""RedQueen — attack specification generator (stub).

Phase 3 implements this module.  Signatures are **frozen**; do not rename.
"""
from __future__ import annotations

from redqueen.gemma_client import GemmaClient
from redqueen.schemas import AttackSpec, RunTelemetry


def generate_attack_spec(
    scenario: str,
    client: GemmaClient | None,
    mode: str,
) -> tuple[AttackSpec, RunTelemetry]:
    """Turn a natural-language fraud scenario into a typed :class:`AttackSpec`.

    In *live* mode the Gemma model interprets *scenario*; in *replay* mode a
    pre-recorded response is loaded from ``data/replay/``.

    Args:
        scenario: Human-readable description of the fraud attack.
        client: A :class:`~redqueen.gemma_client.GemmaClient` instance (live
            mode) or ``None`` (replay mode).
        mode: ``"live"`` or ``"replay"``.

    Returns:
        A ``(AttackSpec, RunTelemetry)`` tuple.

    Raises:
        NotImplementedError: Until Phase 3 is implemented.
    """
    raise NotImplementedError("generate_attack_spec: implemented in Phase 3")
