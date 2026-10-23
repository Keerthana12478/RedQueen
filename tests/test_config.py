"""Phase 1 tests — Settings / config.

Covers:
- Default construction without any env vars or API key
- Settings.from_env() picks up overrides
- repr/str do not leak the API key value
- Frozen model rejects mutation
"""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from redqueen.config import Settings


# ---------------------------------------------------------------------------
# 1. Default construction (no env, no key)
# ---------------------------------------------------------------------------

def test_defaults_load_without_api_key(monkeypatch):
    """Settings() must work with no API key present."""
    # Make sure no API key leaks in from the environment
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("REDQUEEN_MODE", raising=False)
    monkeypatch.delenv("REDQUEEN_MODEL", raising=False)
    monkeypatch.delenv("REDQUEEN_SEED", raising=False)

    s = Settings()
    assert s.seed == 1337
    assert s.mode == "live"
    assert s.model == "gemma-4-31b-it"
    assert s.fallback_model == "gemma-4-26b-a4b-it"
    assert s.api_key.get_secret_value() == ""


def test_default_split_sizes():
    s = Settings()
    assert s.n_sample == 2000
    assert s.n_validation == 5000
    assert s.n_sealed == 10_000


def test_default_thresholds():
    s = Settings()
    assert s.global_fpr_ceiling == pytest.approx(0.015)
    assert s.min_recall_gain_pp == pytest.approx(5.0)
    assert s.segment_fpr_budget == pytest.approx(0.03)
    assert s.max_clauses == 3
    assert s.max_validation_retries == 1
    assert s.min_segment_legit_count == 50


# ---------------------------------------------------------------------------
# 2. from_env() picks up environment overrides
# ---------------------------------------------------------------------------

def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("REDQUEEN_SEED", "42")
    monkeypatch.setenv("REDQUEEN_MODE", "replay")
    monkeypatch.setenv("REDQUEEN_MODEL", "gemma-test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test-key")

    s = Settings.from_env()
    assert s.seed == 42
    assert s.mode == "replay"
    assert s.model == "gemma-test-model"
    assert s.api_key.get_secret_value() == "sk-test-key"


# ---------------------------------------------------------------------------
# 3. repr / str must NOT leak the API key value
# ---------------------------------------------------------------------------

def test_repr_does_not_leak_api_key():
    s = Settings(api_key="super-secret-key")  # type: ignore[arg-type]
    r = repr(s)
    assert "super-secret-key" not in r
    assert "super" not in r


def test_str_does_not_leak_api_key():
    s = Settings(api_key="my-secret-token")  # type: ignore[arg-type]
    assert "my-secret-token" not in str(s)


def test_repr_shows_set_when_key_present():
    s = Settings(api_key="any-value")  # type: ignore[arg-type]
    assert "set" in repr(s)


def test_repr_shows_unset_when_key_absent():
    s = Settings()
    assert "unset" in repr(s)


def test_secret_str_get_secret_value_works():
    """Calling get_secret_value() explicitly should return the actual key."""
    s = Settings(api_key="abc123")  # type: ignore[arg-type]
    assert s.api_key.get_secret_value() == "abc123"


# ---------------------------------------------------------------------------
# 4. Frozen model — mutation must be rejected
# ---------------------------------------------------------------------------

def test_frozen_rejects_mutation():
    s = Settings()
    with pytest.raises((ValidationError, TypeError)):
        s.seed = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. Mode literal enforcement
# ---------------------------------------------------------------------------

def test_invalid_mode_rejected():
    with pytest.raises((ValidationError, ValueError)):
        Settings(mode="production")  # type: ignore[arg-type]
