"""Deterministic gate. No model imports or calls.

Target recall = TP / (TP + FN) on fraud with attack_name == spec.name.
Gain = (patched target recall - current detector target recall) * 100 pp.
Global FPR = FP / (FP + TN) on legitimate rows; legit/10k = FPR * 10000.
Only evaluate_final consumes sealed frames. Reports contain aggregates only.
"""
from __future__ import annotations

import hashlib
import json
import time
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from redqueen.baseline import BaselineDetector
from redqueen.config import Settings
from redqueen.metrics import compute_metrics, segment_fpr, target_attack_recall
from redqueen.rule_engine import apply_rule, combine
from redqueen.schemas import AttackSpec, CheckResult, DefenseRule, MetricSet, ValidationFeedback, VerificationReport
from redqueen.simulator import DEFAULT_DEMO_SPEC, generate_datasets


class ValidationBudgetExceeded(RuntimeError):
    """Initial validation plus at most one revision have been exhausted."""


class SealedAlreadyEvaluated(RuntimeError):
    """This run is finalized; start an independent run to evaluate again."""


class SandboxActivationError(ValueError):
    """Only a matching, accepted cumulative evaluation may activate a rule."""


def _checked(rule: DefenseRule) -> DefenseRule:
    return DefenseRule.model_validate(rule.model_dump() if isinstance(rule, DefenseRule) else rule)


def rule_fingerprint(rule: DefenseRule) -> str:
    return hashlib.sha256(json.dumps(_checked(rule).model_dump(), sort_keys=True).encode()).hexdigest()


REFERENCE_ATTACKS = (
    DEFAULT_DEMO_SPEC,
    DEFAULT_DEMO_SPEC.model_copy(update={
        "name": "ReferenceCrypto", "target_merchant_categories": ["crypto"],
        "amount_range": (50.0, 300.0), "hour_window": [9, 10, 14],
        "velocity_1h_range": (3, 10), "account_age_range": (0, 7),
    }),
)
SEGMENTS = ["merchant_category", "channel", "account_age_bucket"]


def _predict(df, baseline, rules):
    flags = baseline.predict(df)
    for rule in rules:
        flags = combine(flags, apply_rule(rule, df))
    return flags


def _segment_rows(df, flags, settings):
    rows = []
    for dimension, groups in segment_fpr(df, flags, SEGMENTS).items():
        for value, metrics in groups.items():
            sufficient = metrics["n_legit"] >= settings.min_segment_legit_count and metrics["n_legit"] > 0
            rows.append({"segment": dimension, "value": value, **metrics,
                "budget": settings.segment_fpr_budget,
                "status": ("PASS" if metrics["fpr"] <= settings.segment_fpr_budget else "FAIL")
                          if sufficient else "insufficient data"})
    return rows


class SandboxState:
    """Session memory only. Snapshots prevent caller mutation of accepted rules."""

    def __init__(self):
        self.__rules = []
        self.__attacks = []
        self.__runs = set()
        self.audit = []

    @property
    def active_rules(self):
        return [rule.model_copy(deep=True) for rule in self.__rules]

    @property
    def approved_attacks(self):
        return [spec.model_copy(deep=True) for spec in self.__attacks]

    def activate(self, rule: DefenseRule, report: VerificationReport, *, spec: AttackSpec | None = None):
        fingerprints = [rule_fingerprint(r) for r in self.__rules]
        if (report.verdict != "ACCEPTED" or not report.sealed_evaluated
                or not report.checks or not all(c.passed for c in report.checks)
                or report.rule_fingerprint != rule_fingerprint(rule)
                or report.active_rule_fingerprints != fingerprints
                or not report.run_id or report.run_id in self.__runs):
            raise SandboxActivationError("A matching ACCEPTED cumulative report is required")
        self.__rules.append(_checked(rule).model_copy(deep=True))
        if spec is not None and spec.name not in {s.name for s in self.__attacks}:
            self.__attacks.append(AttackSpec.model_validate(spec.model_dump()))
        self.__runs.add(report.run_id)
        self.audit.append(report.model_dump(mode="json"))

    def predict(self, df, baseline=None):
        return _predict(df, baseline or BaselineDetector(), self.__rules)


