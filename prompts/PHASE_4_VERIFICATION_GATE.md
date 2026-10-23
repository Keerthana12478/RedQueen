# PHASE 4 — INDEPENDENT VERIFICATION GATE (25 minutes)

> Paste into Google Antigravity. Implement only this phase. The gate is deterministic Python; it must not call Gemma.

## 1. Phase Objective
Implement `VerificationGate`: validation-split coarse feedback, one-shot sealed-test final evaluation, all verification checks, deterministic ACCEPTED/REJECTED verdicts with explicit reasons, and a headless benchmark script.

## 2. Existing Project Context
RedQueen: Gemma proposes a restricted declarative rule; deterministic Python verifies it; only verified rules become active in the sandbox. Gemma never grades its own rule. Splits: sample (Gemma-visible evidence), validation (coarse feedback, ≤1 retry), sealed (never visible to Gemma; evaluated once per final candidate; no tuning). Patched detector = baseline OR rule (monotonic: patches may add flags, never remove or weaken baseline flags). The ~1.5% global FPR ceiling is a **configurable project design threshold, not an industry standard**. The PPT's illustrative numbers (38.2% → 86.4%, +48.2 pp, 0.8% FPR) are **not** results and must never appear as hardcoded outputs.

## 3. Previous Phase Dependencies
Phase 2: `generate_datasets`, `BaselineDetector`, `apply_rule`, `combine`, `compute_metrics`, `segment_fpr`, `legit_flagged_per_10k`. Phase 3: `DefenseRule`, `AttackSpec`, replay scenarios. Phase 1: `VerificationReport`, `CheckResult`, `ValidationFeedback`, `Settings` thresholds.

## 4. Exact Implementation Tasks
1. **Metric definitions (write them in the module docstring and README):**
   - Target-attack recall = TP/(TP+FN) over fraud rows with `attack_name == spec.name`.
   - Recall gain is in **percentage points**: `(patched_recall - baseline_recall) * 100`. Relative improvement may be shown for information but is never used for gating.
   - Global FPR = FP/(FP+TN) over all legitimate rows of the split; also report legit flagged per 10,000.
2. **`evaluate_validation(rule, datasets, baseline) -> ValidationFeedback`**: compute patched metrics on the validation split only. Return **coarse** buckets: `recall_gain_bucket` (`none` <1 pp, `small` 1–5, `medium` 5–15, `large` ≥15), `fpr_exceeded` (bool), `segment_violation` (bool). No exact metrics, no row data. Track a call counter on the gate instance; enforce `max_validation_retries` (a third feedback request for the same run raises `ValidationBudgetExceeded` (initial validation + one optional retry allowed)).
3. **`evaluate_final(rule, datasets, baseline, approved_attacks) -> VerificationReport`** — runs on the sealed split. Enforce **single evaluation per candidate**: key by run id and gate-instance finalization state; any second final call for that run raises `SealedAlreadyEvaluated`, even if the candidate rule differs. The sealed split is never used for tuning and never returned to callers beyond aggregate metrics.
4. **Checks (each a `CheckResult` with observed, threshold, pass/fail, human-readable detail):**
   1. `rule_valid` — re-parse through `DefenseRule` schema; fields/ops/values legal.
   2. `rule_complexity` — clauses ≤ `max_clauses` (3), only FLAG.
   3. `monotonic` — patched flags ⊇ baseline flags (verify elementwise, not assumed).
   4. `target_recall_gain` — gain ≥ `min_recall_gain_pp` (default 5.0 pp) on sealed target-attack recall.
   5. `global_fpr` — patched global FPR ≤ `global_fpr_ceiling`.
   6. `segment_fpr` — for each segment in (`merchant_category`, `channel`, `account_age_bucket`) with ≥ `min_segment_legit_count` legit rows, patched segment FPR ≤ `segment_fpr_budget`; report the worst offending segment. Segments below the count threshold are skipped and listed as "insufficient data" (not silently passed).
   7. `regression` — for each previously approved attack in `approved_attacks` (list of `AttackSpec`; ships with 2 built-in reference specs, deterministic seeds), regenerate data with its spec, and verify the **cumulative active sandbox detector plus candidate** retains recall on that attack ≥ its previously approved detector (must hold by monotonicity, but test it) and global FPR on that scenario's legitimate rows still ≤ ceiling.
5. **Verdict**: `ACCEPTED` iff all checks pass; else `REJECTED` with `reason` listing the first failed check by priority order (valid → complexity → monotonic → fpr → segment → regression → gain) plus all failing checks in `checks`. The text label for display: `ACCEPTED — ACTIVE IN SANDBOX` / `REJECTED — <reason>`. No rejected rule may be activated: provide `SandboxState` (in `verification.py`) with `activate(rule, report)` that raises unless `report.verdict == "ACCEPTED"`; it appends the rule to the active patch list (in-memory, per session) and the active list is applied via `combine`.
6. **Determinism and latency**: measure `latency_ms` of final verification with `time.perf_counter`; the verdict and metrics must be identical across repeated runs given same inputs (latency excluded).
7. **`benchmarks/run_benchmark.py`** (headless): args `--mode replay|live`, `--seed`, `--scenarios all`, `--json out.json`. For each replay scenario: generate data, baseline metrics, validation feedback, final sealed verdict; print a table (scenario, baseline recall, patched recall, gain pp, FPR, legit/10k, verdict, reason) and optionally JSON. In live mode, Gemma is only used if a key exists; otherwise exit with a clear message. All numbers are computed, never hardcoded.
8. **Adversarial rule fixtures** in tests: over-broad (`amount >= 1`), narrow-but-useless, segment-violating (flags all `crypto`), 3-clause good rule, malformed rule, rule that overfits sample but fails sealed.

