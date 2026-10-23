# PHASE 5 — INTERACTIVE STREAMLIT DASHBOARD (25 minutes)

> Paste into Google Antigravity. Implement only this phase. Keep the UI practical, not elaborate.

## 1. Phase Objective
Build the judge-facing Streamlit dashboard in `app.py` (plus small helpers) that lets a judge enter a scenario, see the generated attack spec, the proposed rule, baseline vs patched metrics, verification checks and the ACCEPT/REJECT verdict — in Live or Offline Replay mode.

## 2. Existing Project Context
RedQueen ("Let the fraudster go first"): Gemma 4 proposes (attack specs, defensive rules); deterministic Python verifies (sample/validation/sealed splits, monotonic baseline-OR-rule detector, FPR and segment constraints). Replay mode requires no API and must be clearly labelled. Illustrative PPT numbers (38.2%, 86.4%, +48.2 pp, 0.8%) are **not** results: show only computed values.

## 3. Previous Phase Dependencies
Phases 1–4: `Settings`, schemas, `GemmaClient` + `probe_capabilities`, `attack_lab`, `defender_forge`, `replay.list_replay_scenarios/load_replay`, `generate_datasets`, `BaselineDetector`, `VerificationGate`, `SandboxState`, `VerificationReport`, `RunTelemetry`. If `pipeline.run_redqueen` is still a stub, implement a **minimal thin orchestration** in `pipeline.py` now (generate spec → datasets → baseline → evidence → rule → validation feedback → ≤1 retry on `fpr_exceeded`/`segment_violation`/`none` bucket → final sealed verdict → activate if accepted) and keep it compatible with Phase 6 hardening.

## 4. Exact Implementation Tasks
1. **Theme**: dark-blue cybersecurity look via `.streamlit/config.toml` (`base="dark"`, primary accent cyan/teal, background deep navy e.g. `#0A1628`, secondary `#10223D`, text light) and a small CSS block in `src/redqueen/ui_components.py`. Readable on a projector: large metrics, high contrast, no animations.
2. **Layout (single page)**:
   - Header: "RedQueen" + tagline + one-line principle "Gemma proposes. Python verifies." + mode badge.
   - Sidebar: Mode toggle (**Live (Gemma 4)** / **Offline Replay**), seed input (default from settings), model name (read-only), API status indicator (from cached `probe_capabilities`; never shows the key), thresholds display (FPR ceiling, min gain pp, segment budget), "Reset sandbox".
   - Main input: scenario text area (prefilled example "Burst of $450 gift card transfers from a newly created IP at 3:00 AM."), replay scenario selector (visible in replay mode), **Run RedQueen** button. Input limited to 600 chars with a visible counter.
   - Result sections (use `st.tabs` or ordered sections): ① Attack Specification (formatted JSON + readable summary) ② Baseline Failure Evidence (counts, a small sample table of missed fraud vs look-alikes — sample split only) ③ Proposed Defensive Rule (JSON + plain-English rendering such as "FLAG if velocity_1h ≥ 4 AND merchant_category == gift_card" + Gemma rationale labelled "Model rationale — not proof") ④ Verification Gate (check table with ✅/❌, observed vs threshold) ⑤ Verdict banner: green **ACCEPTED — ACTIVE IN SANDBOX** or red **REJECTED — reason** ⑥ Metrics & Telemetry.
3. **Metrics shown (all computed)**: baseline recall, patched recall, recall gain in **pp**, global FPR, legit flagged per 10,000, segment FPR table with the worst segment highlighted (bar chart via `st.bar_chart`, no extra deps), model latency, verification latency, attempts used, mode, model used. In replay mode show a persistent banner: "Offline replay — predefined scenario and rule proposal; verification below is computed live in Python. No Gemma call was made."
4. **Sandbox panel**: list active (accepted) rules in `st.session_state`, and a "Re-run baseline vs sandbox" compare to show the cumulative patched detector; rejected rules are listed separately as "Rejected (inactive)".
5. **Resilience**: wrap pipeline in try/except mapping typed errors to friendly messages: `MissingApiKeyError`/`GemmaApiError`/`GemmaOutputError` → "Live mode unavailable: <category>. Switch to Offline Replay" with a one-click button that switches mode (never auto-switch silently). Show spinners with stage names. Persist the last result in `st.session_state` so reruns don't recompute; cache dataset generation with `st.cache_data` keyed by `(spec json, seed)` for **sample-only presentation artifacts** (never cache sealed frames in UI code).
6. **Judge-safety**: sanitize/escape displayed model text (`st.text`/code blocks; no `unsafe_allow_html` with model output); never display raw prompts, keys, or sealed rows. Evidence tables use sample split only.
7. **Download**: "Download run report (JSON)" containing scenario, spec, rule, report, telemetry, mode, seed — no secrets.
8. **README** additions: run instructions, screenshots placeholder, demo script (3-minute judge flow).

