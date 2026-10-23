"""RedQueen smoke test for the Gemma integration.

Usage:
    python scripts/smoke_gemma.py

Exits:
    0  — all tested capabilities passed
    1  — auth or model error
    2  — no API key configured (offline; use replay mode)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make src/ importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()


def _row(label: str, value: object, width: int = 30) -> str:
    return f"  {label:<{width}} {value}"


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not api_key:
        print("=" * 60)
        print("RedQueen — Gemma Smoke Test")
        print("=" * 60)
        print()
        print("  No GEMINI_API_KEY found in environment.")
        print("  Live mode is unavailable.")
        print("  Use REDQUEEN_MODE=replay for offline operation.")
        print()
        print("  To test live mode: set GEMINI_API_KEY in .env or environment.")
        return 2

    from redqueen.config import Settings
    from redqueen.gemma_client import GemmaClient, MissingApiKeyError, GemmaApiError

    print("=" * 60)
    print("RedQueen — Gemma Live Smoke Test")
    print("=" * 60)
    print()

    try:
        settings = Settings.from_env()
        client = GemmaClient(settings)
    except MissingApiKeyError as e:
        print(f"  FAIL: {e}")
        return 2

    # 1. Capability probe
    print("Step 1: Capability probe …")
    try:
        probe = client.probe_capabilities(force=True)
        print(_row("  auth_ok:", probe.auth_ok))
        print(_row("  model_available:", probe.model_available))
        print(_row("  structured_output_ok:", probe.structured_output_ok))
        print(_row("  function_calling_ok:", probe.function_calling_ok))
        print(_row("  latency_ms:", f"{probe.latency_ms:.0f}" if probe.latency_ms else "n/a"))
        if not probe.auth_ok:
            print("\n  FAIL: Authentication failed. Check GEMINI_API_KEY.")
            return 1
        if not probe.model_available:
            print(f"\n  FAIL: Model {settings.model!r} not available.")
            return 1
        print("  -> PASS\n")
    except GemmaApiError as e:
        print(f"  FAIL [{e.category}]: {e}")
        return 1

    # 2. Attack Lab call
    print("Step 2: Attack Lab -- live scenario generation ...")
    from redqueen.attack_lab import generate_attack_spec
    try:
        spec, telemetry = generate_attack_spec(
            "Fraudsters buy electronics at night with new devices and geo mismatches.",
            client=client,
            mode="live",
        )
        print(_row("  spec.name:", spec.name))
        print(_row("  merchant_categories:", spec.target_merchant_categories))
        print(_row("  fraud_fraction:", spec.fraud_fraction))
        print(_row("  model_used:", telemetry.model_used))
        print(_row("  latency_ms:", f"{telemetry.model_latency_ms:.0f}"))
        print("  -> PASS\n")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1

    # 3. Summary
    print("=" * 60)
    print("Smoke test PASSED")
    print(f"  Model used: {telemetry.model_used}")
    print(f"  Structured output: {probe.structured_output_ok}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
