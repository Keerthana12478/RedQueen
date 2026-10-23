"""Confusion counts, target recall and segment FPR, computed only from data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from redqueen.schemas import ALLOWED_FIELDS, MetricSet


def _binary_values(values: object, name: str, index: pd.Index | None = None) -> np.ndarray:
    if isinstance(values, pd.Series) and index is not None and not values.index.equals(index):
        raise ValueError(f"{name} index must match transaction order")
    array = np.asarray(values)
    if array.ndim != 1 or not np.isin(array, [0, 1]).all():
        raise ValueError(f"{name} must be a one-dimensional binary vector without missing values")
    if index is not None and len(array) != len(index):
        raise ValueError(f"{name} length must match transaction count")
    return array.astype(bool)


def compute_metrics(
    y_true: "pd.Series[int]",
    y_pred: "pd.Series[bool]",
) -> MetricSet:
    """Compute counts and rates; every empty denominator returns 0.0."""
    index = y_true.index if isinstance(y_true, pd.Series) else None
    truth = _binary_values(y_true, "y_true")
    predicted = _binary_values(y_pred, "y_pred", index)
    if len(truth) != len(predicted):
        raise ValueError("Labels and predictions must have equal lengths")
    tp = int(np.count_nonzero(truth & predicted))
    fp = int(np.count_nonzero(~truth & predicted))
    tn = int(np.count_nonzero(~truth & ~predicted))
    fn = int(np.count_nonzero(truth & ~predicted))
    return MetricSet(
        recall=tp / (tp + fn) if tp + fn else 0.0,
        precision=tp / (tp + fp) if tp + fp else 0.0,
        fpr=fp / (fp + tn) if fp + tn else 0.0,
        tp=tp, fp=fp, tn=tn, fn=fn,
    )


def recall_gain_pp(base: MetricSet, patched: MetricSet) -> float:
    """Absolute recall gain in percentage points; NOT relative improvement.

    Relative improvement divides by baseline recall and is not used for gating.
    """
    return (patched.recall - base.recall) * 100.0


def legit_flagged_per_10k(fp: int, n_legit: int) -> float:
    """Scale false positives to 10,000 legitimate rows (0 if there are none)."""
    if not 0 <= fp <= n_legit:
        raise ValueError("Require 0 <= fp <= n_legit")
    return fp / n_legit * 10_000.0 if n_legit else 0.0


def target_attack_recall(df: pd.DataFrame, flags: "pd.Series[bool]", attack_name: str) -> float:
    """Recall on fraud bearing attack_name, excluding unrelated background.

    Zero target rows returns 0.0, never evidence of success: Phase 4 must reject
    a final candidate whose sealed target-positive denominator is zero.
    """
    predicted = _binary_values(flags, "flags", df.index)
    truth = _binary_values(df["is_fraud"], "is_fraud", df.index)
    target = truth & df["attack_name"].eq(attack_name).to_numpy()
    count = int(target.sum())
    return float(predicted[target].sum() / count) if count else 0.0


def segment_fpr(
    df: pd.DataFrame,
    flags: "pd.Series[bool]",
    segments: list[str],
) -> dict:
    """Return {segment: {value: {fpr, fp, n_legit}}}, including empty groups.

    Supported segments: merchant_category, channel, account_age_bucket.
    Age boundaries are <30, 30 through 365 inclusive, and >365. Frauds never
    contribute to FPR. Callers apply Settings.min_segment_legit_count.
    """
    predicted = _binary_values(flags, "flags", df.index)
    legit = ~_binary_values(df["is_fraud"], "is_fraud", df.index)
    result = {}
    for segment in segments:
        if segment == "account_age_bucket":
            age = df["account_age_days"].to_numpy()
            values = np.where(age < 30, "<30", np.where(age <= 365, "30-365", ">365"))
            categories = ["<30", "30-365", ">365"]
        elif segment in ("merchant_category", "channel"):
            values = df[segment].to_numpy()
            categories = sorted(ALLOWED_FIELDS[segment].categories or ())
        else:
            raise ValueError(f"Unsupported FPR segment: {segment}")
        groups = {}
        for category in categories:
            mask = legit & (values == category)
            count = int(mask.sum())
            fp = int(predicted[mask].sum())
            groups[category] = {"fpr": fp / count if count else 0.0,
                                "fp": fp, "n_legit": count}
        result[segment] = groups
    return result