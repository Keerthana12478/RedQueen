"""RedQueen — replay scenario loader (stub).

Phase 3 implements this module.  Signatures are **frozen**; do not rename.
"""
from __future__ import annotations


def list_replay_scenarios() -> list[str]:
    """Return the names of all available replay scenarios.

    Returns:
        A list of scenario name strings found in ``data/replay/``.

    Raises:
        NotImplementedError: Until Phase 3 is implemented.
    """
    raise NotImplementedError("list_replay_scenarios: implemented in Phase 3")


def load_replay(name: str) -> dict:
    """Load a pre-recorded replay scenario by name.

    Args:
        name: Scenario name (as returned by :func:`list_replay_scenarios`).

    Returns:
        A dict containing the recorded :class:`~redqueen.schemas.AttackSpec`,
        :class:`~redqueen.schemas.DefenseRule`, and Gemma responses.

    Raises:
        NotImplementedError: Until Phase 3 is implemented.
    """
    raise NotImplementedError("load_replay: implemented in Phase 3")