## 5. Files to Create or Modify
`src/redqueen/verification.py`, `benchmarks/run_benchmark.py`, `tests/test_verification.py`, `tests/test_benchmark.py`; update `README.md` (metric definitions, thresholds, how verdicts are produced) and `docs/ARCHITECTURE.md`. Minimal additive edits to `schemas.py` only if required and backward compatible (document them).

## 6. Technical Constraints
- Gate imports no Gemma/google-genai code. It receives rules as objects, never strings to execute.
- Sealed split only touched inside `evaluate_final`; return aggregates only. Add a test asserting `defender_forge`/`attack_lab` modules never reference the gate's sealed data path.
- Thresholds come from `Settings`; tests may override them but defaults stay as in Phase 1.
- Whole final verification (including regression on 2 approved attacks) should complete in under ~3 s at default sizes.
- Guard divide-by-zero for empty classes.

## 7. Acceptance Criteria
- Good narrow rule on the default demo spec → ACCEPTED with computed metrics.
- Over-broad rule → REJECTED citing `global_fpr`; segment-violating rule → REJECTED citing `segment_fpr`; weak rule → REJECTED citing `target_recall_gain`; invalid rule → REJECTED at `rule_valid`.
- `SandboxState.activate` raises for REJECTED reports; ACCEPTED rules appear in the active list; baseline flags remain flagged.
- Second `evaluate_final` in the same run raises even for a changed candidate; a third validation evaluation beyond the initial check and one retry raises.
- Feedback contains only coarse buckets (assert no numeric metric fields).
- Repeat runs give identical verdicts/metrics.
- Metric definitions in code match the README (pp vs relative).

## 8. Testing Instructions
```
pytest -q tests/test_verification.py tests/test_benchmark.py
pytest -q
python benchmarks/run_benchmark.py --mode replay --seed 1337 --scenarios all
```
Expected: replay table shows a mix of ACCEPTED and REJECTED verdicts computed from data; no crash with no API key. Edge cases: zero target fraud, tiny segments, threshold boundary values (exactly at ceiling passes, just above fails), unseeded vs seeded reproducibility.

## 9. Deliverables
A deterministic, tested gate with explicit reasons, sealed-split discipline, sandbox activation rules, and a headless benchmark that runs offline.

## 10. Handoff Instructions
Phase 5 needs: `VerificationReport` fields for display, `ValidationFeedback`, `SandboxState`, `run_benchmark`-style helpers, segment FPR tables, latency values. Phase 6's `pipeline.run_redqueen` will orchestrate forge → validation feedback → ≤1 retry → sealed final → sandbox activation.

## 11. Completion Report
Files created/modified; tests run + counts; benchmark output (actual); implementation status; thresholds used; unresolved issues; Phase 5 readiness. Do not report passes without running the commands.

---

## Audited verification invariants and contract corrections
- **Important Phase 1 schema dependency:** `VerificationReport` should contain `baseline` and `patched` metrics from the **sealed** evaluation, but UI-facing code may receive these aggregates only. For target-attack gating, compute target-specific recall separately; overall recall and target recall are different metrics. Add optional target metrics to the report with a backward-compatible schema change if needed.
- `evaluate_validation` may run once on the initial candidate and **once after the optional retry** (maximum **two validation evaluations**). A third request is rejected. Do not implement 'a second feedback request raises' because that would make the permitted retry impossible.
- Gate final evaluation must be one-shot **per run**, not only per rule hash. Use a run identifier or gate-instance state; prevent a second final evaluation in the same run even if a new rule object is supplied. Across new independent runs, a new held-out seed is required when sealed results might inform development.
- Invalid rule input should produce a deterministic `REJECTED` report **without executing invalid code or consuming the sealed split**; avoid a schema exception that prevents a verdict.
- Target gain requires a nonzero number of sealed target fraud rows. If absent, reject as insufficient evidence; do not treat zero recall as a passing threshold.
- Regression check should evaluate the **current cumulative sandbox detector plus candidate** against previously approved attack scenarios, not merely compare the candidate to the original baseline. Existing accepted rules must remain active. Test global/segment FPR after cumulative activation.
- A baseline FPR already above ceiling cannot be repaired by OR-only rules. Reject with a clear reason and document the simulator/baseline feasibility condition.
- The headless benchmark script may be a narrow replay-only working harness in this phase; Phase 6 finishes live integration. Never fabricate successful accepted fixtures: measure and adjust legitimate fixture design transparently.
