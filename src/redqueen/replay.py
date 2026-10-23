"""RedQueen — replay scenario loader (Phase 3 implementation).

Replay scenarios are stored as JSON files in ``data/replay/``.
Each file contains a pre-validated ``AttackSpec``, a ``DefenseRule``, and
a ``label: "REPLAY"`` marker.  Replay mode never calls the live API and
never presents output as Gemma-generated.

Matching precedence:
  1. Exact ``name`` match (case-insensitive).
  2. Highest keyword-overlap score (visible to caller as "closest match").
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Canonical location of replay scenario files
_REPLAY_DIR = Path(__file__).parent.parent.parent / "data" / "replay"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_replay_scenarios() -> list[str]:
    """Return the names of all available replay scenarios.

    Returns:
        List of scenario name strings (from the ``name`` field of each JSON).
    """
    names: list[str] = []
    for path in sorted(_REPLAY_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            names.append(data["name"])
        except Exception as exc:
            logger.warning("Skipping replay file %s: %s", path.name, exc)
    return names


def load_replay(name: str) -> dict[str, Any]:
    """Load a pre-recorded replay scenario by name.

    Matching is first attempted by exact name (case-insensitive), then by
    highest keyword-overlap score.  The returned dict always includes a
    ``"_matched_name"`` key indicating which scenario was selected and a
    ``"_match_type"`` key (``"exact"`` or ``"closest"``) so callers can
    surface this to the user.

    Args:
        name: Scenario name or free-text description.

    Returns:
        Dict with keys ``name``, ``scenario_text``, ``attack_spec``,
        ``proposed_rule``, ``label``, ``_matched_name``, ``_match_type``.

    Raises:
        FileNotFoundError: If no replay scenarios exist.
        KeyError: If no scenario can be matched.
    """
    scenarios: list[dict[str, Any]] = []
    for path in sorted(_REPLAY_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_source_file"] = path.name
            scenarios.append(data)
        except Exception as exc:
            logger.warning("Skipping replay file %s: %s", path.name, exc)

    if not scenarios:
        raise FileNotFoundError(
            f"No replay scenarios found in {_REPLAY_DIR}. "
            "Ensure data/replay/*.json files are present."
        )

    # Exact match (case-insensitive)
    name_lower = name.strip().lower()
    for scenario in scenarios:
        if scenario.get("name", "").lower() == name_lower:
            result = dict(scenario)
            result["_matched_name"] = scenario["name"]
            result["_match_type"] = "exact"
            return result

    # Keyword-overlap fallback
    query_tokens = _tokenize(name_lower)
    best_score = -1
    best_scenario: dict[str, Any] | None = None
    for scenario in scenarios:
        candidate_text = " ".join([
            scenario.get("name", ""),
            scenario.get("scenario_text", ""),
        ]).lower()
        score = _overlap(query_tokens, _tokenize(candidate_text))
        if score > best_score:
            best_score = score
            best_scenario = scenario

    if best_scenario is None:
        raise KeyError(f"No replay scenario matched {name!r}")

    result = dict(best_scenario)
    result["_matched_name"] = best_scenario["name"]
    result["_match_type"] = "closest"
    logger.info(
        "Replay: free-text %r matched closest scenario %r (score=%d)",
        name, best_scenario["name"], best_score,
    )
    return result


def load_replay_validated(name: str) -> dict[str, Any]:
    """Load a replay scenario and validate its embedded specs with Pydantic.

    Returns the same dict as :func:`load_replay` but with ``attack_spec`` and
    ``proposed_rule`` as validated Pydantic model instances.

    Raises:
        ValueError: If embedded specs fail schema validation.
    """
    from redqueen.schemas import AttackSpec, DefenseRule

    raw = load_replay(name)

    try:
        raw["attack_spec"] = AttackSpec.model_validate(raw["attack_spec"])
    except Exception as exc:
        raise ValueError(
            f"Replay scenario {raw['name']!r} has invalid attack_spec: {exc}"
        ) from exc

    try:
        raw["proposed_rule"] = DefenseRule.model_validate(raw["proposed_rule"])
    except Exception as exc:
        raise ValueError(
            f"Replay scenario {raw['name']!r} has invalid proposed_rule: {exc}"
        ) from exc

    if raw.get("label") != "REPLAY":
        raise ValueError(
            f"Replay scenario {raw['name']!r} is missing label: \"REPLAY\""
        )

    return raw


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({"a", "an", "the", "of", "in", "at", "on", "with", "for", "and", "or"})


def _tokenize(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(t for t in tokens if t not in _STOPWORDS)


def _overlap(a: frozenset[str], b: frozenset[str]) -> int:
    return len(a & b)
