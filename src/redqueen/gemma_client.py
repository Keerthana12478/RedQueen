"""Bounded Gemma JSON adapter. Model proposals are data, never executable code.

Capability calls are separate from each proposal's maximum three API requests.
Native output requires a successful round-trip; other schemas use prompt JSON.
No replay substitution occurs.
"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Any, Literal
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)
_KEY_RE = re.compile(r"AIza[0-9A-Za-z\-_]{30,}")

class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _KEY_RE.sub("[REDACTED]", record.getMessage())
        record.args = ()
        return True

logger.addFilter(_RedactFilter())

class MissingApiKeyError(RuntimeError):
    """Live mode has no credential."""

class GemmaApiError(RuntimeError):
    CATEGORIES = frozenset({"auth", "rate_limit", "timeout", "unavailable", "bad_output"})
    def __init__(self, message: str, category: str) -> None:
        super().__init__(_KEY_RE.sub("[REDACTED]", message))
        self.category = category if category in self.CATEGORIES else "unavailable"

class GemmaOutputError(GemmaApiError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "bad_output")

class CapabilityProbe(BaseModel):
    model_config = {"extra": "forbid"}
    model_available: bool
    auth_ok: bool
    structured_output_ok: bool | Literal["unknown"]
    function_calling_ok: bool | Literal["unknown"]
    latency_ms: float | None
    model_used: str | None = None
    error_category: str | None = None
    error_detail: str | None = None
    attempts: int = 0

_STRIP_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)

def _strip_fences(text: str) -> str:
    match = _STRIP_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text.strip()

class GemmaClient:
    _MAX_OUTPUT_RETRIES = 2
    _BACKOFF_BASE_S = 1.5

    def __init__(self, settings: Any) -> None:
        key = settings.api_key
        if key is None or not key.get_secret_value().strip():
            raise MissingApiKeyError("No GEMINI_API_KEY — live mode unavailable, use replay")
        self._key = key.get_secret_value().strip()
        self._model = settings.model
        self._fallback = settings.fallback_model
        self._resolved_model = self._model
        self._probe_cache: CapabilityProbe | None = None
        self.last_attempts = 0
        self.total_api_calls = 0
        self.last_output_path = "schema-in-prompt"

    def __repr__(self) -> str:
        return f"GemmaClient(model={self._model!r})"

    def _make_client(self) -> Any:
        from google import genai
        from google.genai import types
        return genai.Client(api_key=self._key, http_options=types.HttpOptions(
            timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))

    def _classify_api_error(self, exc: Exception) -> str:
        message = str(exc).lower()
        code = str(getattr(exc, "code", ""))
        if code in {"401", "403"} or any(x in message for x in (
                "api_key", "api key", "unauthorized", "permission", "401", "403")):
            return "auth"
        if code == "429" or any(x in message for x in ("quota", "rate limit", "429")):
            return "rate_limit"
        if any(x in message for x in ("timeout", "timed out", "deadline")):
            return "timeout"
        return "unavailable"

    def _safe_error(self, exc: Exception) -> GemmaApiError:
        category = self._classify_api_error(exc)
        code = getattr(exc, "code", None)
        detail = f"HTTP {code}; " if isinstance(code, int) or (isinstance(code, str) and code.isdigit()) else ""
        return GemmaApiError(f"Gemma API {category} ({detail}{type(exc).__name__})", category)

    def _call_once(self, client: Any, model: str, prompt: str, *, system: str | None,
                   temperature: float, max_output_tokens: int, use_native_schema: bool,
                   schema_model: type[BaseModel] | None) -> str:
        from google.genai import types
        config: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_output_tokens}
        if system:
            config["system_instruction"] = system
        if use_native_schema and schema_model is not None:
            config.update(response_mime_type="application/json", response_schema=schema_model)
        self.total_api_calls = getattr(self, "total_api_calls", 0) + 1
        response = client.models.generate_content(
            model=model, contents=prompt, config=types.GenerateContentConfig(**config))
        if isinstance(response.text, str):
            return response.text
        try:
            return "".join(p.text for p in response.candidates[0].content.parts
                           if not getattr(p, "thought", False) and p.text)
        except (AttributeError, IndexError, TypeError):
            return ""

    def probe_capabilities(self, *, force: bool = False) -> CapabilityProbe:
        if self._probe_cache is not None and not force:
            return self._probe_cache
        started = time.perf_counter()
        attempts = 0
        model = self._model
        try:
            client = self._make_client()
            try:
                attempts += 1
                answer = self._call_once(client, model, "Reply with the single word: ok",
                    system=None, temperature=0.0, max_output_tokens=2048,
                    use_native_schema=False, schema_model=None)
            except Exception as exc:
                if self._classify_api_error(exc) != "unavailable" or self._fallback == model:
                    raise
                model = self._fallback
                attempts += 1
                answer = self._call_once(client, model, "Reply with the single word: ok",
                    system=None, temperature=0.0, max_output_tokens=2048,
                    use_native_schema=False, schema_model=None)
            if not answer.strip():
                raise GemmaOutputError("Connectivity probe returned no answer")
            self._resolved_model = model
            class Ping(BaseModel):
                ok: bool
            structured: bool | str = "unknown"
            try:
                attempts += 1
                raw = self._call_once(client, model, 'Return JSON {"ok": true}',
                    system=None, temperature=0.0, max_output_tokens=2048,
                    use_native_schema=True, schema_model=Ping)
                structured = Ping.model_validate_json(raw).ok is True
            except Exception as exc:
                message = str(exc).lower()
                if any(x in message for x in ("not supported", "unsupported", "400")):
                    structured = False
                logger.info("Structured probe inconclusive/unsupported: %s", type(exc).__name__)
            result = CapabilityProbe(model_available=True, auth_ok=True,
                structured_output_ok=structured, function_calling_ok="unknown",
                latency_ms=(time.perf_counter() - started) * 1000, model_used=model,
                attempts=attempts)
        except Exception as exc:
            safe = self._safe_error(exc)
            result = CapabilityProbe(model_available=False, auth_ok=False,
                structured_output_ok="unknown", function_calling_ok="unknown",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_category=safe.category, error_detail=str(safe), attempts=attempts)
        self._probe_cache = result
        logger.info("Optional function calling skipped (untested)")
        return result

    def generate_json(self, prompt: str, schema_model: type[BaseModel], *,
                      system: str | None = None, temperature: float = 0.2,
                      max_output_tokens: int = 4096) -> tuple[BaseModel, float, str]:
        if not 1 <= max_output_tokens <= 8192:
            raise ValueError("max_output_tokens must be in [1, 8192]")
        # Probing is explicit: no hidden requests within the proposal budget.
        probe = self._probe_cache
        native = probe is not None and probe.structured_output_ok is True
        schema = schema_model.model_json_schema()
        if "prefixItems" in json.dumps(schema):
            native = False
        hint = "\nReturn only JSON matching this schema:\n" + json.dumps(schema)
        full_prompt = prompt if native else prompt + hint
        model = getattr(self, "_resolved_model", self._model)
        fallback_used = model != self._model
        transient_retried = False
        last_error = "No valid JSON response"
        client = self._make_client()
        started = time.perf_counter()
        self.last_attempts = 0
        self.last_output_path = "native" if native else "schema-in-prompt"
        for attempt in range(3):
            self.last_attempts += 1
            try:
                raw = self._call_once(client, model, full_prompt, system=system,
                    temperature=temperature, max_output_tokens=max_output_tokens,
                    use_native_schema=native, schema_model=schema_model)
            except Exception as exc:
                category = self._classify_api_error(exc)
                if category == "unavailable" and not fallback_used and self._fallback != model and attempt < 2:
                    model, fallback_used = self._fallback, True
                    continue
                if category in {"rate_limit", "timeout", "unavailable"} and not transient_retried and attempt < 2:
                    transient_retried = True
                    time.sleep(self._BACKOFF_BASE_S)
                    continue
                raise self._safe_error(exc) from None
            try:
                instance = schema_model.model_validate(json.loads(_strip_fences(raw)))
                self._resolved_model = model
                latency = (time.perf_counter() - started) * 1000
                logger.info("JSON proposal: chars=%d calls=%d latency_ms=%.0f", len(prompt), self.last_attempts, latency)
                return instance, latency, model
            except (ValueError, TypeError, ValidationError) as exc:
                if isinstance(exc, ValidationError):
                    last_error = json.dumps(exc.errors(include_input=False, include_context=False))[:500]
                else:
                    last_error = "Malformed or truncated JSON"
                native = False
                self.last_output_path = "schema-in-prompt"
                full_prompt = prompt + hint + "\nPrevious output failed validation: " + last_error
        raise GemmaOutputError(f"Invalid model JSON after {self.last_attempts} calls: {last_error}")

    def smoke_test(self) -> bool:
        probe = self.probe_capabilities(force=True)
        return probe.auth_ok and probe.model_available

def resolve_mode(settings: Any, client_probe: CapabilityProbe | None = None) -> str:
    requested = (getattr(settings, "mode", None) or "live").lower()
    if requested not in {"live", "replay"}:
        raise ValueError("Mode must be live or replay")
    if requested == "live" and client_probe is not None:
        if not client_probe.auth_ok or not client_probe.model_available:
            raise GemmaApiError(client_probe.error_detail or "Live API unavailable; choose replay explicitly",
                                client_probe.error_category or "unavailable")
    return requested
