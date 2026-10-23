# PHASE 1 — SETUP & ARCHITECTURE (10 minutes)

> Paste this whole file into Google Antigravity. Do NOT implement later phases. Do not claim anything works unless you ran it.

## 1. Phase Objective
Create a new repository skeleton for **RedQueen** with a fixed module layout, shared Pydantic schemas, configuration, and stub interfaces so Phases 2–6 integrate without conflicting assumptions. All cross-phase contracts are defined **here**.

## 2. Existing Project Context
RedQueen ("Let the fraudster go first") is an adversarial fraud-testing arena for Hacktoberfest Hack Day Chennai × CodeYGen 2026 (FinTech PS1). Gemma 4 (via Gemini API, `google-genai`) (a) turns a judge's natural-language fraud scenario into a typed attack spec and (b) proposes a restricted declarative defensive rule. **Deterministic Python** simulates synthetic transactions, runs a baseline detector, analyses failures, and independently verifies the rule. Only verified rules become active in the sandbox. Principle: **Gemma proposes. Python verifies.** Gemma never grades its own rule. Data is 100% synthetic. Not a production fraud detector. Stack: Python 3.13 (or compatible), Streamlit, Pandas, NumPy, Pydantic v2, google-genai, pytest. License Apache-2.0. Total build budget 120 min; this phase gets 10.

## 3. Previous Phase Dependencies
None. New repository.

## 4. Exact Implementation Tasks
1. `git init`; create the layout in §5. Check `python --version`; use 3.13 if all deps install, else the newest compatible and record it in README.
2. `requirements.txt` (pinned minimums, no extras): `streamlit`, `pandas`, `numpy`, `pydantic>=2`, `google-genai`, `python-dotenv`, `pytest`. Add `pyproject.toml` only for `pytest` config (`pythonpath = ["src"]`, `testpaths = ["tests"]`).
3. `.env.example`: `GEMINI_API_KEY=`, `REDQUEEN_MODEL=gemma-4-31b-it`, `REDQUEEN_FALLBACK_MODEL=gemma-4-26b-a4b-it`, `REDQUEEN_MODE=live` (`live|replay`), `REDQUEEN_SEED=1337`. `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.log`, `.streamlit/secrets.toml`.
4. `src/redqueen/config.py`: frozen Pydantic `Settings` loaded from env (python-dotenv). Fields and defaults:
   - `seed=1337`, `mode`, `model`, `fallback_model`, `api_key` (as `SecretStr`; never printed/logged; `repr` must not leak it)
   - Split sizes: `n_sample=2000`, `n_validation=5000`, `n_sealed=10000`
   - Thresholds (configurable design values, **not** industry standards): `global_fpr_ceiling=0.015`, `min_recall_gain_pp=5.0`, `segment_fpr_budget=0.03`, `max_clauses=3`, `max_validation_retries=1` (one optional retry after the initial validation; at most two validation evaluations), `min_segment_legit_count=50`
