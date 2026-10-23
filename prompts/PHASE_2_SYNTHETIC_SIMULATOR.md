# PHASE 2 — SYNTHETIC FRAUD SIMULATOR & BASELINE (20 minutes)

> Paste into Google Antigravity. Implement only this phase. Report honestly.

## 1. Phase Objective
Implement a reproducible synthetic transaction simulator, the baseline detector, the rule execution engine, metrics, and failure analysis. Output three isolated splits (sample / validation / sealed) with realistic overlap between legitimate and fraudulent behaviour.

## 2. Existing Project Context
RedQueen is an adversarial fraud-testing arena: Gemma 4 turns judge scenarios into typed `AttackSpec`s and proposes restricted `DefenseRule`s; deterministic Python simulates, evaluates and verifies; only verified rules activate in the sandbox. **Gemma proposes. Python verifies.** All data is synthetic. Splits: sample (only evidence Gemma may see), validation (coarse feedback, ≤1 retry), sealed (never visible to Gemma, evaluated once per final candidate). Rules are declarative JSON with ≤3 ANDed clauses and action FLAG; the patched detector is baseline OR rule (monotonic).

## 3. Previous Phase Dependencies
From Phase 1: `schemas.py` (`ALLOWED_FIELDS`, `AttackSpec`, `DefenseRule`, `Clause`, `Evidence`, `MetricSet`), `config.py` (`Settings`), stub signatures in `simulator.py`, `baseline.py`, `rule_engine.py`, `metrics.py`, `failure_analysis.py`. Do not rename them.

## 4. Exact Implementation Tasks
1. **Legitimate background** `generate_legit_background(n, seed)`: use `np.random.default_rng(seed)`. Realistic distributions: `amount` lognormal (median ≈ 40, clipped to 50000); `hour_of_day` weighted to daytime with a small night tail; `velocity_1h` Poisson(0.4) clipped; `velocity_24h` Poisson(2.5); `account_age_days` gamma-like with a minority (~6%) under 30 days; `ip_age_days` mostly large with ~4% under 7; `is_new_device` ~5%; `geo_mismatch` ~3%; `amount_ratio_to_avg` lognormal around 1; `merchant_category` weighted (grocery/dining/utilities common, gift_card ~2%, crypto ~1%); `channel` weighted. This **deliberately includes legitimate look-alikes** (e.g. legit night gift-card buys, legit bursts at ~1–2% of rows, new-account users).
2. **Fraud generation** `generate_fraud(spec, n, seed)`: sample every field from the `AttackSpec` ranges/probabilities; `evasion_overlap` (0–1) blends a fraction of fraud rows' features toward the legit distribution (e.g. lower velocity, daytime hours) so some fraud is genuinely hard. Set `is_fraud=1`, `attack_name=spec.name`. Also include a small (≈1–2% of the fraud count) background of "generic" fraud unrelated to the spec labelled `attack_name="background"` so the baseline has something to catch.
3. **`generate_datasets(spec, seed, settings)`**: build each split with its own derived seed (`seed`, `seed+1`, `seed+2` documented in code and README), sizes from `settings`, fraud count = `round(n * spec.fraud_fraction)`. Assign `split` column, unique `txn_id` per split (prefix `S`,`V`,`T`). Splits must be disjoint in `txn_id`, same columns and dtypes. Same inputs ⇒ identical DataFrame values, dtypes, index, and row order (test it).
4. **Baseline detector** `BaselineDetector`: fixed, documented, deliberately imperfect rule list (e.g. `amount >= 5000`; `velocity_1h >= 12`; `geo_mismatch == 1 and is_new_device == 1 and amount >= 800`; `account_age_days < 3 and amount >= 1000`). Expose `rules` as `DefenseRule`-compatible clause lists for display and reuse `rule_engine`. Calibrate so overall baseline FPR on legit background is roughly 0.3–0.8% and baseline recall on typical spec attacks is clearly incomplete (≈20–50%). Never hardcode target metrics; just choose thresholds and report what is measured.
5. **`rule_engine.apply_rule`**: vectorised evaluation of each clause with pandas, AND across clauses; re-validate the rule through the schema before use; reject unknown fields/ops defensively with a typed `RuleExecutionError`. `combine(baseline, rule)` returns elementwise OR and must never clear a baseline flag.
6. **`metrics.compute_metrics`**: recall = TP/(TP+FN) over fraud rows (return 0.0 when no fraud), precision, FPR = FP/(FP+TN) over legit rows, and counts. Provide `recall_gain_pp(base, patched) = (patched.recall - base.recall) * 100` (**percentage points**; document that relative improvement is a different quantity and not used for gating). Provide `legit_flagged_per_10k(fp, n_legit)`. **Target-attack recall** = recall restricted to rows where `attack_name == spec.name`. `segment_fpr(df, flags, segments)`: FPR per category value for `merchant_category`, `channel`, plus buckets `account_age_bucket` (`<30`, `30-365`, `>365`); return legit count per segment so thin segments can be handled by `min_segment_legit_count`.
7. **`failure_analysis.build_evidence(sample_df, baseline_flags, settings)`**: only from the sample split. `missed_fraud`: up to 25 target-attack fraud rows the baseline missed (fields restricted to permitted fields; drop `txn_id`, `split`, `is_fraud`, `attack_name`). `lookalike_legit`: up to 25 legit rows nearest to the missed fraud in normalised feature space (deterministic nearest-neighbour via NumPy, no sklearn). `summary_stats`: counts, baseline recall on sample, per-field quantiles for missed fraud vs look-alikes. Assert/raise if given a non-sample split.
8. Add a small `scripts/demo_sim.py`? **No** — keep to listed files; use a pytest-only sanity run instead.

