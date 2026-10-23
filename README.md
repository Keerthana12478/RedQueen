# RedQueen ♛

> **Let the fraudster go first.**

RedQueen is an adversarial fraud-testing arena built for Hacktoberfest Hack Day
Chennai × CodeYGen 2026 (FinTech PS1).

> **Gemma proposes. Python verifies.**

---

## What It Does

A judge describes a fraud scenario in plain English.  RedQueen:

1. Uses **Gemma 4** (via Google Gemini API) to interpret the scenario and
   generate a typed attack specification.
2. Uses **deterministic Python** to synthesise 17 000 realistic synthetic
   transactions (sample / validation / sealed splits).
3. Runs a **rule-based baseline detector** and analyses its failures.
4. Asks **Gemma 4** to propose a declarative defense rule from the evidence.
5. **Python independently verifies** the rule against held-out data.
6. Only verified rules become active in the sandbox.
7. A **Streamlit dashboard** shows the full arena — attack spec, rule, metrics.

The model never grades its own rule.  Data is 100 % synthetic.
This is **not** a production fraud detector.

---

## Architecture

```
scenario (text)
    → attack_lab      [Gemma] AttackSpec
    → simulator       [Python] sample / validation / sealed DataFrames
    → baseline        [Python] BaselineDetector
    → failure_analysis[Python] Evidence (sample only)
    → defender_forge  [Gemma] DefenseRule
    → verification    [Python] ValidationFeedback → VerificationReport
    → pipeline        PipelineResult (no raw sealed rows)
    → app.py          Streamlit dashboard
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full contract,
split rules, invariant list, and module table.

---

## Setup

### Prerequisites

- Python 3.13+ (tested on 3.14)
- A Google Gemini API key with access to Gemma 4 models

### Install

```bash
git clone <repo>
cd RedQueen

# Create a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your-key-here
```

### Run tests

```bash
pytest -q
```

### Launch the dashboard

```bash
streamlit run app.py
```

---

## Run Modes

| Mode     | Description                                                    |
|----------|----------------------------------------------------------------|
| `live`   | Calls the Gemma 4 API for attack spec and rule generation      |
| `replay` | Loads pre-recorded fixtures from `data/replay/` (no API key)  |

Set `REDQUEEN_MODE=replay` in `.env` for offline / CI use.

---

## Python Version

Developed and tested on **Python 3.14.7**.
All dependencies support Python 3.11+; use the newest compatible version
available and record it here if different.

---

## Honest Limitations

- **Not a production fraud detector.** All data is 100 % synthetic.
  Do not deploy this to real financial systems.
- **Illustrative PPT numbers are not experimental results.**
  All metrics shown are computed from the synthetic simulator output at
  runtime; no hardcoded benchmark values are used.
- **Gemma proposes heuristics.** The model's rule suggestions are a starting
  point; Python verifies them rigorously, but the verification criteria are
  also configurable MVP choices, not validated industry standards.
- **One-shot sealed evaluation.** The sealed dataset is evaluated exactly once
  per rule candidate to avoid contamination.  Repeated public judging requires
  fresh held-out seeds.

---

## TODO — By Phase

| Phase | Status   | Deliverable                              |
|-------|----------|------------------------------------------|
| 1     | ✅ Done  | Setup, schemas, config, stubs, tests     |
| 2     | ⬜ Next  | Simulator, baseline, rule engine, metrics|
| 3     | ⬜       | Gemma client, attack_lab, defender_forge |
| 4     | ⬜       | Verification gate (validation + sealed)  |
| 5     | ⬜       | Streamlit dashboard, pipeline            |
| 6     | ⬜       | Integration, hardening, delivery         |

---

## License

Apache-2.0 — see [`LICENSE`](LICENSE).