5. `src/redqueen/schemas.py` — implement exactly (Pydantic v2, `extra="forbid"`):
   - `ALLOWED_FIELDS: dict[str, FieldSpec]` where FieldSpec = (dtype, min, max, categories). Fields: `amount` (float 0–50000), `hour_of_day` (int 0–23), `velocity_1h` (int 0–50), `velocity_24h` (int 0–200), `account_age_days` (int 0–5000), `ip_age_days` (int 0–3650), `is_new_device` (int 0/1), `geo_mismatch` (int 0/1), `amount_ratio_to_avg` (float 0–100), `merchant_category` (str in `{grocery,electronics,gift_card,travel,utilities,dining,crypto,peer_transfer}`), `channel` (str in `{web,mobile,pos,atm}`).
   - `ALLOWED_OPS = {">", ">=", "<", "<=", "==", "!="}`; categorical fields allow only `==`/`!=`.
   - `Clause(field, op, val)`; validator checks field exists, op legal for dtype, val type and bounds.
   - `DefenseRule(clauses: list[Clause] (1..3), action: Literal["FLAG"], rationale: str (≤500 chars, display only))`. A `model_validator(mode="before")` accepts the single-clause shorthand `{"field","op","val","action"}` and normalises it into `clauses`. Clauses are ANDed. No other logic constructs.
   - `AttackSpec(name, description, target_merchant_categories: list, amount_range: (float,float), hour_window: list[int], velocity_1h_range: (int,int), account_age_range: (int,int), ip_age_range: (int,int), new_device_prob: float 0–1, geo_mismatch_prob: float 0–1, fraud_fraction: float 0.01–0.30, evasion_overlap: float 0–1)` with range-ordering validators and field bounds from `ALLOWED_FIELDS`.
   - `Transaction` column contract = `ALLOWED_FIELDS` keys plus `txn_id`, `is_fraud` (0/1), `attack_name` (str; `"none"` for legitimate), `split` (`sample|validation|sealed`).
   - `Evidence` (`missed_fraud: list[dict]`, `lookalike_legit: list[dict]`, `permitted_fields: list[str]`, `summary_stats: dict`) — sample split only.
   - `ValidationFeedback` (coarse only: `recall_gain_bucket` in `{none,small,medium,large}`, `fpr_exceeded: bool`, `segment_violation: bool`).
   - `CheckResult(name, passed, observed, threshold, detail)`; `VerificationReport(verdict: Literal["ACCEPTED","REJECTED"], reason: str, checks: list[CheckResult], baseline: MetricSet, patched: MetricSet, recall_gain_pp: float, legit_flagged_per_10k: float, sealed_evaluated: bool, latency_ms: float)`; `MetricSet(recall, precision, fpr, tp, fp, tn, fn)`.
   - `RunTelemetry(mode: Literal["live","replay"], model_used: str|None, model_latency_ms, verification_latency_ms, attempts: int)`.
6. `src/redqueen/` stub modules with **docstring + typed signatures raising `NotImplementedError`** (exact signatures; later phases must not rename):
   - `simulator.py`: `generate_datasets(spec: AttackSpec, seed: int, settings: Settings) -> dict[str, pd.DataFrame]` (keys `sample`,`validation`,`sealed`); `generate_legit_background(n:int, seed:int)->pd.DataFrame`.
   - `baseline.py`: `class BaselineDetector: predict(df)->pd.Series[bool]; rules: list`.
   - `rule_engine.py`: `apply_rule(rule: DefenseRule, df) -> pd.Series[bool]`; `combine(baseline_flags, rule_flags) -> pd.Series[bool]` (logical OR only).
   - `metrics.py`: `compute_metrics(y_true, y_pred) -> MetricSet`; `segment_fpr(df, flags, segments:list[str]) -> dict`.
   - `failure_analysis.py`: `build_evidence(sample_df, baseline_flags, settings) -> Evidence`.
   - `gemma_client.py`: `class GemmaClient: generate_json(prompt, schema_model, ...)`, `smoke_test()`.
   - `attack_lab.py`: `generate_attack_spec(scenario: str, client|None, mode) -> tuple[AttackSpec, RunTelemetry]`.
   - `defender_forge.py`: `propose_rule(evidence: Evidence, client|None, mode, feedback: ValidationFeedback|None) -> tuple[DefenseRule, RunTelemetry]`.
   - `replay.py`: `list_replay_scenarios()`, `load_replay(name)->dict`.
   - `verification.py`: `class VerificationGate: evaluate_validation(rule, datasets, baseline)->ValidationFeedback; evaluate_final(rule, datasets, baseline, approved_attacks)->VerificationReport`.
   - `pipeline.py`: `run_redqueen(scenario: str, settings: Settings, mode: str|None=None) -> PipelineResult` (dataclass bundling spec, dataset **metadata only**, sample-only evidence, rule, report, telemetry; never raw sealed/validation frames).
7. Other files: `app.py` (Streamlit placeholder rendering "RedQueen — setup OK" and current mode), `scripts/smoke_gemma.py` (stub), `benchmarks/run_benchmark.py` (stub), `data/replay/.gitkeep`, `LICENSE` (full Apache-2.0 text, year 2026), `README.md` skeleton (title, tagline, **Gemma proposes. Python verifies.**, architecture list, setup steps, run modes, "Illustrative PPT numbers are not experimental results", honest limitations, TODO sections per phase).
8. `docs/ARCHITECTURE.md`: one-page contract summary (data flow, split rules, module table, invariant list below).

