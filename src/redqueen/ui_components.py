"""Pure display helpers. Model text belongs in text/code, never HTML."""
from __future__ import annotations
import json
import pandas as pd
from redqueen.schemas import DefenseRule, VerificationReport

REPLAY_BANNER = "Offline replay — predefined scenario and rule proposal; verification below is computed live in Python. No Gemma call was made."


def mode_label(mode: str) -> str:
    return "LIVE GEMMA" if mode == "live" else "OFFLINE REPLAY"


def render_rule(rule: DefenseRule) -> str:
    operators = {">=":"≥", "<=":"≤", "!=":"≠", "==":"="}
    return "FLAG if " + " AND ".join(f"{c.field} {operators.get(c.op,c.op)} {json.dumps(c.val)}" for c in rule.clauses)


def verdict_banner(report: VerificationReport) -> str:
    return "ACCEPTED — ACTIVE IN SANDBOX" if report.verdict=="ACCEPTED" else "REJECTED — " + report.reason


def check_table(report: VerificationReport) -> pd.DataFrame:
    return pd.DataFrame([{"Check":c.name, "Status":"PASS" if c.passed else "FAIL",
        "Observed":c.observed, "Threshold":c.threshold, "Detail":c.detail} for c in report.checks])


def metric_table(report: VerificationReport) -> pd.DataFrame:
    rows = []
    for label, metrics in [("Original baseline",report.original_baseline),
        ("Before candidate (baseline + active rules)",report.baseline),
        ("Candidate + original baseline",report.candidate_only),
        ("After candidate (cumulative)",report.patched)]:
        if metrics is not None:
            rows.append({"Detector":label,"Overall fraud recall":metrics.recall,
                "Precision":metrics.precision,"Global FPR":metrics.fpr,"Legitimate flags / 10k":metrics.fpr*10000})
    return pd.DataFrame(rows)
