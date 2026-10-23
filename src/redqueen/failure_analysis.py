"""Sample-only failure evidence; no validation or sealed rows may enter."""
from __future__ import annotations

import numpy as np
import pandas as pd

from redqueen.config import Settings
from redqueen.metrics import compute_metrics
from redqueen.schemas import ALLOWED_FIELDS, Evidence


def _nearest_legit_positions(
    frame: pd.DataFrame, missed: np.ndarray, legit: np.ndarray,
) -> np.ndarray:
    """Minimum distance to any displayed miss, with stable row-order ties.

    Numeric differences are divided by each field's sample range. Subtracting
    BEFORE scaling avoids cancellation for symmetric neighbours. Constant
    fields use scale 1. Each categorical mismatch adds 1 to squared distance
    (equivalent to one-hot encoding scaled by sqrt(2)). No held-out data fits
    these scales. Memory is linear in sample size, not n_legit*n_misses.
    """
    numeric = [name for name, spec in ALLOWED_FIELDS.items() if spec.dtype != "str"]
    categorical = [name for name, spec in ALLOWED_FIELDS.items() if spec.dtype == "str"]
    values = frame[numeric].to_numpy(dtype=float)
    categories = frame[categorical].to_numpy()
    spans = np.ptp(values, axis=0)
    spans[spans == 0] = 1.0
    distances = np.full(len(legit), np.inf)
    for position in missed:
        delta = (values[legit] - values[position]) / spans
        squared = np.einsum("ij,ij->i", delta, delta)
        squared += np.count_nonzero(categories[legit] != categories[position], axis=1)
        distances = np.minimum(distances, squared)
    return legit[np.argsort(distances, kind="stable")[:25]]


def _quantiles(frame: pd.DataFrame) -> dict:
    """JSON-safe numeric quantiles; empty cohorts produce empty maps."""
    if frame.empty:
        return {}
    return {
        name: {str(q): float(frame[name].quantile(q)) for q in (0.1, 0.5, 0.9)}
        for name, spec in ALLOWED_FIELDS.items() if spec.dtype != "str"
    }


def build_evidence(
    sample_df: pd.DataFrame,
    baseline_flags: "pd.Series[bool]",
    settings: Settings,
) -> Evidence:
    """Return <=25 target misses and <=25 nearest unique legitimate rows.

    Infer the single target attack from fraud labels other than 'background'.
    Multiple target names are rejected because this interface has no spec
    argument. Nearest neighbours minimise squared distance to any displayed
    miss; stable sorting resolves ties in original row order. With no target
    misses there are no neighbours. Inputs are never modified.
    """
    if "split" not in sample_df or not sample_df["split"].eq("sample").all():
        raise ValueError("Evidence requires sample-only rows")
    fields = list(ALLOWED_FIELDS)
    if not set(fields).issubset(sample_df.columns):
        raise ValueError("Evidence requires all permitted feature columns")
    baseline = compute_metrics(sample_df["is_fraud"], baseline_flags)
    fraud = sample_df["is_fraud"].eq(1).to_numpy()
    predicted = np.asarray(baseline_flags, dtype=bool)
    names = sample_df.loc[
        sample_df["is_fraud"].eq(1) & ~sample_df["attack_name"].eq("background"),
        "attack_name",
    ].unique()
    if len(names) > 1 or (len(names) == 1 and names[0] in ("none", "")):
        raise ValueError("Evidence expects one named target attack")
    target = fraud & sample_df["attack_name"].isin(names).to_numpy()
    missed_positions = np.flatnonzero(target & ~predicted)
    displayed_positions = missed_positions[:25]
    missed = sample_df.iloc[displayed_positions][fields]
    legit_positions = np.flatnonzero(~fraud)
    neighbours = np.array([], dtype=int)
    if len(displayed_positions) and len(legit_positions):
        neighbours = _nearest_legit_positions(sample_df, displayed_positions, legit_positions)
    lookalikes = sample_df.iloc[neighbours][fields]
    target_count = int(target.sum())
    summary = {
        "n_rows": len(sample_df), "n_legit": int((~fraud).sum()),
        "n_fraud": int(fraud.sum()), "n_target_fraud": target_count,
        "n_background_fraud": int((fraud & ~target).sum()),
        "n_missed_target": len(missed_positions),
        "n_displayed_missed": len(missed), "n_lookalike_legit": len(lookalikes),
        "baseline_recall": baseline.recall,
        "baseline_target_recall": float(predicted[target].sum() / target_count)
            if target_count else 0.0,
        "min_segment_legit_count": settings.min_segment_legit_count,
        "quantiles": {"missed_fraud": _quantiles(missed),
                      "lookalike_legit": _quantiles(lookalikes)},
    }
    return Evidence(
        missed_fraud=missed.to_dict(orient="records"),
        lookalike_legit=lookalikes.to_dict(orient="records"),
        permitted_fields=fields, summary_stats=summary,
    )
