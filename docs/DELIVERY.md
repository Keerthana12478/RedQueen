# RedQueen delivery record — 2026-10-23

The prototype is ready for an offline judge demo. Live connectivity was verified, but typed
live generation failed with HTTP 504; a full real-live run is not claimed.

## Phase completion and exact regression evidence

All suites used the existing .venv, without installing packages. Full-suite command:

~~~powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider
~~~

| Checkpoint | Observed result |
|---|---|
| Initial existing suite (python -m pytest -q) | 248 passed, 2 warnings in 9.26s |
| Phase 3 complete | 253 passed, 1 warning in 8.05s |
| Phase 4 complete | 276 passed, 1 warning in 21.28s |
| Phase 5 complete | 285 passed, 5 warnings in 33.09s |
| Phase 6 final | **308 passed, 6 warnings in 37.70s** |
| pip check | No broken requirements found |
| git diff --check | Exit 0; no whitespace errors |

The final six warnings come from Streamlit's pandas reset_index usage (five occurrences)
and Google SDK typing (one). No tests were skipped or marked expected-failure. The test
cache plugin was disabled because the initial environment produced a cache-path warning;
test collection and assertions were unchanged.

The first gate run correctly rejected every preset because the baseline alone exceeded a
rare merchant segment's budget. The documented simulator sampling correction retained the
baseline and thresholds and passed the original distribution tests. The old Phase 2
"pipeline remains stub" assertion was replaced with completed-pipeline and sample-boundary
assertions. A new overlength UI test initially expected an error, but direct inspection showed
Streamlit enforces max_chars by truncating to 600; the test now asserts that actual contract.
API, verifier and security behavior are tested without real network calls.

## Rehearsal evidence

| Item | Outcome actually observed |
|---|---|
| Replay accepted | GiftCardNightBurst ACCEPTED on real computed metrics, seed 1337 |
| Replay global rejection | HighAmountGeoMismatch REJECTED on global_fpr |
| Replay segment rejection | CryptoNewAccountBurst REJECTED on segment_fpr despite compliant global FPR |
| Determinism | Every preset compared across independent runs with identical metrics/spec/rule/evidence |
| Dashboard accepted/rejected | Streamlit AppTest clicked presets/Run; accepted rules retained, rejected rules inactive |
| Rerun persistence | Same last-run id retained; sealed evaluation not repeated on a UI rerun |
| Missing live key | Friendly message and explicit Switch to Offline Replay; no silent fallback |
| Empty / 601-character input | Empty Run disabled; UI enforced 600 chars; backend independently rejects >600 |
| Injection-style input | Mocked-live pipeline treated scenario as data; credential sentinel absent from prompts/reports |
| One revision and one final | Spies verified two validation calls at most, one final on the revised candidate only |
| Cumulative sandbox | Two distinct rules accepted with mocked live; a later rejection left both active |
| Streamlit startup | Documented command served /_stcore/health with 200 + ok and / with HTTP 200 |
| Benchmark | All presets executed through shared pipeline; full computed reports saved in benchmark.json |
| Real Gemma probe | auth/model/structured-output passed; function calling unknown; observed latency 16,798 ms |
| Real typed Attack Lab | Failed with GemmaApiError timeout, HTTP 504; smoke exit 1 |
| Real Defender Forge / full live run | Not completed because the attack generation request failed |
| No-key smoke | Exit 2 with clear replay recommendation, verified in regression test |
| Fresh environment install | Not run; no dependency-install permission requested or assumed |
| Deployment / release tag | Not performed; deferred as optional |

The final recorded replay gate latency was at most approximately 217 ms across the three
benchmark cases. The replay pipeline test also asserts completion under five seconds.
All numbers are measured synthetic results; consult benchmark.json for exact aggregate counts.

## Demo commands and fallback

~~~powershell
cd C:\Users\dhrit\Downloads\RedQueen
.venv\Scripts\python.exe -m streamlit run app.py
.venv\Scripts\python.exe benchmarks/run_benchmark.py --mode replay --seed 1337 --scenarios all
.venv\Scripts\python.exe -u -X utf8 scripts/smoke_gemma.py
~~~

For judging: Offline Replay → seed 1337 → GiftCardNightBurst → Run RedQueen → show the rule,
computed metrics, checks and active sandbox. Then HighAmountGeoMismatch → Run → show
rejection and unchanged active-rule count. Use CryptoNewAccountBurst to show segment harm.
Reset sandbox before repeating the positive case. README contains the three-minute script.

If venue networking fails, select Offline Replay explicitly or click the provided switch
button. Replay works without a key or network and is never labelled LIVE GEMMA.
Do not spend judging time waiting for live generation if the API continues timing out.

## Security, Git and remaining limitations

.env and .streamlit/secrets.toml are ignored and untracked; only placeholder .env.example is
tracked. A quick reachable Git history scan found zero Google API-key-shaped strings.
No model output is executed. Sealed rows/results never enter model prompts. Reports and UI
contain only permitted sample evidence and aggregate held-out results.

Existing changes are preserved, including the original staged/unstaged Phase 3 work. The
historical phase2_proposed_changes.txt remains unchanged and is included in Phase 6 at the
user's request to commit all project changes. Four separate phase content checkpoints and
descriptive commit messages are prepared, and the user authorized their commits followed by
launching the dashboard. No push, credential change or force push is requested or planned.

Remaining blocker: real typed Gemma generation returned HTTP 504. Offline demo has no
known blocker. Fresh-install verification was deferred pending dependency-install approval.
Future work includes fresh holdout seeds after development, durable run tracking, broader
realistic population validation, and live transport/latency investigation. All data remains
synthetic; the simple baseline and restricted rules are not a production financial service.
