# RedQueen architecture and contracts

**Gemma proposes. Python verifies.**

The shared pipeline.run_redqueen function owns the eight-stage flow. The CLI and Streamlit
use the same orchestrator. Existing module names and required schema fields are preserved.

~~~text
Judge text → attack_lab → AttackSpec
                       ↓
                 SimulationBoundary
                 ├── sample → baseline + active rules → Evidence → defender_forge
                 ├── validation → VerificationGate.evaluate_validation → coarse feedback
                 └── sealed → VerificationGate.evaluate_final (once per run)
                                                              ↓
                                                     VerificationReport
                                                              ↓
                                              accepted → SandboxState.activate
                                                              ↓
                                       PipelineResult → Streamlit / benchmark
~~~

## Split capabilities

| Split | Default rows | Consumer | Model visibility |
|---|---:|---|---|
| sample | 2,000 | failure analysis | permitted features and aggregates only |
| validation | 5,000 | gate validation method | coarse buckets only, ≤2 evaluations |
| sealed | 10,000 | gate final method | never |

SimulationBoundary holds frames privately. Model/UI code receives Evidence and count
metadata, never a DataFrame. Validation receives only the validation capability. Final
receives the sealed capability without the pipeline inspecting its contents. Independent
reference frames are generated and consumed inside the gate's final method too.
The boundary protects application interfaces; it is not a Python process isolation mechanism.

## Proposal and retry contracts

Attack input is normalized and bounded to 600 characters. Scenario/evidence strings are
framed as untrusted data. AttackSpec and DefenseRule revalidate all permitted fields,
operators, categories and numeric bounds. Forge validates nested sample records and
numeric aggregate summaries before model access. Model output never becomes code.

Each generate_json invocation allows at most three actual API requests, including format
repair, model fallback and transient retry. Capability probes are explicit/cached and separate.
Unprobed function calling remains unknown. AttackSpec uses prompt JSON; a native schema
is used only when supported and suitable. Invalid model output is a typed error.

A run requests one initial proposal and at most one validation-feedback revision, only for
no gain, global FPR excess, or segment violation. The final method is called once after
all proposal work. No sealed result is ever sent to the proposer. API failure propagates;
replay requires a user-controlled mode switch. Replay spec and rule share an explicit preset.

## Gate and sandbox

The gate owns a fresh run id, a validation counter, and a consumed-final state. Finalization
is marked before evaluation, preventing repeated final checks even with a changed rule.
Invalid rules return a rejection without reading the sealed split.

Checks are validity, complexity, elementwise original/current flag preservation, marginal
target recall gain, cumulative global FPR, cumulative segment FPR, and regression on two
built-in reference attacks plus session-approved attacks. Thin segments are listed as
insufficient data. Missing target positives or legitimate evidence cannot pass.

Report baseline = detector before candidate (original baseline plus active accepted patches).
Report patched = that cumulative detector plus candidate. Additional aggregate fields preserve
original-baseline and candidate-only comparisons. Activation binds an accepted report to the
candidate fingerprint and exact preceding active-rule fingerprints; rejected/stale/reused
reports are rejected. Active-rule snapshots are deep copies. The sandbox is session memory.

## Backward-compatible schema additions

VerificationReport retains its original required fields and adds optional target recall/count,
original-baseline metrics, candidate-only metrics, segment summaries, run id, candidate hash
and active-rule hashes. RunTelemetry adds optional replay_scenario and replay_match fields.
PipelineResult adds scenario/seed/run id, coarse feedback, stage timing, step telemetry,
revision count and active-rule count. Its JSON export explicitly excludes Settings and raw data.

## Determinism and feasibility

Simulator split roots are seed, seed+1 and seed+2; independent child streams and stable
row/index ordering make repeated inputs deterministic. Merchant categories use fixed
proportions stratified across burst/ordinary traffic, apportioned by largest remainder and
seeded shuffling. This integration correction retains legitimate burst look-alikes without
consulting flags, evaluation metrics or split identity. Detector and budgets were unchanged.
A baseline above any budget cannot be repaired by adding flags and is rejected.

Gain is target recall difference *100 percentage points. Global FPR is FP/(FP+TN) on
legitimate rows and flags per 10k = FPR*10000. Default settings: minimum gain 5 pp, global
ceiling .015, segment budget .03, minimum segment count 50, maximum clauses 3, one revision.
These are project choices. Report metrics and verdict are deterministic; latency and run id vary.

## Modules

| Module | Responsibility |
|---|---|
| config, schemas | settings, secrets and typed contracts |
| simulator | deterministic synthetic transaction generation |
| baseline, rule_engine, metrics | fixed rules, safe comparisons, computed counts/rates |
| failure_analysis | sample-only evidence |
| gemma_client, attack_lab, defender_forge | bounded live proposals and input guards |
| replay | deterministic fixture matching and validation |
| verification | coarse validation, one-shot final checks, sandbox state |
| pipeline | single orchestrator and aggregate-only result |
| ui_components, app.py | safe rendering and session interaction |
| benchmarks/run_benchmark.py | headless runner through the same pipeline |

The one-shot registry is in memory per run, not persistent across processes. Deterministic
rehearsals intentionally reuse seeds; fresh held-out seeds are required after development
has learned from sealed results. All data is synthetic; this is not a production fraud detector.
