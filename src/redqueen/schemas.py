"""RedQueen — shared Pydantic v2 schemas (cross-phase contract, frozen for all phases).

All schemas use ``extra="forbid"`` to reject unknown keys.
Categorical and binary fields only allow ``==`` / ``!=`` operators.
Clauses are ANDed; no other logic constructs are supported.

The ``ALLOWED_FIELDS`` dict is the single source of truth for transaction
column names, types, and bounds.  Later phases must not rename any field here;
additions require a documented, backward-compatible change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Field specification registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    """Metadata for one transaction feature column."""

    dtype: Literal["float", "int", "str"]
    min: float | int | None = None      # None for categorical strings
    max: float | int | None = None
    categories: frozenset[str] | None = None   # only for dtype == "str"


ALLOWED_FIELDS: dict[str, FieldSpec] = {
    "amount":               FieldSpec("float", 0, 50_000),
    "hour_of_day":          FieldSpec("int",   0, 23),
    "velocity_1h":          FieldSpec("int",   0, 50),
    "velocity_24h":         FieldSpec("int",   0, 200),
    "account_age_days":     FieldSpec("int",   0, 5_000),
    "ip_age_days":          FieldSpec("int",   0, 3_650),
    "is_new_device":        FieldSpec("int",   0, 1),
    "geo_mismatch":         FieldSpec("int",   0, 1),
    "amount_ratio_to_avg":  FieldSpec("float", 0, 100),
    "merchant_category":    FieldSpec(
        "str", categories=frozenset(
            {"grocery", "electronics", "gift_card", "travel",
             "utilities", "dining", "crypto", "peer_transfer"}
        )
    ),
    "channel":              FieldSpec(
        "str", categories=frozenset({"web", "mobile", "pos", "atm"})
    ),
}

# Binary (0/1) integer fields — only == / != allowed (same restriction as categorical)
_BINARY_FIELDS: frozenset[str] = frozenset({"is_new_device", "geo_mismatch"})

ALLOWED_OPS: frozenset[str] = frozenset({">", ">=", "<", "<=", "==", "!="})
_CATEGORICAL_OPS: frozenset[str] = frozenset({"==", "!="})


def _is_categorical(field_name: str) -> bool:
    spec = ALLOWED_FIELDS.get(field_name)
    return spec is not None and (spec.dtype == "str" or field_name in _BINARY_FIELDS)


# ---------------------------------------------------------------------------
# Clause
# ---------------------------------------------------------------------------

class Clause(BaseModel):
    """A single comparison predicate: ``field op val``."""

    model_config = {"frozen": True, "extra": "forbid"}

    field: str
    op: str
    val: Any

    @model_validator(mode="after")
    def _validate_clause(self) -> "Clause":
        field_name = self.field
        op = self.op
        val = self.val

        # 1. Field must exist
        if field_name not in ALLOWED_FIELDS:
            raise ValueError(f"Unknown field: {field_name!r}")

        spec = ALLOWED_FIELDS[field_name]

        # 2. Op must be in allowed set
        if op not in ALLOWED_OPS:
            raise ValueError(f"Illegal operator {op!r}; allowed: {ALLOWED_OPS}")

        # 3. Categorical / binary fields: only == / !=
        if _is_categorical(field_name) and op not in _CATEGORICAL_OPS:
            raise ValueError(
                f"Field {field_name!r} is categorical/binary; "
                f"only == / != are allowed, got {op!r}"
            )

        # 4. Value type and bounds
        if spec.dtype == "str":
            if not isinstance(val, str):
                raise ValueError(
                    f"Field {field_name!r} expects str value, got {type(val).__name__}"
                )
            if spec.categories is not None and val not in spec.categories:
                raise ValueError(
                    f"Value {val!r} not in allowed categories for {field_name!r}: "
                    f"{spec.categories}"
                )
        elif spec.dtype == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(
                    f"Field {field_name!r} expects int value, got {type(val).__name__}"
                )
            if spec.min is not None and val < spec.min:
                raise ValueError(
                    f"Value {val} below minimum {spec.min} for field {field_name!r}"
                )
            if spec.max is not None and val > spec.max:
                raise ValueError(
                    f"Value {val} above maximum {spec.max} for field {field_name!r}"
                )
        elif spec.dtype == "float":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ValueError(
                    f"Field {field_name!r} expects numeric value, got {type(val).__name__}"
                )
            val_f = float(val)
            if not math.isfinite(val_f):
                raise ValueError("Numeric rule values must be finite")
            if spec.min is not None and val_f < spec.min:
                raise ValueError(
                    f"Value {val} below minimum {spec.min} for field {field_name!r}"
                )
            if spec.max is not None and val_f > spec.max:
                raise ValueError(
                    f"Value {val} above maximum {spec.max} for field {field_name!r}"
                )

        return self


# ---------------------------------------------------------------------------
# DefenseRule
# ---------------------------------------------------------------------------

class DefenseRule(BaseModel):
    """A declarative defense rule composed of 1–3 ANDed clauses.

    Shorthand single-clause form (flat dict with ``field``, ``op``, ``val``,
    ``action``) is normalised by the ``model_validator`` before field
    validation runs.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    clauses: list[Clause]
    action: Literal["FLAG"]
    rationale: str

    @model_validator(mode="before")
    @classmethod
    def _normalise_shorthand(cls, data: Any) -> Any:
        """Accept flat shorthand and promote it into the ``clauses`` list form."""
        if isinstance(data, dict):
            # Detect shorthand: has 'field', 'op', 'val' at top level but no 'clauses'
            if "clauses" not in data and "field" in data and "op" in data and "val" in data:
                if set(data) - {"field", "op", "val", "action", "rationale"}:
                    raise ValueError("Unknown shorthand rule keys")
                clause_data = {
                    "field": data["field"],
                    "op": data["op"],
                    "val": data["val"],
                }
                return {
                    "clauses": [clause_data],
                    "action": data.get("action", "FLAG"),
                    "rationale": data.get("rationale", ""),
                }
        return data

    @field_validator("clauses")
    @classmethod
    def _validate_clauses_count(cls, v: list[Clause]) -> list[Clause]:
        if not (1 <= len(v) <= 3):
            raise ValueError(f"DefenseRule requires 1–3 clauses, got {len(v)}")
        return v

    @field_validator("rationale")
    @classmethod
    def _validate_rationale_length(cls, v: str) -> str:
        if len(v) > 500:
            raise ValueError(f"rationale must be ≤500 characters, got {len(v)}")
        return v