## 5. Files to Create or Modify
`app.py`, `src/redqueen/ui_components.py` (new, helpers: banner, metric cards, check table, rule renderer), `.streamlit/config.toml`, `src/redqueen/pipeline.py` (minimal orchestration if not present), `tests/test_ui_components.py`, `tests/test_pipeline.py` (basic), `README.md`. Do not rename frozen modules.

## 6. Technical Constraints
- Streamlit only; add no new dependencies. Pure helper functions in `ui_components.py` must be unit-testable without Streamlit running (return strings/dataframes).
- Replay run must complete with zero network/keys; target end-to-end replay latency < 5 s at default sizes.
- The UI never touches the sealed DataFrame directly: only `VerificationReport` aggregates.
- Mode label comes from `RunTelemetry.mode`, not from the toggle alone.
- Handle empty/whitespace input; disable the Run button while running.

## 7. Acceptance Criteria
- `streamlit run app.py` loads with no key; replay run shows spec, rule, checks, metrics, verdict, all computed.
- Replay scenarios yield both an accepted and a rejected example in the UI (via selector).
- Live mode with no key shows the friendly fallback message and a "Switch to Offline Replay" action, not a stack trace.
- Verdict banner text exactly: `ACCEPTED — ACTIVE IN SANDBOX` or `REJECTED — <reason>`.
- Replay banner always visible in replay mode; no mention of illustrative PPT figures as results.
- Rejected rules never appear in the active sandbox list.
- Downloaded JSON has no secrets.

## 8. Testing Instructions
```
pytest -q tests/test_ui_components.py tests/test_pipeline.py
pytest -q
streamlit run app.py   # manual: replay accepted case, replay rejected case, live-without-key fallback, empty input, 601-char input
```
Optionally use `streamlit.testing.v1.AppTest` for a replay-mode smoke test if it works in the environment; report if skipped. Expected: tests pass; manual checks confirm each acceptance item (report what you actually observed).

## 9. Deliverables
A working, themed dashboard that a judge can operate end-to-end in replay mode and in live mode when a key is available.

## 10. Handoff Instructions
Phase 6 needs: stable `pipeline.run_redqueen` signature and `PipelineResult`, UI entry `app.py`, list of known UI issues, and any untested live-mode paths flagged.

## 11. Completion Report
Files created/modified; tests run + counts; manual checks performed (each with observed result); whether live mode was exercised; implementation status; unresolved issues; Phase 6 readiness. Never claim a manual check was done unless it was.

---

## Audited UI and orchestration constraints
- `pipeline.run_redqueen` is the **single orchestrator** for both CLI and UI. It must be completed here if still a stub; do not duplicate the flow in `app.py` or in the benchmark script. Phase 6 may only harden/refactor with regression tests.
- The dashboard must not receive or cache a sealed DataFrame. Avoid returning raw `datasets` in `PipelineResult`; show sample evidence and aggregate reports only.
- Preserve the distinction between **candidate-only** evaluation and **cumulative active sandbox** evaluation. A newly accepted rule is activated only after the gate passes cumulative checks. Display cumulative active-rule count honestly.
- The mode badge must reflect the actual run's telemetry, not just the sidebar choice. If live mode fails, show a user-controlled switch to replay; never silently substitute replay output.
- Streamlit `st.session_state` must retain accepted rules across reruns, but a new judge scenario must use a fresh run id and isolated evaluation. No repeated sealed testing within the same run.
- For a two-hour MVP, prioritize readable judge input, proposed rule, computed metrics, gate verdict and replay switch; optional styling refinements, report downloads and cumulative charts may be deferred with disclosure.