## 5. Files to Create or Modify
`src/redqueen/simulator.py`, `baseline.py`, `rule_engine.py`, `metrics.py`, `failure_analysis.py`, `tests/test_simulator.py`, `tests/test_baseline.py`, `tests/test_rule_engine.py`, `tests/test_metrics.py`, `tests/test_failure_analysis.py`; update `README.md` (data design, seeds) and `docs/ARCHITECTURE.md` if needed. Do not modify `schemas.py` field names.

## 6. Technical Constraints
Pure Pandas/NumPy; no new dependencies; seeded `default_rng` only (no global `np.random`, no `random` without seed); generating all splits for default sizes <2 s; rule evaluation on 10k rows <100 ms; no `eval`/`query` strings built from rule input (use boolean masks); output frames pass `Transaction` column/dtype checks; sealed data is produced here but must only be consumed by the gate in Phase 4.

## 7. Acceptance Criteria
- Same `(spec, seed)` ⇒ identical frames; different seed ⇒ different frames.
- Splits disjoint, correct sizes, fraud fraction within ±1 percentage point of spec (per-split).
- Legit/fraud feature distributions overlap (test: at least some legit rows satisfy typical fraud thresholds, e.g. legit night gift-card rows exist).
- Baseline metrics computed from data, with FPR on the legit background below 1.5% and target-attack recall < 60% for the default demo spec (gift-card night burst) — if not, retune the baseline thresholds, not the test.
- `combine` never turns a baseline flag off (property-style test over random rules).
- Rule engine matches a hand-computed toy DataFrame for each operator.
- `build_evidence` fails on validation/sealed input and its output contains no forbidden columns.

## 8. Testing Instructions
```
pytest -q tests/test_simulator.py tests/test_baseline.py tests/test_rule_engine.py tests/test_metrics.py tests/test_failure_analysis.py
pytest -q
```
Edge cases: zero fraud rows (recall 0, no crash), zero legit rows in a segment, rule with 3 clauses, categorical `==`, invalid rule raises `RuleExecutionError`, `fraud_fraction` bounds, seed determinism across two runs. Tests assert behaviour and values, not file existence.

## 9. Deliverables
Working simulator + baseline + rule engine + metrics + evidence builder, deterministic and tested, producing real baseline numbers for a default spec.

## 10. Handoff Instructions
Phase 3 needs: `build_evidence(...) -> Evidence`, `DefenseRule`/`AttackSpec` validation, `apply_rule`, and a documented default demo `AttackSpec` (add `DEFAULT_DEMO_SPEC` to `simulator.py`: gift-card transfers ~$450, 2–4 AM, high velocity, young IP). Phase 4 needs `generate_datasets`, `compute_metrics`, `segment_fpr`, `combine`.

## 11. Completion Report
List files created/modified; tests run (exact commands); passed/failed counts; measured baseline recall/FPR for the default spec (as measured, not targeted); implementation status per module; unresolved issues; Phase 3 readiness. Do not claim tests passed unless you ran them.

---

## Audited integration safeguards
- The default demo attack must be detectable by an allowed ≤3-clause rule while legitimate look-alikes make FPR meaningful. Do not silently tune data to force an ACCEPTED verdict: document the simulator assumptions, run both positive and negative rule fixtures, and report observed metrics.
- Generate `DEFAULT_DEMO_SPEC` in this phase and ensure every generated column, type, and allowed category matches Phase 1. Explicitly generate `ip_age_days` (new IP), `merchant_category="gift_card"`, `hour_of_day`, and `velocity_1h` so the judge scenario is representable.
- Fix the contradictory 'same inputs ⇒ byte-identical' criterion to **value-, dtype-, index- and row-order-identical** frames; serialization byte identity is not required.
- Avoid a `target_recall` denominator of zero being treated as evidence of success; the final gate must REJECT when the sealed target attack has no positive rows.
- Use separate independent seeds per split and avoid row leakage; seeded splits alone do not prevent repeated sealed-test contamination across future tuning.
