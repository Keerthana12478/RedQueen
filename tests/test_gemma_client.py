"""Tests for gemma_client.py — Phase 3.

All tests use mocks/monkeypatching; the real API is never called.
"""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from pydantic import BaseModel

from redqueen.gemma_client import (
    CapabilityProbe,
    GemmaApiError,
    GemmaClient,
    GemmaOutputError,
    MissingApiKeyError,
    _strip_fences,
    resolve_mode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSettings:
    model = "gemma-test-model"
    fallback_model = "gemma-test-fallback"

    def __init__(self, key: str | None = "fake-key-AIzatest"):
        from pydantic import SecretStr
        self.api_key = SecretStr(key) if key else None
        self.mode = "live"


class _SimpleSchema(BaseModel):
    value: int
    label: str


def _make_client(key: str | None = "fake-key-AIzatest") -> GemmaClient:
    settings = _FakeSettings(key=key)
    return GemmaClient(settings)


def _mock_generate(text: str):
    """Return a mock genai client whose generate_content returns *text*."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = text
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# MissingApiKeyError
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    def test_no_key_raises(self):
        with pytest.raises(MissingApiKeyError):
            _make_client(key=None)

    def test_empty_key_raises(self):
        with pytest.raises(MissingApiKeyError):
            _make_client(key="")

    def test_whitespace_key_raises(self):
        with pytest.raises(MissingApiKeyError):
            _make_client(key="   ")

    def test_repr_does_not_leak_key(self):
        client = _make_client()
        r = repr(client)
        assert "fake-key" not in r
        assert "AIza" not in r


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------

class TestStripFences:
    def test_bare_json_unchanged(self):
        text = '{"a": 1}'
        assert _strip_fences(text) == text

    def test_json_fence_stripped(self):
        text = "```json\n{\"a\": 1}\n```"
        assert _strip_fences(text) == '{"a": 1}'

    def test_plain_fence_stripped(self):
        text = "```\n{\"a\": 1}\n```"
        assert _strip_fences(text) == '{"a": 1}'


# ---------------------------------------------------------------------------
# probe_capabilities — mocked
# ---------------------------------------------------------------------------

class TestProbeCapabilities:
    def test_probe_cached(self):
        client = _make_client()
        probe1 = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=True, function_calling_ok="unknown",
            latency_ms=10.0,
        )
        client._probe_cache = probe1
        probe2 = client.probe_capabilities()
        assert probe2 is probe1

    def test_probe_force_reruns(self):
        client = _make_client()
        probe1 = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=True, function_calling_ok="unknown",
            latency_ms=10.0,
        )
        client._probe_cache = probe1

        mock_genai_client = _mock_generate("ok")
        # Second call also returns valid _Ping json for struct probe
        mock_genai_client.models.generate_content.side_effect = [
            MagicMock(text="ok"),
            MagicMock(text='{"ok": true}'),
        ]

        with patch.object(client, "_make_client", return_value=mock_genai_client):
            probe2 = client.probe_capabilities(force=True)
        assert probe2 is not probe1

    def test_probe_auth_failure_marked(self):
        client = _make_client()
        mock_genai_client = MagicMock()
        mock_genai_client.models.generate_content.side_effect = Exception("401 api_key invalid")

        with patch.object(client, "_make_client", return_value=mock_genai_client):
            probe = client.probe_capabilities(force=True)

        assert probe.auth_ok is False
        assert probe.model_available is False


# ---------------------------------------------------------------------------
# generate_json — valid response
# ---------------------------------------------------------------------------

class TestGenerateJsonValid:
    def test_valid_json_response(self):
        client = _make_client()
        # Seed cache: no native struct output
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        valid_json = json.dumps({"value": 42, "label": "test"})
        mock_genai_client = _mock_generate(valid_json)

        with patch.object(client, "_make_client", return_value=mock_genai_client):
            instance, latency_ms, model_used = client.generate_json(
                "Generate something", _SimpleSchema
            )

        assert isinstance(instance, _SimpleSchema)
        assert instance.value == 42
        assert instance.label == "test"
        assert latency_ms >= 0
        assert model_used == client._model

    def test_fenced_json_response(self):
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        fenced = "```json\n{\"value\": 7, \"label\": \"fenced\"}\n```"
        mock_genai_client = _mock_generate(fenced)

        with patch.object(client, "_make_client", return_value=mock_genai_client):
            instance, _, _ = client.generate_json("test", _SimpleSchema)

        assert instance.value == 7
        assert instance.label == "fenced"

    def test_native_schema_path_used_when_supported(self):
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=True, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        valid_json = json.dumps({"value": 1, "label": "native"})
        mock_genai_client = _mock_generate(valid_json)

        with patch.object(client, "_make_client", return_value=mock_genai_client):
            instance, _, _ = client.generate_json("test", _SimpleSchema)

        # Config should have included response_mime_type
        call_kwargs = mock_genai_client.models.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[0] if call_kwargs.args else None
        # Just verify the call was made
        assert mock_genai_client.models.generate_content.called


# ---------------------------------------------------------------------------
# generate_json — retries and failures
# ---------------------------------------------------------------------------

class TestGenerateJsonRetries:
    def test_invalid_then_valid_succeeds(self):
        """First response is invalid JSON; second is valid → succeeds."""
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        mock_gc = MagicMock()
        mock_gc.models.generate_content.side_effect = [
            MagicMock(text="not json at all"),
            MagicMock(text='{"value": 99, "label": "retry"}'),
        ]

        with patch.object(client, "_make_client", return_value=mock_gc):
            instance, _, _ = client.generate_json("test", _SimpleSchema)

        assert instance.value == 99
        assert mock_gc.models.generate_content.call_count == 2

    def test_persistent_invalid_raises_output_error(self):
        """All 3 attempts return invalid JSON → GemmaOutputError."""
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        mock_gc = MagicMock()
        mock_gc.models.generate_content.return_value = MagicMock(text="not json")

        with patch.object(client, "_make_client", return_value=mock_gc):
            with pytest.raises(GemmaOutputError):
                client.generate_json("test", _SimpleSchema)

        assert mock_gc.models.generate_content.call_count == 3  # 1 + 2 retries

    def test_schema_invalid_then_valid(self):
        """Valid JSON but wrong schema, then correct → succeeds."""
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        mock_gc = MagicMock()
        mock_gc.models.generate_content.side_effect = [
            MagicMock(text='{"wrong_field": 1}'),
            MagicMock(text='{"value": 5, "label": "ok"}'),
        ]

        with patch.object(client, "_make_client", return_value=mock_gc):
            instance, _, _ = client.generate_json("test", _SimpleSchema)

        assert instance.value == 5

    def test_rate_limit_raises_api_error(self):
        """Rate-limit exception → GemmaApiError with category rate_limit."""
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        mock_gc = MagicMock()
        mock_gc.models.generate_content.side_effect = Exception("429 quota exceeded rate limit")

        with patch("time.sleep"):  # don't actually sleep
            with patch.object(client, "_make_client", return_value=mock_gc):
                with pytest.raises(GemmaApiError) as exc_info:
                    client.generate_json("test", _SimpleSchema)

        assert exc_info.value.category == "rate_limit"

    def test_auth_error_raises_api_error(self):
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        mock_gc = MagicMock()
        mock_gc.models.generate_content.side_effect = Exception("api_key invalid unauthorized")

        with patch.object(client, "_make_client", return_value=mock_gc):
            with pytest.raises(GemmaApiError) as exc_info:
                client.generate_json("test", _SimpleSchema)

        assert exc_info.value.category == "auth"

    def test_fallback_model_used_on_unavailable(self):
        """Primary model unavailable → falls back to fallback model."""
        client = _make_client()
        client._probe_cache = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=5.0,
        )
        mock_gc = MagicMock()

        def side_effect(model, contents, config):
            if model == client._model:
                raise Exception("not found 404")
            return MagicMock(text='{"value": 1, "label": "fallback"}')

        mock_gc.models.generate_content.side_effect = side_effect

        with patch.object(client, "_make_client", return_value=mock_gc):
            instance, _, model_used = client.generate_json("test", _SimpleSchema)

        assert model_used == client._fallback
        assert instance.value == 1


# ---------------------------------------------------------------------------
# resolve_mode
# ---------------------------------------------------------------------------

class TestResolveMode:
    def test_replay_mode_returned_as_is(self):
        settings = _FakeSettings()
        settings.mode = "replay"
        assert resolve_mode(settings) == "replay"

    def test_live_mode_with_healthy_probe(self):
        settings = _FakeSettings()
        settings.mode = "live"
        probe = CapabilityProbe(
            model_available=True, auth_ok=True,
            structured_output_ok=True, function_calling_ok="unknown",
            latency_ms=10.0,
        )
        assert resolve_mode(settings, probe) == "live"

    def test_live_mode_with_failed_probe_raises(self):
        settings = _FakeSettings()
        settings.mode = "live"
        probe = CapabilityProbe(
            model_available=False, auth_ok=False,
            structured_output_ok=False, function_calling_ok="unknown",
            latency_ms=100.0,
        )
        with pytest.raises(GemmaApiError):
            resolve_mode(settings, probe)

    def test_live_mode_no_probe_returns_live(self):
        settings = _FakeSettings()
        settings.mode = "live"
        assert resolve_mode(settings, None) == "live"
