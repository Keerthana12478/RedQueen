"""Phase 2 simulator contracts, overlap and reproducibility (including subprocesses)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

from redqueen.config import Settings
from redqueen.schemas import ALLOWED_FIELDS, AttackSpec, Transaction
from redqueen.simulator import (
    DEFAULT_DEMO_SPEC, generate_datasets, generate_fraud, generate_legit_background,
)


@pytest.fixture
def datasets():
    return generate_datasets(
        DEFAULT_DEMO_SPEC, 1337, Settings(n_sample=800, n_validation=1000, n_sealed=1500))


def test_split_sizes_ids_types_and_transaction_contract(datasets):
    ids = set()
    first = datasets["sample"]
    for (split, frame), n, prefix in zip(
        datasets.items(), (800, 1000, 1500), ("S", "V", "T"), strict=True
    ):
        assert len(frame) == n
        assert list(frame) == list(first)
        assert frame.dtypes.equals(first.dtypes)
        assert frame.index.equals(pd.RangeIndex(n))
        assert frame["split"].eq(split).all()
        assert frame["txn_id"].str.startswith(prefix).all()
        assert frame["txn_id"].is_unique
        assert not ids.intersection(frame["txn_id"])
        ids.update(frame["txn_id"])
        assert frame["is_fraud"].sum() == round(n * DEFAULT_DEMO_SPEC.fraud_fraction)
        assert abs(frame["is_fraud"].mean() - DEFAULT_DEMO_SPEC.fraud_fraction) <= 0.01
        assert not frame.isna().any().any()
        for name, spec in ALLOWED_FIELDS.items():
            dtype = {"float": "float64", "int": "int64", "str": "object"}[spec.dtype]
            assert str(frame[name].dtype) == dtype
            if spec.dtype == "str":
                assert set(frame[name]).issubset(spec.categories)
            else:
                assert frame[name].between(spec.min, spec.max).all()
        for row in frame.to_dict("records"):
            Transaction.model_validate(row)
        assert frame.loc[frame.is_fraud.eq(0), "attack_name"].eq("none").all()
        assert (frame.velocity_24h >= frame.velocity_1h).all()


def test_exact_default_frame_determinism_and_seed_variation():
    a = generate_datasets(DEFAULT_DEMO_SPEC, 1337, Settings())
    b = generate_datasets(DEFAULT_DEMO_SPEC, 1337, Settings())
    c = generate_datasets(DEFAULT_DEMO_SPEC, 1338, Settings())
    for split in a:
        assert_frame_equal(a[split], b[split], check_exact=True)
        assert not a[split].equals(c[split])
    # Same root seed is used for this shifted sample and the original validation.
    # The source streams also depend on counts: they are not reused slices.
    assert not a["validation"][list(ALLOWED_FIELDS)].head(100).equals(
        c["sample"][list(ALLOWED_FIELDS)].head(100))


def test_split_generation_is_independent_of_other_split_sizes():
    small = Settings(n_sample=100, n_validation=200, n_sealed=300)
    changed = Settings(n_sample=500, n_validation=200, n_sealed=300)
    a = generate_datasets(DEFAULT_DEMO_SPEC, 52, small)
    b = generate_datasets(DEFAULT_DEMO_SPEC, 52, changed)
    for split in ("validation", "sealed"):
        assert_frame_equal(a[split], b[split], check_exact=True)


def test_independent_processes_and_hash_seeds_are_deterministic():
    code = """
import hashlib, sys
sys.path.insert(0, "src")
from redqueen.simulator import DEFAULT_DEMO_SPEC, generate_datasets
from redqueen.config import Settings
frames = generate_datasets(DEFAULT_DEMO_SPEC, 1337,
    Settings(n_sample=150, n_validation=200, n_sealed=300))
h = hashlib.sha256()
for frame in frames.values():
    h.update(frame.to_json(orient="split", double_precision=15).encode())
    h.update(str(frame.dtypes.to_dict()).encode())