class VerificationGate:
    def __init__(self, settings: Settings | None = None, spec: AttackSpec | None = None,
                 *, active_rules=(), run_id: str | None = None):
        self.settings = settings or Settings()
        self.spec = spec
        self.run_id = run_id or uuid4().hex
        self._active = [_checked(r).model_copy(deep=True) for r in active_rules]
        self.validation_calls = 0
        self._finalized = False

    def _target(self, df):
        if self.spec is not None:
            return self.spec.name
        names = df.loc[df["is_fraud"].eq(1) & ~df["attack_name"].isin(["none", "background"]), "attack_name"].unique()
        if len(names) > 1:
            raise ValueError("Gate requires one target AttackSpec")
        return str(names[0]) if len(names) else ""

    def evaluate_validation(self, rule, datasets, baseline) -> ValidationFeedback:
        if self._finalized:
            raise SealedAlreadyEvaluated("Finalized runs cannot request feedback")
        if self.validation_calls >= 1 + min(1, max(0, self.settings.max_validation_retries)):
            raise ValidationBudgetExceeded("Only initial validation and one revision are permitted")
        self.validation_calls += 1
        checked = _checked(rule)
        df = datasets["validation"]
        current = _predict(df, baseline, self._active)
        patched = combine(current, apply_rule(checked, df))
        target = self._target(df)
        gain = (target_attack_recall(df, patched, target) - target_attack_recall(df, current, target)) * 100
        bucket = "none" if gain < 1 else "small" if gain < 5 else "medium" if gain < 15 else "large"
        metrics = compute_metrics(df["is_fraud"], patched)
        return ValidationFeedback(recall_gain_bucket=bucket,
            fpr_exceeded=metrics.fpr > self.settings.global_fpr_ceiling,
            segment_violation=any(r["status"] == "FAIL" for r in _segment_rows(df, patched, self.settings)))

    def evaluate_final(self, rule, datasets, baseline, approved_attacks=None) -> VerificationReport:
        if self._finalized:
            raise SealedAlreadyEvaluated("Sealed evaluation already consumed for this run")
        self._finalized = True  # consume the run even if evaluation later fails
        started = time.perf_counter()
        checks = []
        def check(name, passed, observed, threshold, detail):
            checks.append(CheckResult(name=name, passed=bool(passed), observed=float(observed),
                                      threshold=float(threshold), detail=detail))
        empty = MetricSet(recall=0.0, precision=0.0, fpr=0.0, tp=0, fp=0, tn=0, fn=0)
        try:
            checked = _checked(rule)
        except (ValidationError, TypeError, ValueError, AttributeError):
            check("rule_valid", False, 0, 1, "Rule violates the restricted DefenseRule schema")
            return VerificationReport(verdict="REJECTED", reason="rule_valid: invalid declarative rule",
                checks=checks, baseline=empty, patched=empty, recall_gain_pp=0.0,
                legit_flagged_per_10k=0.0, sealed_evaluated=False,
                latency_ms=(time.perf_counter()-started)*1000, run_id=self.run_id)
        check("rule_valid", True, 1, 1, "Fields, operators, bounds and FLAG action revalidated")
        check("rule_complexity", len(checked.clauses) <= self.settings.max_clauses,
              len(checked.clauses), self.settings.max_clauses, "AND clauses; FLAG only")
        df = datasets["sealed"]  # sole final-evaluation capability boundary
        original = baseline.predict(df)
        current = _predict(df, baseline, self._active)
        candidate = combine(original, apply_rule(checked, df))
        patched = combine(current, apply_rule(checked, df))
        base_metrics = compute_metrics(df["is_fraud"], current)
        patched_metrics = compute_metrics(df["is_fraud"], patched)
        target = self._target(df)
        target_count = int((df["is_fraud"].eq(1) & df["attack_name"].eq(target)).sum())
        before = target_attack_recall(df, current, target)
        after = target_attack_recall(df, patched, target)
        gain = (after - before) * 100
        check("monotonic", bool((~current | patched).all()), int((current & ~patched).sum()), 0,
              "Every existing baseline and active-sandbox flag must remain flagged")
        check("target_recall_gain", target_count > 0 and gain >= self.settings.min_recall_gain_pp,
              gain, self.settings.min_recall_gain_pp,
              f"Marginal target recall gain in pp on {target_count} target fraud rows" if target_count
              else "Insufficient evidence: zero target fraud rows")
        legit_count = patched_metrics.fp + patched_metrics.tn
        check("global_fpr", legit_count > 0 and patched_metrics.fpr <= self.settings.global_fpr_ceiling,
              patched_metrics.fpr, self.settings.global_fpr_ceiling,
              "Current detector already exceeds ceiling; OR-only patches cannot repair it"
              if base_metrics.fpr > self.settings.global_fpr_ceiling else
              "Cumulative sandbox FPR on legitimate transactions" if legit_count else "Insufficient legitimate rows")
        segments = _segment_rows(df, patched, self.settings)
        tested = [r for r in segments if r["status"] != "insufficient data"]
        worst = max(tested, key=lambda r: r["fpr"], default=None)
        skipped = [f'{r["segment"]}={r["value"]}' for r in segments if r["status"] == "insufficient data"]
        detail = (f'Worst: {worst["segment"]}={worst["value"]}; ' if worst else "No eligible segments; ")
        if skipped:
            detail += "insufficient data: " + ", ".join(skipped)
        check("segment_fpr", bool(tested) and all(r["status"] == "PASS" for r in tested),
              worst["fpr"] if worst else 0, self.settings.segment_fpr_budget, detail)
        regression_failures = []
        references = list(REFERENCE_ATTACKS)
        for spec in approved_attacks or []:
            if not isinstance(spec, AttackSpec):
                raise ValueError("approved_attacks must contain AttackSpec objects")
            references.append(spec)
        unique = {spec.name: spec for spec in references}
        for i, reference in enumerate(unique.values()):
            # These independent reference sets are consumed only inside this method.
            reference_df = generate_datasets(reference, self.settings.seed + 10000 + i*100, self.settings)["sealed"]
            old = _predict(reference_df, baseline, self._active)
            new = combine(old, apply_rule(checked, reference_df))
            old_recall = target_attack_recall(reference_df, old, reference.name)
            new_recall = target_attack_recall(reference_df, new, reference.name)
            metric = compute_metrics(reference_df["is_fraud"], new)
            ref_segments = _segment_rows(reference_df, new, self.settings)
            target_rows = int((reference_df["is_fraud"].eq(1) & reference_df["attack_name"].eq(reference.name)).sum())
            if (not target_rows or metric.fp + metric.tn == 0 or new_recall < old_recall
                    or metric.fpr > self.settings.global_fpr_ceiling
                    or any(r["status"] == "FAIL" for r in ref_segments)):
                regression_failures.append(reference.name)
        check("regression", not regression_failures, len(regression_failures), 0,
              "Failed recall/FPR/segment protection: " + ", ".join(regression_failures)
              if regression_failures else f"Recall and cumulative FPR budgets retained on {len(unique)} reference attacks")
        priority = ["rule_valid", "rule_complexity", "monotonic", "global_fpr", "segment_fpr", "regression", "target_recall_gain"]
        first = next((c for name in priority for c in checks if c.name == name and not c.passed), None)
        return VerificationReport(verdict="REJECTED" if first else "ACCEPTED",
            reason=f"{first.name}: {first.detail}" if first else "All deterministic checks passed",
            checks=checks, baseline=base_metrics, patched=patched_metrics, recall_gain_pp=gain,
            legit_flagged_per_10k=patched_metrics.fpr * 10000, sealed_evaluated=True,
            latency_ms=(time.perf_counter()-started)*1000,
            target_baseline_recall=before, target_patched_recall=after, target_fraud_count=target_count,
            original_baseline=compute_metrics(df["is_fraud"], original),
            candidate_only=compute_metrics(df["is_fraud"], candidate), segment_results=segments,
            run_id=self.run_id, rule_fingerprint=rule_fingerprint(checked),
            active_rule_fingerprints=[rule_fingerprint(r) for r in self._active])
