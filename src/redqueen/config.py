"""RedQueen — frozen application settings loaded from environment / .env file.

Loaded using python-dotenv + pure Pydantic v2 (no pydantic-settings dependency).
The API key is a :class:`pydantic.SecretStr`; its value is **never** printed or
logged — repr/str deliberately hide it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr

# Load .env if present; never overrides already-set environment variables.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Settings(BaseModel):
    """Frozen application settings.

    All fields have sane defaults so ``Settings()`` works without a .env file
    or any environment variables set — useful for testing and offline use.
    """

    # ------------------------------------------------------------------ core
    seed: int = 1337
    mode: Literal["live", "replay"] = "live"
    model: str = "gemma-4-31b-it"
    fallback_model: str = "gemma-4-26b-a4b-it"
    api_key: SecretStr = SecretStr("")

    # ------------------------------------------------------------------ split sizes
    n_sample: int = 2000
    n_validation: int = 5000
    n_sealed: int = 10_000

    # ------------------------------------------------------------------ thresholds (configurable design values)
    global_fpr_ceiling: float = 0.015
    min_recall_gain_pp: float = 5.0
    segment_fpr_budget: float = 0.03
    max_clauses: int = 3
    max_validation_retries: int = 1   # one optional retry → at most two evaluations
    min_segment_legit_count: int = 50

    model_config = {"frozen": True}

    @classmethod
    def from_env(cls) -> "Settings":
        """Construct Settings by reading the relevant environment variables."""
        seed_raw = _env("REDQUEEN_SEED", "1337")
        return cls(
            seed=int(seed_raw),
            mode=_env("REDQUEEN_MODE", "live"),  # type: ignore[arg-type]
            model=_env("REDQUEEN_MODEL", "gemma-4-31b-it"),
            fallback_model=_env("REDQUEEN_FALLBACK_MODEL", "gemma-4-26b-a4b-it"),
            api_key=SecretStr(_env("GEMINI_API_KEY", "")),
        )

    def __repr__(self) -> str:
        key_status = "set" if self.api_key.get_secret_value() else "unset"
        return (
            f"Settings(mode={self.mode!r}, model={self.model!r}, "
            f"fallback_model={self.fallback_model!r}, seed={self.seed}, "
            f"api_key=<{key_status}>)"
        )

    __str__ = __repr__
