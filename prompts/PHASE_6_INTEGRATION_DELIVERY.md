# PHASE 6 — INTEGRATION, TESTING & DELIVERY (15 minutes)

> Paste into Google Antigravity. Implement only this phase. Prioritise a working end-to-end MVP over extras.

## 1. Phase Objective
Harden and finish the end-to-end pipeline, run the full test suite, validate the judge demo flow in both modes, complete the README/LICENSE, and prepare the repo for delivery (optionally deployment).

## 2. Existing Project Context
RedQueen — "Let the fraudster go first." Gemma 4 (Gemini API) proposes attack specs and defensive rules; deterministic Python (simulator, baseline, restricted rule engine, verification gate) verifies on separate sample/validation/sealed splits; only ACCEPTED rules are active in the sandbox. **Gemma proposes. Python verifies.** Live mode uses real Gemma calls; Offline Replay uses predefined proposals with computed verification and is always labelled. Synthetic data only; not a production fraud system. Apache-2.0.

## 3. Previous Phase Dependencies
Everything from Phases 1–5 as named: `src/redqueen/*`, `app.py`, `benchmarks/run_benchmark.py`, `scripts/smoke_gemma.py`, `data/replay/*.json`, `tests/*`, `README.md`, `docs/ARCHITECTURE.md`.

## 4. Exact Implementation Tasks
1. **Pipeline hardening** (`pipeline.py::run_redqueen`): stages with per-stage timing and typed errors; flow = validate input → attack spec → datasets → baseline → evidence (sample only) → rule proposal → validation feedback → at most **one** retry (only when feedback shows `none` bucket, `fpr_exceeded` or `segment_violation`) → sealed final evaluation (once on the final candidate) → sandbox activation only if ACCEPTED. Ensure the retry's sealed evaluation happens only for the final candidate, never for the discarded one.
2. **End-to-end integration tests** (`tests/test_e2e_replay.py`): run every replay scenario through `run_redqueen(mode="replay")` with no network/key; assert a mix of verdicts, computed metrics are floats within [0,1], gains in pp match `(patched - baseline)*100`, rejected rules not active, replay label present, determinism across two runs with the same seed. **Mocked-live** e2e (`tests/test_e2e_live_mock.py`) using a fake client: valid output path, invalid-then-valid path, API failure path surfacing a typed error.
3. **Security/contract regression tests** (`tests/test_contracts.py`): grep-style assertions that `attack_lab.py`/`defender_forge.py`/`gemma_client.py` do not reference sealed/validation frames; no `eval(`/`exec(`/`subprocess`/`os.system` in `src/`; `.env` is git-ignored; `repr(Settings())` leaks nothing; no module contains hardcoded PPT metrics (`86.4`, `48.2`, `38.2` as result literals — allow only in README under a clearly labelled "illustrative" note).
4. **Full suite + coverage of behaviour**: run `pytest -q`; fix defects found (in-scope bugs only). Do not weaken tests to pass.
5. **Demo rehearsal checklist** (execute and record actual outcomes): (a) replay accepted case, (b) replay rejected case, (c) live mode with a key if available (otherwise record "not run — no key"), (d) live-without-key fallback to replay, (e) injection-style scenario text, (f) benchmark script, (g) fresh venv install from `requirements.txt` using the README steps verbatim.
6. **README final**: what RedQueen is/is not, architecture diagram (ASCII), the eight-stage workflow, metric definitions (pp vs relative), thresholds (configurable design values, not industry standards), Live vs Replay explanation (no claim that offline mode is live AI), setup/run/test/benchmark commands, 3-minute judge demo script, limitations (synthetic data, simple baseline, restricted rule language, single-attack scope, sealed set reuse caveat), security notes (no key in repo), license, "RedQueen Gym" description (typed schemas, simulator, baseline, verifier, benchmark, adapter, dashboard, tests, seeds). The benchmark task statement: **"Patch a detector without breaking legitimate users."** Do not claim the repo is public unless verified.
7. **Repo hygiene**: Apache-2.0 `LICENSE` present; `.env.example` complete; no secrets in git history (`git log -p` quick scan for the key pattern if a key was used locally); small conventional commits; tag `v0.1.0-hackathon`.
8. **Optional (only if time remains, after everything above passes)**: DigitalOcean App Platform deployment notes (`Procfile`/run command `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`, env var `GEMINI_API_KEY` set as a secret, default `REDQUEEN_MODE=replay`). Do not claim deployment unless it was performed and URL-tested.

