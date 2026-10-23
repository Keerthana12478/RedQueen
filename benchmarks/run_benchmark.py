"""Headless computed replay benchmark; Phase 5 shares the UI orchestrator."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redqueen.pipeline import run_redqueen
from redqueen.gemma_client import GemmaApiError, MissingApiKeyError
from redqueen.config import Settings
from redqueen.replay import list_replay_scenarios, load_replay_validated


def main(argv=None):
    parser = argparse.ArgumentParser(description="Patch a detector without breaking legitimate users.")
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--scenarios", default="all")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    settings = Settings.from_env().model_copy(update={"seed": args.seed, "mode": args.mode})
    names = list_replay_scenarios() if args.scenarios=="all" else [args.scenarios]
    results = []
    print(("OFFLINE REPLAY" if args.mode=="replay" else "LIVE GEMMA") + " | scenario | target baseline | patched | gain pp | FPR | legit/10k | verdict | reason")
    for name in names:
        fixture = load_replay_validated(name)
        try:
            result = run_redqueen(name if args.mode=="replay" else fixture["scenario_text"], settings, args.mode)
        except (MissingApiKeyError, GemmaApiError) as error:
            print(f"Live mode unavailable: {getattr(error, 'category', 'missing_key')}. Use --mode replay.", file=sys.stderr)
            return 2
        report = result.report
        print(f'{name} | {report.target_baseline_recall:.2%} | {report.target_patched_recall:.2%} | {report.recall_gain_pp:+.2f} | {report.patched.fpr:.2%} | {report.legit_flagged_per_10k:.1f} | {report.verdict} | {report.reason}')
        results.append({"scenario":name,"mode":args.mode,"seed":args.seed,"report":report.model_dump(mode="json"),"telemetry":result.telemetry.model_dump(mode="json")})
    if args.json:
        args.json.write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
