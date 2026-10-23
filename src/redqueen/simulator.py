"""Reproducible synthetic transactions; no model calls or held-out evaluation.

Split roots are seed, seed+1 and seed+2. Each root draws separate child seeds
for legitimate and fraudulent rows, then shuffles with its own default_rng.
Only the Phase 4 gate may consume sealed rows outside generator contract tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from redqueen.config import Settings
from redqueen.schemas import ALLOWED_FIELDS, AttackSpec


DEFAULT_DEMO_SPEC = AttackSpec(
    name="GiftCardNightBurst",
    description="Gift-card transfers near $450 at 2-4 AM, with bursts and young IPs.",
    target_merchant_categories=["gift_card"],
    amount_range=(400.0, 500.0),
    hour_window=[2, 3, 4],
    velocity_1h_range=(6, 14),
    account_age_range=(5, 180),
    ip_age_range=(0, 3),
    new_device_prob=0.75,
    geo_mismatch_prob=0.35,
    fraud_fraction=0.08,
    evasion_overlap=0.20,
)


def _check_count(n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 0:
        raise ValueError("Row count must be a non-negative integer")


def _checked_spec(spec: AttackSpec) -> AttackSpec:
    # Frozen models still contain mutable lists: revalidate at the boundary.
    checked = AttackSpec.model_validate(spec.model_dump())
    if not checked.hour_window or not checked.target_merchant_categories:
        raise ValueError("Attack hours and merchant categories must be non-empty")
    if checked.name in {"none", "background", ""}:
        raise ValueError("Attack name must be non-empty and not a reserved label")
    if not np.isfinite(checked.amount_range).all():
        raise ValueError("Attack amounts must be finite")
    return checked


def _typed_features(data: dict | pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(data, columns=list(ALLOWED_FIELDS))
    return frame.astype({
        name: {"float": "float64", "int": "int64", "str": "object"}[field.dtype]
        for name, field in ALLOWED_FIELDS.items()
    })


def generate_legit_background(n: int, seed: int) -> pd.DataFrame:
    """Generate n legitimate feature rows plus is_fraud / attack_name labels.

    Amounts are lognormal (median $40, sigma 1.6). Ordinary hourly velocity is
    Poisson(0.4); 1.5% are legitimate bursts of 4-16 transactions. Categories,
    night hours, new devices and young accounts deliberately overlap attacks.
    """
    _check_count(n)
    rng = np.random.default_rng(seed)
    hours = np.array([1] * 6 + [3] * 3 + [7] * 13 + [3] * 2, dtype=float)
    velocity = rng.poisson(0.4, n).clip(0, 50)
    bursts = rng.random(n) < 0.015
    velocity[bursts] = rng.integers(4, 17, bursts.sum())
    account_age = rng.gamma(2.0, 400.0, n).clip(30, 5000).astype("int64")
    young = rng.random(n) < 0.06
    account_age[young] = rng.integers(0, 30, young.sum())
    ip_age = rng.gamma(2.0, 240.0, n).clip(7, 3650).astype("int64")
    young_ip = rng.random(n) < 0.04
    ip_age[young_ip] = rng.integers(0, 7, young_ip.sum())
    frame = _typed_features({
        "amount": rng.lognormal(np.log(40.0), 1.6, n).clip(0, 50_000),
        "hour_of_day": rng.choice(24, n, p=hours / hours.sum()),
        "velocity_1h": velocity,
        "velocity_24h": np.maximum(velocity, rng.poisson(2.5, n)).clip(0, 200),
        "account_age_days": account_age,
        "ip_age_days": ip_age,
        "is_new_device": (rng.random(n) < 0.05).astype("int64"),
        "geo_mismatch": (rng.random(n) < 0.03).astype("int64"),
        "amount_ratio_to_avg": rng.lognormal(0.0, 0.65, n).clip(0, 100),
        "merchant_category": rng.choice(
            ["grocery", "dining", "utilities", "electronics", "travel",
             "peer_transfer", "gift_card", "crypto"],
            n, p=[0.28, 0.24, 0.20, 0.10, 0.07, 0.08, 0.02, 0.01],
        ),
        "channel": rng.choice(["web", "mobile", "pos", "atm"], n,
                              p=[0.25, 0.40, 0.30, 0.05]),
    })
    frame["is_fraud"] = np.zeros(n, dtype="int64")
    frame["attack_name"] = pd.Series(["none"] * n, dtype="object")
    return frame


def generate_fraud(spec: AttackSpec, n: int, seed: int) -> pd.DataFrame:
    """Generate exactly n fraud rows, including round(1.5% * n) generic rows.

    Target fields are uniform within inclusive integer ranges and uniform over
    specified categories/hours; probabilities are independent Bernoulli draws.
    Fields absent from AttackSpec inherit the legitimate distribution, with
    daily velocity >= hourly velocity and an amount-based ratio. A fraction
    round(evasion_overlap * target_count) has ALL features replaced by legit
    draws: these rows are intentionally indistinguishable from legit activity.
    Generic fraud replaces part of n (it never inflates the fraud fraction).
    """
    _check_count(n)
    spec = _checked_spec(spec)
    rng = np.random.default_rng(seed)
    frame = generate_legit_background(n, int(rng.integers(0, 2**63)))
    frame["amount"] = rng.uniform(*spec.amount_range, n)
    frame["hour_of_day"] = rng.choice(spec.hour_window, n)
    frame["velocity_1h"] = rng.integers(
        spec.velocity_1h_range[0], spec.velocity_1h_range[1] + 1, n)
    frame["velocity_24h"] = (frame["velocity_1h"].to_numpy()
                             + rng.poisson(6, n)).clip(0, 200)
    frame["account_age_days"] = rng.integers(
        spec.account_age_range[0], spec.account_age_range[1] + 1, n)
    frame["ip_age_days"] = rng.integers(spec.ip_age_range[0], spec.ip_age_range[1] + 1, n)
    frame["is_new_device"] = (rng.random(n) < spec.new_device_prob).astype("int64")
    frame["geo_mismatch"] = (rng.random(n) < spec.geo_mismatch_prob).astype("int64")
    frame["merchant_category"] = pd.Series(
        rng.choice(spec.target_merchant_categories, n), dtype="object")
    frame["amount_ratio_to_avg"] = (
        frame["amount"].to_numpy() / 40.0 * rng.lognormal(0, 0.3, n)).clip(0, 100)
    frame["is_fraud"] = np.ones(n, dtype="int64")
    frame["attack_name"] = pd.Series([spec.name] * n, dtype="object")

    generic_count = round(n * 0.015)
    order = rng.permutation(n)
    generic = order[:generic_count]
    evaders = order[generic_count:generic_count + round(
        (n - generic_count) * spec.evasion_overlap)]
    lookalikes = generate_legit_background(len(evaders), int(rng.integers(0, 2**63)))
    for field in ALLOWED_FIELDS:
        frame.loc[evaders, field] = lookalikes[field].to_numpy()
    frame.loc[generic, "amount"] = rng.uniform(6000, 15_000, generic_count)
    frame.loc[generic, "velocity_1h"] = rng.integers(12, 26, generic_count)
    frame.loc[generic, "velocity_24h"] = rng.integers(26, 60, generic_count)
    frame.loc[generic, "attack_name"] = "background"
    return frame


def generate_datasets(
    spec: AttackSpec,
    seed: int,
    settings: Settings,
) -> dict[str, pd.DataFrame]:
    """Build isolated splits with roots seed / seed+1 / seed+2.

    IDs have S/V/T prefixes; frames share explicit dtypes, columns, RangeIndex
    and deterministic shuffled row order. IDs identify rows within this run,
    not across runs. No global RNG state is read or modified.
    """
    spec = _checked_spec(spec)
    sizes = (settings.n_sample, settings.n_validation, settings.n_sealed)
    for n in sizes:
        _check_count(n)
    datasets = {}
    for offset, (split, prefix, n) in enumerate(zip(
        ("sample", "validation", "sealed"), ("S", "V", "T"), sizes, strict=True
    )):
        rng = np.random.default_rng(seed + offset)
        n_fraud = round(n * spec.fraud_fraction)
        legit_seed, fraud_seed = (int(s) for s in rng.integers(0, 2**63, 2))
        frame = pd.concat([
            generate_legit_background(n - n_fraud, legit_seed),
            generate_fraud(spec, n_fraud, fraud_seed),
        ], ignore_index=True)
        frame = frame.iloc[rng.permutation(n)].reset_index(drop=True)
        frame["txn_id"] = pd.Series([f"{prefix}{i:08d}" for i in range(n)], dtype="object")
        frame["split"] = pd.Series([split] * n, dtype="object")
        datasets[split] = frame
    return datasets