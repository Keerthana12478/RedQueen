"""RedQueen — Gemma API client (stub).

Phase 3 implements this module.  Signatures are **frozen**; do not rename.

INVARIANT: No network calls at import time.  ``GemmaClient`` is only
instantiated at runtime when mode == "live".  Secrets are never logged.
"""
from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel


class GemmaClient:
    """Thin wrapper around the ``google-genai`` SDK for structured JSON generation.

    Uses ``REDQUEEN_MODEL`` with ``REDQUEEN_FALLBACK_MODEL`` on failure.
    The API key is read from :class:`~redqueen.config.Settings` and is never
    printed or logged.
    """

    def generate_json(
        self,
        prompt: str,
        schema_model: Type[BaseModel],
        *,
        temperature: float = 0.2,
        max_retries: int = 2,
    ) -> BaseModel:
        """Call the model and parse the response into *schema_model*.

        Args:
            prompt: The full prompt string to send.
            schema_model: A Pydantic model class; the response is validated
                against it and returned as an instance.
            temperature: Sampling temperature (0 = deterministic).
            max_retries: How many times to retry on transient API errors.

        Returns:
            A validated instance of *schema_model*.

        Raises:
            NotImplementedError: Until Phase 3 is implemented.
        """
        raise NotImplementedError("GemmaClient.generate_json: implemented in Phase 3")

    def smoke_test(self) -> bool:
        """Send a minimal probe request to verify connectivity and key validity.

        Returns:
            ``True`` if the API is reachable and returns a valid response.

        Raises:
            NotImplementedError: Until Phase 3 is implemented.
        """
        raise NotImplementedError("GemmaClient.smoke_test: implemented in Phase 3")
