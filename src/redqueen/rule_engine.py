"""Vectorised, revalidated declarative clauses and monotonic OR patches."""
from __future__ import annotations

import operator

import numpy as np
import pandas as pd
from pydantic import ValidationError

from redqueen.schemas import DefenseRule


class RuleExecutionError(ValueError):
    """A malformed rule, incompatible data, or misaligned flag vector."""


def apply_rule(rule: DefenseRule, df: pd.DataFrame) -> "pd.Series[bool]":
    """Revalidate even constructed/mutated models; AND clauses on df's index."""
    try:
        payload = rule.model_dump() if isinstance(rule, DefenseRule) else rule
        checked = DefenseRule.model_validate(payload)
        comparisons = {
            ">": operator.gt, ">=": operator.ge, "<": operator.lt,
            "<=": operator.le, "==": operator.eq, "!=": operator.ne,
        }
        result = pd.Series(True, index=df.index, dtype=bool)
        for clause in checked.clauses:
            if isinstance(clause.val, (int, float)) and not np.isfinite(clause.val):
                raise RuleExecutionError("Rule thresholds must be finite")
            values = df[clause.field]
            if not isinstance(values, pd.Series) or values.isna().any():
                raise RuleExecutionError(f"Missing or duplicate values for {clause.field}")
            result &= comparisons[clause.op](values, clause.val).astype(bool)
        return result
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, RuleExecutionError):
            raise
        raise RuleExecutionError(f"Cannot execute defense rule: {exc}") from exc


def combine(
    baseline_flags: "pd.Series[bool]",
    rule_flags: "pd.Series[bool]",
) -> "pd.Series[bool]":
    """Elementwise OR; reject index mismatches rather than silently align rows."""
    for flags in (baseline_flags, rule_flags):
        if not isinstance(flags, pd.Series) or not pd.api.types.is_bool_dtype(flags):
            raise RuleExecutionError("Flags must be boolean Series")
        if flags.isna().any():
            raise RuleExecutionError("Flags must not contain missing values")
    if not baseline_flags.index.equals(rule_flags.index):
        raise RuleExecutionError("Flag indices must match in the same order")
    return (baseline_flags | rule_flags).astype(bool)