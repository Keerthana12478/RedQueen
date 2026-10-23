# RedQueen ♛ — Let the Fraudster Go First

**Patch a detector without breaking legitimate users.**

RedQueen is a synthetic adversarial fraud arena for Hacktoberfest Hack Day Chennai ×
CodeYGen 2026 (FinTech PS1). A judge supplies a scenario; Gemma proposes typed attack
specifications and declarative rules; independent Python accepts or rejects each patch.
Only accepted rules enter an in-memory sandbox. **Gemma proposes. Python verifies.**

This prototype is ready for an **offline deterministic replay demo**. Live Gemini API
connectivity and a small structured-output probe passed; the typed Attack Lab smoke
request returned HTTP 504 timeout. A complete real-live run is **not verified**.
Replay is explicitly labelled and uses predefined proposals with freshly computed metrics.

## Quick start (existing environment)

From the repository root in PowerShell:

~~~powershell
.venv\Scripts\python.exe -m streamlit run app.py
~~~

Open the local URL printed by Streamlit, normally http://localhost:8501.
The dashboard starts in **Offline Replay** and makes no API calls on startup.
Choose seed **1337**, preset **GiftCardNightBurst**, and click **Run RedQueen**.
No API key is needed for replay. Accepted rules persist across reruns; **Reset sandbox**
clears the session. All displayed numbers are calculated from synthetic transactions.

## Setup in a fresh environment

Tested on Python **3.14.7** with the dependencies in requirements.txt.
Creating/installing into a fresh environment was not performed during delivery because
installation requires user permission; the existing environment passes pip check.

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
~~~

On macOS/Linux substitute .venv/bin/python. Activation is optional with these commands.
For live mode, copy .env.example to .env and set GEMINI_API_KEY locally. Never commit .env.
Use the dashboard's explicit Live (Gemma) option or --mode live in the benchmark.
REDQUEEN_MODEL and REDQUEEN_FALLBACK_MODEL select models available to your account;
the configured defaults are gemma-4-31b-it and gemma-4-26b-a4b-it.
Offline deterministic replay works locally; live Gemma requires Gemini API connectivity.

## Eight-stage workflow

1. Sanitize the judge scenario (nonempty, at most 600 characters), then create a typed AttackSpec with live Gemma or a selected replay fixture.
2. Generate independent sample (2,000), validation (5,000), and sealed (10,000) transaction splits.
3. Run the fixed baseline plus existing accepted rules; derive permitted sample-only failure evidence.
4. Propose a DefenseRule: one to three AND clauses, allowed fields/comparisons only, action FLAG.
5. Evaluate validation data in Python and return coarse gain/FPR/segment feedback only.
6. Optionally request **one** revision for no gain or an FPR/segment violation, then validate it once.
7. Evaluate **only the final candidate** on the sealed split exactly once for this run; check independent reference attacks too.
8. Activate only accepted candidates in the session sandbox and return aggregate reports and sample evidence.

~~~text
scenario → Attack Lab [Gemma / explicit replay]
         → simulator [seeded Python]
         → baseline + sample failure evidence
         → Defender Forge [Gemma / same replay fixture]
         → validation [coarse feedback; ≤1 revision]
         → sealed verification [Python; once per run]
         → ACCEPTED: sandbox activation / REJECTED: inactive
         → Streamlit dashboard + headless benchmark
~~~

The CLI and dashboard both call pipeline.run_redqueen; they do not duplicate evaluation.
See [architecture and boundaries](docs/ARCHITECTURE.md).

## What the verification gate checks

All checks must pass: schema validity; rule complexity; elementwise monotonicity;
target recall gain; global FPR; merchant/channel/account-age segment FPR;
and regression protection on two built-in reference attacks plus previously approved scenarios.
The patched detector is always the baseline OR accepted rules OR candidate.
A rejected candidate never changes the active detector.

Target-attack recall is TP/(TP+FN) on fraud with attack_name equal to the current attack name.
**Gain in percentage points** is (patched target recall - current sandbox target recall)*100;
it is not relative improvement. Overall fraud recall includes background fraud and is shown
separately. Global FPR is FP/(FP+TN) over legitimate rows; legitimate flags per 10,000 = FPR*10000.
The report distinguishes original baseline, current cumulative detector, candidate-only plus
original baseline, and cumulative detector plus candidate. Main gain is marginal to active rules.

| Setting | Default |
|---|---:|
| Minimum target recall gain | 5.0 pp |
| Global FPR ceiling | 1.5% |
| Segment FPR budget | 3.0% |
| Minimum legitimate rows per tested segment | 50 |
| Maximum clauses per rule | 3 |
| Maximum validation revisions | 1 |

These are **configurable project design values, not industry standards**. Thin segments are
listed as insufficient data; zero target positives or zero legitimate evidence cannot pass.
Failure priority is validity → complexity → monotonicity → global FPR → segment FPR →
regression → target gain. Every check records its observed value, threshold, and explanation.
An already over-budget baseline cannot be repaired by an OR-only patch and is rejected.

## Computed replay results

The following table was generated by the benchmark on seed 1337, using an isolated empty
sandbox for each scenario. These are measured synthetic results, not targets or claims
about real fraud detection. Full aggregate reports: [benchmark.json](docs/benchmark.json).

| Scenario | Target recall before → after | Gain (pp) | Global FPR | Verdict |
|---|---:|---:|---:|---|
| CryptoNewAccountBurst | 0.00% → 84.94% | +84.94 | 0.98% | REJECTED (segment_fpr) |
| GiftCardNightBurst | 26.40% → 80.08% | +53.68 | 0.71% | ACCEPTED |
| HighAmountGeoMismatch | 60.71% → 67.92% | +7.21 | 3.79% | REJECTED (global_fpr) |