## 5. Files to Create or Modify
`src/redqueen/pipeline.py` (harden), `tests/test_e2e_replay.py`, `tests/test_e2e_live_mock.py`, `tests/test_contracts.py`, `README.md` (final), `docs/ARCHITECTURE.md` (final), optional `docs/DEPLOY.md`. Bug-fix edits to earlier modules are allowed only to fix failing behaviour; list each in the report.

## 6. Technical Constraints
No new dependencies; no refactors beyond fixes; no feature additions beyond the plan; time-box: if something is failing and not demo-critical, document it under "Known issues" instead of expanding scope. Do not print or store API keys. Never describe replay results as live Gemma output.

## 7. Acceptance Criteria
- `pytest -q` passes fully (or failures are listed honestly with causes).
- Fresh-venv install and `streamlit run app.py` work using README steps.
- Replay e2e works offline with accepted and rejected outcomes computed from data.
- Live mode works when a key is present, else falls back gracefully with a user-triggered switch.
- Sealed split evaluated once per final candidate (test proves it); at most one retry.
- README claims match actual behaviour; limitations stated.

## 8. Testing Instructions
```
python -m venv .venv
# Activate: Unix: source .venv/bin/activate | Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
python benchmarks/run_benchmark.py --mode replay --seed 1337 --scenarios all
python scripts/smoke_gemma.py          # only meaningful with a key; report actual output or "no key"
streamlit run app.py                   # run the rehearsal checklist
```
Expected: green tests, benchmark table with computed mixed verdicts, dashboard flows as specified. Edge cases: no network, invalid key, rate limit, malformed model JSON, empty input, double-click on Run.

## 9. Deliverables
A demo-ready repository: working dashboard in both modes, verified pipeline, benchmark script, full tests, final README and license, and a recorded rehearsal result.

## 10. Handoff Instructions
Provide a final `DELIVERY.md` section inside README (or `docs/DELIVERY.md`): exact demo commands, recommended judge scenarios, known issues, fallback procedure if the venue network fails (use Replay), and what remains for post-hackathon work.

## 11. Completion Report
Report: files created; files modified (including bug fixes in earlier modules); tests executed with exact commands and pass/fail counts; rehearsal checklist results (each item: done/not run + observed outcome); actual implementation status per feature; unresolved issues; whether live Gemma and deployment were actually exercised; delivery readiness. Never claim tests passed or features worked without having executed them.

---

## Audited delivery gates and prioritization
- **Mandatory within 15 minutes:** `pytest -q`, offline benchmark, dashboard replay ACCEPT and REJECT, live smoke test **only if a key is already available**, README truthfulness, `.env` exclusion, and exact run commands. Fresh-environment reinstall, detailed security scan, tagging, and DigitalOcean are stretch tasks; report skipped items rather than claiming completion.
- Ensure Phase 4's gate owns all sealed evaluations. The CLI, UI and pipeline may receive aggregate reports only; no additional sealed inspection or re-evaluation in Phase 6.
- Verify actual end-to-end runtime and report if 120-minute target is missed. A project can be demo-ready in replay mode while live Gemma remains unverified; do not call that 'fully live-tested'.
- Add a cross-phase contract test that asserts `PipelineResult` exposes no sealed/validation DataFrames and that only accepted rules enter sandbox state.
- The PPT still contains an outdated 'zero-dependency local fallback' line on slide 8. Documentation must state **offline deterministic replay works locally; live Gemma requires Gemini API connectivity**.
