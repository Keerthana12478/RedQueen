"""Fixed, deliberately imperfect baseline; all thresholds are design choices."""
from __future__ import annotations

import pandas as pd

from redqueen.rule_engine import apply_rule, combine
from redqueen.schemas import DefenseRule


class BaselineDetector:
    """OR four transparent DefenseRules, evaluated through the shared engine.

    Large amounts >=5000; hourly velocity >=12; geo + new device + amount>=800;
    or account age<3 + amount>=1000. No threshold adapts to evaluation data.
    """

    def __init__(self) -> None:
        self.rules: list[DefenseRule] = [
            DefenseRule(clauses=[{"field": "amount", "op": ">=", "val": 5000}],
                        action="FLAG", rationale="Large transaction."),
            DefenseRule(clauses=[{"field": "velocity_1h", "op": ">=", "val": 12}],
                        action="FLAG", rationale="Extreme hourly burst."),
            DefenseRule(clauses=[
                {"field": "geo_mismatch", "op": "==", "val": 1},
                {"field": "is_new_device", "op": "==", "val": 1},
                {"field": "amount", "op": ">=", "val": 800},
            ], action="FLAG", rationale="New device and geography with a large amount."),
            DefenseRule(clauses=[
                {"field": "account_age_days", "op": "<", "val": 3},
                {"field": "amount", "op": ">=", "val": 1000},
            ], action="FLAG", rationale="Large amount on a very young account."),
        ]

    def predict(self, df: pd.DataFrame) -> "pd.Series[bool]":
        """Return boolean flags aligned with df, without modifying transactions."""
        flags = pd.Series(False, index=df.index, dtype=bool)
        for rule in self.rules:
            flags = combine(flags, apply_rule(rule, df))
        return flags