## 5. Files to Create or Modify
```
LICENSE  README.md  requirements.txt  pyproject.toml  .env.example  .gitignore  app.py
docs/ARCHITECTURE.md
src/redqueen/{__init__,config,schemas,simulator,baseline,rule_engine,metrics,failure_analysis,gemma_client,attack_lab,defender_forge,replay,verification,pipeline}.py
scripts/smoke_gemma.py   benchmarks/run_benchmark.py   data/replay/.gitkeep
tests/{__init__,test_schemas,test_config}.py
```
Filenames above are **frozen** for all phases.

## 6. Technical Constraints
- Invariants (put in ARCHITECTURE.md): sealed split never reaches `gemma_client`, `attack_lab`, `defender_forge` or UI evidence; rules are declarative only — no `eval`/`exec`/SQL/shell; accepted patch = baseline OR rule (monotonic); every metric computed from simulator output; live and replay clearly labelled; secrets never logged.
- Gate-owned sealed access: sealed data is only consumed inside `VerificationGate.evaluate_final`.
- Type hints everywhere; no global mutable state; no network calls at import time.

## 7. Acceptance Criteria
- `pip install -r requirements.txt` succeeds in a fresh venv.
- `Settings()` loads defaults without an API key; `repr(settings)` contains no key.
- Valid rule JSON (including the shorthand `{"field":"velocity_1h","op":">=","val":4,"action":"FLAG"}`) parses; invalid ones are rejected (unknown field, op `"contains"`, 4 clauses, `action:"BLOCK"`, out-of-bounds value, wrong type, extra keys, `==` misuse is allowed only on categorical/binary).
- All stubs import cleanly and expose the listed signatures.
- `streamlit run app.py` starts.

## 8. Testing Instructions
```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
streamlit run app.py   # confirm it loads, then stop
```
`tests/test_schemas.py` must cover: valid/invalid rules (≥8 cases above), shorthand normalisation, `AttackSpec` range ordering and bounds, categorical-op restriction, `extra="forbid"`. `tests/test_config.py`: defaults, env override, no secret leak in `repr`/`str`. Expected: all pass.

## 9. Deliverables
A runnable skeleton with frozen schemas, config, stub interfaces, README skeleton, license, and passing schema/config tests.

## 10. Handoff Instructions
Phase 2 implements `simulator.py`, `baseline.py`, `metrics.py`, `rule_engine.py` (+ `failure_analysis.py`) against these exact schemas. It must not alter `schemas.py` field names; additions require a documented, backward-compatible change.

## 11. Completion Report
Report: files created; files modified; tests executed (with the exact command); passed/failed counts; actual implementation status (what is stub vs real); unresolved issues; Python version used; Phase 2 readiness. Never claim tests passed without running them.

---

## Audited cross-phase decisions (binding for all six phases)
- **Timebox:** 120 minutes total (10/20/25/25/25/15). The PPT's three-hour feasibility statement is the presentation's earlier estimate; the two-hour plan is the user's current execution constraint. Defer noncritical extras rather than misrepresent completion.
- **Recall threshold:** `min_recall_gain_pp=5.0` is a configurable **MVP implementation choice**. Slide 7's `≥ +25% marginal recall` is an illustrative example with ambiguous units, **not** a mandatory gate threshold. Report measured target-attack gain in percentage points, and disclose the configured threshold.
- **One-shot sealed policy:** a final candidate receives one sealed evaluation. Never expose sealed rows to the model, dashboard, or retry logic. Fresh held-out seeds/datasets are required for new development or repeated public judging; repeated inspection of aggregate sealed outcomes can contaminate future tuning.
- **Gate access boundary:** the simulator necessarily creates the sealed frame; only the verification gate may **read/evaluate** it after generation. The pipeline passes it opaquely to the gate and must not compute or inspect sealed metrics itself.
- **Data model:** make `PipelineResult` an explicit dataclass in `pipeline.py` now, including `spec`, `rule`, `report`, `telemetry`, and **sample-only display evidence**; do not include sealed rows or raw validation data in UI-facing objects. Create a minimal callable orchestration skeleton now; Phase 5 completes it and Phase 6 hardens it.
- **Scope:** no deployment, live leaderboard, continuous attacks, screenshot intake, or external detector plugins unless all MVP tests pass and time remains. No hardcoded PPT metrics.