# ---------------------------------------------------------------------------
# AttackSpec
# ---------------------------------------------------------------------------

class AttackSpec(BaseModel):
    """Specification for a synthetic fraud attack scenario."""

    model_config = {"frozen": True, "extra": "forbid"}

    name: str
    description: str
    target_merchant_categories: list[str]
    amount_range: tuple[float, float]
    hour_window: list[int]
    velocity_1h_range: tuple[int, int]
    account_age_range: tuple[int, int]
    ip_age_range: tuple[int, int]
    new_device_prob: float
    geo_mismatch_prob: float
    fraud_fraction: float
    evasion_overlap: float

    @model_validator(mode="after")
    def _usable_spec(self) -> "AttackSpec":
        if not self.name.strip() or self.name in {"none", "background"}:
            raise ValueError("Attack requires a non-reserved name")
        if not self.hour_window or not self.target_merchant_categories:
            raise ValueError("Attack hours and categories must be non-empty")
        if not all(math.isfinite(v) for v in self.amount_range):
            raise ValueError("Attack amounts must be finite")
        return self

    @field_validator("target_merchant_categories")
    @classmethod
    def _valid_categories(cls, v: list[str]) -> list[str]:
        allowed = ALLOWED_FIELDS["merchant_category"].categories
        for cat in v:
            if cat not in allowed:
                raise ValueError(f"Unknown merchant category: {cat!r}")
        return v

    @field_validator("amount_range")
    @classmethod
    def _amount_range_order(cls, v: tuple[float, float]) -> tuple[float, float]:
        spec = ALLOWED_FIELDS["amount"]
        lo, hi = v
        if lo > hi:
            raise ValueError(f"amount_range low {lo} > high {hi}")
        if lo < spec.min or hi > spec.max:  # type: ignore[operator]
            raise ValueError(
                f"amount_range {v} out of allowed bounds [{spec.min}, {spec.max}]"
            )
        return v

    @field_validator("hour_window")
    @classmethod
    def _hour_window_valid(cls, v: list[int]) -> list[int]:
        for h in v:
            if not (0 <= h <= 23):
                raise ValueError(f"hour_window entry {h} out of 0–23")
        return v

    @field_validator("velocity_1h_range")
    @classmethod
    def _velocity_1h_range_order(cls, v: tuple[int, int]) -> tuple[int, int]:
        spec = ALLOWED_FIELDS["velocity_1h"]
        lo, hi = v
        if lo > hi:
            raise ValueError(f"velocity_1h_range low {lo} > high {hi}")
        if lo < spec.min or hi > spec.max:  # type: ignore[operator]
            raise ValueError(f"velocity_1h_range {v} out of bounds")
        return v

    @field_validator("account_age_range")
    @classmethod
    def _account_age_range_order(cls, v: tuple[int, int]) -> tuple[int, int]:
        spec = ALLOWED_FIELDS["account_age_days"]
        lo, hi = v
        if lo > hi:
            raise ValueError(f"account_age_range low {lo} > high {hi}")
        if lo < spec.min or hi > spec.max:  # type: ignore[operator]
            raise ValueError(f"account_age_range {v} out of bounds")
        return v

    @field_validator("ip_age_range")
    @classmethod
    def _ip_age_range_order(cls, v: tuple[int, int]) -> tuple[int, int]:
        spec = ALLOWED_FIELDS["ip_age_days"]
        lo, hi = v
        if lo > hi:
            raise ValueError(f"ip_age_range low {lo} > high {hi}")
        if lo < spec.min or hi > spec.max:  # type: ignore[operator]
            raise ValueError(f"ip_age_range {v} out of bounds")
        return v

    @field_validator("new_device_prob", "geo_mismatch_prob", "evasion_overlap")
    @classmethod
    def _prob_0_1(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Probability must be in [0, 1], got {v}")
        return v

    @field_validator("fraud_fraction")
    @classmethod
    def _fraud_fraction_valid(cls, v: float) -> float:
        if not (0.01 <= v <= 0.30):
            raise ValueError(f"fraud_fraction must be in [0.01, 0.30], got {v}")
        return v


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

class Transaction(BaseModel):
    """Column contract for a single transaction row.

    All ``ALLOWED_FIELDS`` columns are present, plus metadata columns.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # ---- metadata
    txn_id: str
    is_fraud: Literal[0, 1]
    attack_name: str   # "none" for legitimate transactions
    split: Literal["sample", "validation", "sealed"]

    # ---- feature columns (mirrors ALLOWED_FIELDS)
    amount: float
    hour_of_day: int
    velocity_1h: int
    velocity_24h: int
    account_age_days: int
    ip_age_days: int
    is_new_device: Literal[0, 1]
    geo_mismatch: Literal[0, 1]
    amount_ratio_to_avg: float
    merchant_category: str
    channel: str


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class Evidence(BaseModel):
    """Failure-analysis artefact derived from the sample split only."""

    model_config = {"extra": "forbid"}

    missed_fraud: list[dict]
    lookalike_legit: list[dict]
    permitted_fields: list[str]
    summary_stats: dict


# ---------------------------------------------------------------------------
# ValidationFeedback
# ---------------------------------------------------------------------------

class ValidationFeedback(BaseModel):
    """Coarse validation signal sent back to the defender (no exact metrics)."""

    model_config = {"extra": "forbid"}

    recall_gain_bucket: Literal["none", "small", "medium", "large"]
    fpr_exceeded: bool
    segment_violation: bool


# ---------------------------------------------------------------------------
# Verification / report types
# ---------------------------------------------------------------------------

class MetricSet(BaseModel):
    """Confusion-matrix derived metrics for a single evaluation pass."""

    model_config = {"extra": "forbid"}

    recall: float
    precision: float
    fpr: float
    tp: int
    fp: int
    tn: int
    fn: int


class CheckResult(BaseModel):
    """Result of a single gate check."""

    model_config = {"extra": "forbid"}

    name: str
    passed: bool
    observed: float
    threshold: float
    detail: str


class VerificationReport(BaseModel):
    """Full verification outcome returned by :class:`VerificationGate`."""

    model_config = {"extra": "forbid"}

    verdict: Literal["ACCEPTED", "REJECTED"]
    reason: str
    checks: list[CheckResult]
    baseline: MetricSet
    patched: MetricSet
    recall_gain_pp: float
    legit_flagged_per_10k: float
    sealed_evaluated: bool
    latency_ms: float
    target_baseline_recall: float = 0.0
    target_patched_recall: float = 0.0
    target_fraud_count: int = 0
    original_baseline: MetricSet | None = None
    candidate_only: MetricSet | None = None
    segment_results: list[dict] = Field(default_factory=list)
    run_id: str = ""
    rule_fingerprint: str = ""
    active_rule_fingerprints: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Run telemetry
# ---------------------------------------------------------------------------

class RunTelemetry(BaseModel):
    """Timing and bookkeeping for one model-assisted pipeline step."""

    model_config = {"extra": "forbid"}

    mode: Literal["live", "replay"]
    model_used: str | None
    model_latency_ms: float | None
    verification_latency_ms: float
    attempts: int
    replay_scenario: str | None = None
    replay_match: Literal["exact", "closest"] | None = None