The crypto rule demonstrates rejection despite strong recall improvement: legitimate
crypto customers violate the segment budget even while global FPR remains below its ceiling.
The geo rule demonstrates rejection on global FPR. Fixtures contain proposals, not stored verdicts.

### Simulator assumptions and integration correction

Legitimate amounts are lognormal around a median of $40; hourly activity is Poisson(0.4)
with a 1.5% burst mixture spanning 4–16 transactions. Young accounts, new devices, night
purchases, geographic mismatches and gift-card/crypto activity occur among legitimate users.
An evasion fraction of target fraud has all features replaced by legitimate-looking draws.
Generic background fraud is separate from target-attack recall.

During gate integration, independent random merchant draws made a rare crypto segment's
baseline alone exceed its budget at the default seed. The generator now uses fixed category
proportions stratified across burst and ordinary traffic, largest-remainder counts and seeded
shuffling. This reduces rare-segment sampling variance and retains burst look-alikes.
It does not inspect detector flags, labels, evaluation metrics or split identity. The baseline,
thresholds and original distribution tests remain unchanged. This synthetic design assumption
must not be mistaken for evidence about real merchant populations.

Splits use roots seed, seed+1 and seed+2 with separate child streams for legitimate/fraud
traffic. Runs with the same inputs reproduce values, dtypes, index and row order.

## Tests, benchmark and live smoke

~~~powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe benchmarks/run_benchmark.py --mode replay --seed 1337 --scenarios all --json docs/benchmark.json
.venv\Scripts\python.exe -u -X utf8 scripts/smoke_gemma.py
~~~

The test suite uses mocked API clients, real simulation/verifiers, Streamlit AppTest,
and an HTTP startup test. It makes no live Gemma requests. The smoke script is the explicit
live check; no key produces exit 2 and a replay recommendation. API failures never cause
a silent replay substitution. Each proposal allows at most three API requests, including
format repair, transport retry and model fallback. The single validation revision is separate;
request counts and successful proposal latencies include those retries.

The delivered real-live probe reported auth/model/structured output PASS, function calling
unknown (untested), about 16.8 seconds. The typed Attack Lab request then failed with
HTTP 504 timeout (smoke exit 1). AttackSpec uses schema-in-prompt because its tuple schema
is unsuitable for the native path; all responses are still validated with Pydantic.
No real-live Defender Forge or complete live pipeline success is claimed.

## Three-minute judge walkthrough

1. **0:00–0:30:** Open the dashboard in Offline Replay, seed 1337. Explain the scenario and the visible replay banner.
2. **0:30–1:20:** Run GiftCardNightBurst. Open Attack Lab and sample failure evidence; show the declarative rule in Defender Forge.
3. **1:20–2:00:** Show the computed recall gain, FPR, seven gate checks and ACCEPTED — ACTIVE IN SANDBOX. Point out the active-rule count.
4. **2:00–2:40:** Choose HighAmountGeoMismatch and run. Show REJECTED on global FPR; the accepted-rule count stays unchanged. CryptoNewAccountBurst is the alternate segment-budget rejection demo.
5. **2:40–3:00:** Show Live (Gemma), explain connectivity needs and the honest timeout status. If live fails, click Switch to Offline Replay. Download the run report if useful.

Reset the sandbox before repeating the accepted case. Reproposing an already active rule
should fail marginal-gain checks. Switching the sidebar never relabels an earlier result.

## Security and limits

- Model proposals are declarative data; model-generated code, commands, paths and URLs are never executed.
- Gemma receives permitted sample features and aggregates only, plus coarse validation feedback on one optional revision. It never receives sealed data or final sealed results.
- UI text/code/JSON rendering escapes model text. Reports contain no Settings object, API key, or raw held-out frames.
- .env and Streamlit secrets are ignored; only placeholder .env.example is tracked. A quick reachable-history Google-key pattern scan found no matches.
- This is a synthetic single-attack sandbox with a simple rule baseline and restricted rule language, not a production financial service.
- One-shot protection is per gate/run in application memory. Repeated deterministic demo runs reuse the same seed for reproducibility; after inspecting sealed results for development, use fresh held-out seeds. There is no durable cross-process holdout registry or isolation against arbitrary Python introspection.
- Validation and sealed splits can reject candidates, including at other seeds. Acceptance of the positive fixture is not universal.
- Existing dependency versions pass pip check. Google SDK and Streamlit/pandas emit upstream deprecation warnings.
- Deployment, leaderboards, fresh-environment reinstall, screenshots, elaborate styling and a release tag were deferred. The functional Streamlit theme, report download, and cumulative checks are implemented.

## RedQueen Gym and delivery

RedQueen Gym is the reusable experiment harness: typed schemas, seeded simulator, fixed
baseline, restricted rule engine, independent verifier, benchmark runner, bounded Gemma
adapter, dashboard and regression tests. Its task is: **Patch a detector without breaking
legitimate users.**

Phases 1–2 are preserved. Phases 3–6 are implemented and tested in replay, with mocked-live
end-to-end coverage. Real-live generation remains blocked by the measured API timeout.
See [delivery evidence and rehearsal](docs/DELIVERY.md) and [phase commit plan](docs/COMMIT_PLAN.md).
No deployment or public-repository status is claimed. The four phase commits were authorized; pushing requires separate approval.

Apache-2.0 — see [LICENSE](LICENSE).
