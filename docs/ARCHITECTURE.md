# RedQueen — Architecture Reference

> **Gemma proposes. Python verifies.**

One-page contract summary for all phases.  Filenames, schema field names, and
invariants listed here are **frozen** — additions require documented,
backward-compatible changes.

---

## Data Flow

```
[User scenario (text)]
        │
        ▼
  attack_lab.py          ← Gemma 4 (live) or replay fixture
        │  AttackSpec
        ▼
  simulator.py           ← Deterministic Python; NumPy seeded RNG
        │  dict[split → DataFrame]
        │   ├─ sample       (2 000 rows)  → failure_analysis, UI evidence
        │   ├─ validation   (5 000 rows)  → VerificationGate (coarse feedback)
        │   └─ sealed       (10 000 rows) → VerificationGate ONLY (one-shot)
        ▼
  baseline.py            ← Rule-based baseline detector
        │  BaselineDetector
        ▼
  failure_analysis.py    ← Sample split only → Evidence (sample rows)
        │  Evidence
        ▼
  defender_forge.py      ← Gemma 4 proposes DefenseRule
        │  DefenseRule
        ▼
  verification.py        ← Pure Python: validate → (optional retry) → seal
        │  VerificationReport
        ▼
  pipeline.py            ← PipelineResult (no raw sealed/validation rows)
        │
        ▼
  app.py (Streamlit)     ← Display only; reads PipelineResult
```

---

## Split Rules

| Split      | Rows   | Who reads it                      | Visible to model? |
|------------|--------|-----------------------------------|-------------------|
| sample     | 2 000  | failure_analysis, UI, baseline     | Yes (Evidence)    |
| validation | 5 000  | VerificationGate only (coarse)     | No (coarse only)  |
| sealed     | 10 000 | VerificationGate.evaluate_final    | **Never**         |

Sealed data is consumed **one time only**; never re-evaluated for tuning.

---

## Module Table

| Module              | Phase | Responsibility                                      |
|---------------------|-------|-----------------------------------------------------|
| `config.py`         | 1     | Frozen Settings; SecretStr for API key              |
| `schemas.py`        | 1     | All cross-phase Pydantic contracts                  |
| `simulator.py`      | 2     | Synthetic data generation (seeded)                  |
| `baseline.py`       | 2     | Deterministic rule-based baseline detector          |
| `rule_engine.py`    | 2     | Apply DefenseRule; combine with baseline (OR)       |
| `metrics.py`        | 2     | compute_metrics, segment_fpr                        |
| `failure_analysis.py` | 2  | Build Evidence from sample split                    |
| `gemma_client.py`   | 3     | google-genai wrapper; structured JSON generation    |
| `attack_lab.py`     | 3     | Scenario → AttackSpec (live or replay)              |
| `defender_forge.py` | 3     | Evidence → DefenseRule (live or replay)             |
| `replay.py`         | 3     | Load pre-recorded scenarios from data/replay/       |
| `verification.py`   | 4     | Validation + sealed gate; pure Python               |
| `pipeline.py`       | 5     | End-to-end orchestration; PipelineResult dataclass  |
| `app.py`            | 5     | Streamlit dashboard                                 |

---

## Invariants (Binding for All Phases)

1. **Sealed-split gate boundary**: `sealed` rows are only consumed inside
   `VerificationGate.evaluate_final`.  The pipeline passes the sealed
   DataFrame opaquely; it must not inspect sealed metrics itself.

2. **No model grading its own rule**: Gemma proposes a rule; a separate
   deterministic Python gate verifies it.  The model never sees validation
   or sealed metrics.

3. **Declarative rules only**: `DefenseRule` clauses are evaluated by
   `rule_engine.apply_rule` using pure Python comparisons.  No `eval`,
   `exec`, SQL, or shell calls are ever used.

4. **Monotonic patch**: `combine(baseline, rule)` is logical OR only.  The
   patched detector can only flag *more* transactions than the baseline —
   never fewer.

5. **Every metric from simulator output**: No hardcoded PPT numbers; all
   recall, precision, and FPR values are computed from the simulator's
   synthetic data.

6. **Secrets never logged**: `Settings.api_key` is a `SecretStr`; its value
   is never written to logs, repr output, or UI components.

7. **No network at import time**: `GemmaClient` is only instantiated at
   runtime.  All modules import cleanly without side-effects.

8. **One-shot sealed evaluation**: A final candidate receives exactly one
   sealed evaluation.  Fresh held-out seeds/datasets are required for new
   development cycles.

9. **Sample-only evidence in UI**: `PipelineResult.evidence` contains only
   sample-split rows.  `PipelineResult` never includes raw validation or
   sealed DataFrames.

10. **Live vs replay clearly labelled**: `RunTelemetry.mode` always reflects
    which path was taken; the UI displays this prominently.

---

## Configuration Thresholds (Configurable, Not Industry Standards)

| Setting                  | Default | Meaning                                      |
|--------------------------|---------|----------------------------------------------|
| `global_fpr_ceiling`     | 0.015   | Maximum allowed FPR on the full dataset      |
| `min_recall_gain_pp`     | 5.0 pp  | Minimum marginal recall gain (percentage pts)|
| `segment_fpr_budget`     | 0.03    | Per-segment FPR ceiling                      |
| `max_clauses`            | 3       | Maximum AND-clauses in a DefenseRule         |
| `max_validation_retries` | 1       | One optional retry after initial validation  |
| `min_segment_legit_count`| 50      | Minimum legitimate rows for segment FPR test |

> These are **MVP implementation choices**, not validated industry standards.
> The `min_recall_gain_pp=5.0` threshold is the configurable gate; the PPT's
> ≥+25% example is illustrative and uses different units.

## Phase 4 additions

VerificationReport adds backward-compatible optional aggregate target recall, original
baseline, candidate-only metrics, segment summaries, run identifier, and candidate/active-rule
fingerprints. Existing required fields retain their names. Report baseline means the current
cumulative detector before the candidate; patched means cumulative detector plus candidate.
SandboxState binds activation to this candidate and the exact preexisting active-rule list.
A run is finalized before sealed access, and further feedback or final evaluation is refused.
Merchant generation uses stratified category counts across burst/ordinary groups; no thresholds
or baseline rules were changed to satisfy the new segment checks.