print(h.hexdigest())
"""
    root = Path(__file__).resolve().parents[1]
    outputs = []
    for hash_seed in ("1", "72"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", code], cwd=root, env=env, text=True).strip())
    assert outputs[0] == outputs[1]
    assert len(outputs[0]) == hashlib.sha256().digest_size * 2


def test_generators_do_not_touch_global_numpy_rng():
    before = np.random.get_state()
    generate_datasets(DEFAULT_DEMO_SPEC, 42,
                      Settings(n_sample=20, n_validation=30, n_sealed=40))
    after = np.random.get_state()
    assert before[0] == after[0]
    np.testing.assert_array_equal(before[1], after[1])
    assert before[2:] == after[2:]


def test_legitimate_distribution_includes_attack_lookalikes():
    frame = generate_legit_background(100_000, 1337)
    assert frame.is_fraud.eq(0).all()
    assert 35 < frame.amount.median() < 45
    assert 0.045 < frame.account_age_days.lt(30).mean() < 0.075
    assert 0.03 < frame.ip_age_days.lt(7).mean() < 0.05
    assert 0.04 < frame.is_new_device.mean() < 0.06
    assert 0.02 < frame.geo_mismatch.mean() < 0.04
    assert 0.01 < frame.velocity_1h.ge(4).mean() < 0.025
    assert 0.015 < frame.merchant_category.eq("gift_card").mean() < 0.025
    assert 0.005 < frame.merchant_category.eq("crypto").mean() < 0.015
    assert 0.8 < frame.amount_ratio_to_avg.median() < 1.2
    assert frame.hour_of_day.between(9, 21).mean() > 0.7
    assert ((frame.merchant_category == "gift_card") & (frame.hour_of_day <= 4)).any()
    assert ((frame.merchant_category == "gift_card") & (frame.velocity_1h >= 6)).any()


def test_fraud_ranges_probabilities_and_generic_count():
    payload = DEFAULT_DEMO_SPEC.model_dump()
    payload.update(evasion_overlap=0.0, new_device_prob=1.0, geo_mismatch_prob=0.0)
    spec = AttackSpec.model_validate(payload)
    frame = generate_fraud(spec, 10_000, 52)
    assert len(frame) == 10_000
    assert frame.is_fraud.eq(1).all()
    assert frame.attack_name.eq("background").sum() == 150
    target = frame[frame.attack_name == spec.name]
    for field, bounds in (
        ("amount", spec.amount_range), ("velocity_1h", spec.velocity_1h_range),
        ("account_age_days", spec.account_age_range), ("ip_age_days", spec.ip_age_range),
    ):
        assert target[field].between(*bounds).all()
    assert target.hour_of_day.isin(spec.hour_window).all()
    assert target.merchant_category.isin(spec.target_merchant_categories).all()
    assert target.is_new_device.eq(1).all()
    assert target.geo_mismatch.eq(0).all()
    assert_frame_equal(frame, generate_fraud(spec, 10_000, 52), check_exact=True)
    assert not frame.equals(generate_fraud(spec, 10_000, 53))


def test_partial_fraud_probabilities_are_sampled():
    frame = generate_fraud(
        AttackSpec.model_validate({**DEFAULT_DEMO_SPEC.model_dump(), "evasion_overlap": 0}),
        20_000, 71)
    target = frame[frame.attack_name == DEFAULT_DEMO_SPEC.name]
    assert abs(target.is_new_device.mean() - DEFAULT_DEMO_SPEC.new_device_prob) < 0.02
    assert abs(target.geo_mismatch.mean() - DEFAULT_DEMO_SPEC.geo_mismatch_prob) < 0.02


@pytest.mark.parametrize("overlap", [0.0, 0.2, 1.0])
def test_overlap_replaces_expected_fraction_of_target_features(overlap):
    spec = AttackSpec.model_validate({
        **DEFAULT_DEMO_SPEC.model_dump(), "evasion_overlap": overlap})
    frame = generate_fraud(spec, 10_000, 1337)
    target = frame[frame.attack_name == spec.name]
    signature = (target.merchant_category.eq("gift_card")
                 & target.hour_of_day.isin(spec.hour_window)
                 & target.velocity_1h.between(*spec.velocity_1h_range)
                 & target.amount.between(*spec.amount_range))
    # Legitimate draws can coincidentally match; for this fixture none do.
    assert (~signature).sum() == round(len(target) * overlap)
    if overlap == 1:
        assert 35 < target.amount.median() < 45
        assert target.merchant_category.eq("gift_card").mean() < 0.04


@pytest.mark.parametrize("fraction", [0.01, 0.30])
def test_fraud_fraction_bounds(fraction):
    spec = AttackSpec.model_validate({
        **DEFAULT_DEMO_SPEC.model_dump(), "fraud_fraction": fraction})
    for frame in generate_datasets(spec, 3, Settings()).values():
        assert frame.is_fraud.sum() == round(len(frame) * fraction)


@pytest.mark.parametrize("fraction", [0, 0.009, 0.301, 1])
def test_invalid_fraud_fraction_rejected(fraction):
    with pytest.raises(ValidationError):
        AttackSpec.model_validate({**DEFAULT_DEMO_SPEC.model_dump(), "fraud_fraction": fraction})


@pytest.mark.parametrize("n", [0, 1])
def test_empty_and_rounded_zero_fraud_splits(n):
    frames = generate_datasets(
        DEFAULT_DEMO_SPEC, 1, Settings(n_sample=n, n_validation=n, n_sealed=n))
    for frame in frames.values():
        assert len(frame) == n
        assert frame.is_fraud.sum() == 0
        assert set(frame) == set(Transaction.model_fields)
        assert str(frame.amount.dtype) == "float64"
        assert str(frame.attack_name.dtype) == "object"
    assert len(generate_fraud(DEFAULT_DEMO_SPEC, 0, 4)) == 0


@pytest.mark.parametrize("n", [-1, 1.5, True])
def test_invalid_counts_rejected(n):
    with pytest.raises(ValueError):
        generate_legit_background(n, 1)
    with pytest.raises(ValueError):
        generate_fraud(DEFAULT_DEMO_SPEC, n, 1)


def test_invalid_split_count_does_not_require_configuration_change():
    with pytest.raises(ValueError):
        generate_datasets(DEFAULT_DEMO_SPEC, 1, Settings(n_sample=-1))


@pytest.mark.parametrize("field,value", [
    ("hour_window", []), ("target_merchant_categories", []),
    ("name", "background"), ("name", "none"), ("name", ""),
    ("amount_range", (float("nan"), 500.0)),
])
def test_unusable_attack_specs_fail_at_generator_boundary(field, value):
    spec = DEFAULT_DEMO_SPEC.model_copy(update={field: value})
    with pytest.raises(ValueError):
        generate_fraud(spec, 20, 1)


def test_default_generation_performance():
    start = perf_counter()
    frames = generate_datasets(DEFAULT_DEMO_SPEC, 1337, Settings())
    elapsed = perf_counter() - start
    assert sum(map(len, frames.values())) == 17_000
    assert elapsed < 2.0, f"Default split generation took {elapsed:.4f}s"
