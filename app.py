"""Judge dashboard. The shared pipeline owns every evaluation."""
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import pandas as pd
import streamlit as st
from redqueen.config import Settings
from redqueen.gemma_client import GemmaApiError, GemmaClient, MissingApiKeyError
from redqueen.pipeline import PipelineError, run_redqueen
from redqueen.replay import list_replay_scenarios, load_replay
from redqueen.ui_components import REPLAY_BANNER, check_table, metric_table, mode_label, render_rule, verdict_banner
from redqueen.verification import SandboxState

st.set_page_config(page_title="RedQueen | Fraud Arena", page_icon="♛", layout="wide")
settings = Settings.from_env()
st.session_state.setdefault("sandbox", SandboxState())
st.session_state.setdefault("run_mode", "Offline Replay")
st.session_state.setdefault("scenario_text", load_replay("GiftCardNightBurst")["scenario_text"])


def switch_replay():
    st.session_state.run_mode = "Offline Replay"
    st.session_state.pop("live_error", None)


def set_preset():
    if st.session_state.preset != "Custom text (closest replay)":
        st.session_state.scenario_text = load_replay(st.session_state.preset)["scenario_text"]


def reset_sandbox():
    st.session_state.sandbox = SandboxState()
    st.session_state.pop("result", None)
    st.session_state.pop("live_error", None)


st.title("♛ RedQueen")
st.subheader("Let the fraudster go first.")
st.caption("Gemma proposes. Python verifies. | Synthetic fraud arena | Sandbox only")
with st.sidebar:
    st.header("Arena controls")
    requested = st.radio("Proposal mode", ["Offline Replay", "Live (Gemma)"], key="run_mode")
    seed = int(st.number_input("Deterministic seed", min_value=0, max_value=2147483647, value=settings.seed, step=1))
    st.caption("Configured model")
    st.code(settings.model, language=None)
    if requested == "Live (Gemma)":
        if not settings.api_key.get_secret_value().strip():
            st.warning("No GEMINI_API_KEY configured. Live mode unavailable.")
            st.button("Switch to Offline Replay", on_click=switch_replay, key="missing_key_replay")
        else:
            st.caption("API key configured; connectivity checked on request.")
            if st.button("Check live API"):
                with st.spinner("Checking live Gemma capabilities…"):
                    st.session_state.api_probe = GemmaClient(settings).probe_capabilities()
            probe = st.session_state.get("api_probe")
            if probe is not None:
                if probe.model_available and probe.auth_ok:
                    st.success(f"API available: {probe.model_used}")
                else:
                    st.warning(f"Live API unavailable: {probe.error_category}")
                st.caption(f"Structured output: {probe.structured_output_ok}; function calling: {probe.function_calling_ok}")
    else:
        st.success("Offline ready • no network required")
    st.divider()
    st.caption("Configurable project thresholds")
    st.write(f"Global FPR ≤ {settings.global_fpr_ceiling:.1%}")
    st.write(f"Target recall gain ≥ {settings.min_recall_gain_pp:g} pp")
    st.write(f"Segment FPR ≤ {settings.segment_fpr_budget:.1%} (≥{settings.min_segment_legit_count} legit rows)")
    st.button("Reset sandbox", on_click=reset_sandbox)
mode = "replay" if requested=="Offline Replay" else "live"
if mode=="replay":
    st.info(REPLAY_BANNER)
    names = ["GiftCardNightBurst"] + [n for n in list_replay_scenarios() if n!="GiftCardNightBurst"]
    st.selectbox("Scenario preset", names+["Custom text (closest replay)"], key="preset", on_change=set_preset)
else:
    st.info("LIVE GEMMA selected • proposals require Gemini API connectivity. Python independently verifies them.")
scenario = st.text_area("Judge scenario", key="scenario_text", height=110, max_chars=600)
st.caption(f"{len(scenario)}/600 characters • Editing a replay preset uses the closest matching fixture.")
progress = st.empty()
if st.button("Run RedQueen", type="primary", disabled=not scenario.strip()):
    chosen = scenario
    if mode=="replay":
        preset = st.session_state.get("preset")
        if preset and preset!="Custom text (closest replay)" and scenario==load_replay(preset)["scenario_text"]:
            chosen = preset
    try:
        with st.spinner("Running the fraud arena…"):
            result = run_redqueen(chosen, settings.model_copy(update={"seed":seed}), mode,
                sandbox=st.session_state.sandbox, on_stage=progress.info)
        st.session_state.result = result
        st.session_state.pop("live_error", None)
    except (MissingApiKeyError, GemmaApiError) as error:
        category = getattr(error,"category","missing_key")
        st.session_state.live_error = f"Live mode unavailable: {category}. Switch to Offline Replay."
    except ValueError as error:
        st.error(str(error))
    except PipelineError as error:
        st.error(f"{error}. Reset the sandbox or use another preset.")
    finally:
        progress.empty()
if st.session_state.get("live_error"):
    st.error(st.session_state.live_error)
    st.button("Switch to Offline Replay", on_click=switch_replay, key="error_replay")
result = st.session_state.get("result")
if result is not None:
    report = result.report
    st.divider()
    st.subheader("Last completed run • " + mode_label(result.telemetry.mode))
    st.caption(f"Seed {result.seed} | Run {result.run_id[:12]} | API requests {result.telemetry.attempts} | Validation revisions {result.validation_retries}")
    if result.telemetry.mode=="replay":
        st.info(REPLAY_BANNER)
        match = "Closest replay scenario" if result.telemetry.replay_match=="closest" else "Selected replay scenario"
        st.write(f"{match}: {result.telemetry.replay_scenario}")
    if report.verdict=="ACCEPTED":
        st.success(verdict_banner(report))
    else:
        st.error(verdict_banner(report))
        st.caption("Rejected candidate metrics below describe an inactive proposal.")
    columns = st.columns(5)
    for column, label, value in zip(columns, ["Target recall before","Target recall after candidate","Target gain","Candidate cumulative FPR","Legit flags / 10,000"],
        [f"{report.target_baseline_recall:.1%}",f"{report.target_patched_recall:.1%}",f"{report.recall_gain_pp:+.2f} pp",f"{report.patched.fpr:.2%}",f"{report.legit_flagged_per_10k:.1f}"]):
        column.metric(label,value)
    attack, evidence, forge, gate, metrics = st.tabs(["Attack Lab", "Failure Evidence", "Defender Forge", "Verification Gate", "Metrics & Telemetry"])
    with attack:
        st.text(result.spec.description)
        st.json(result.spec.model_dump(mode="json"))
    with evidence:
        st.caption("Sample split only. No validation or sealed rows are displayed.")
        summary = result.evidence.summary_stats
        st.write(f"Sample rows: {summary['n_rows']} | Target fraud: {summary['n_target_fraud']} | Missed target fraud: {summary['n_missed_target']}")
        st.write("Missed fraud • permitted features")
        st.dataframe(pd.DataFrame(result.evidence.missed_fraud), hide_index=True, width="stretch")
        st.write("Look-alike legitimate transactions • permitted features")
        st.dataframe(pd.DataFrame(result.evidence.lookalike_legit), hide_index=True, width="stretch")
    with forge:
        st.code(render_rule(result.rule), language=None)
        st.json(result.rule.model_dump(mode="json"))
        st.caption("Proposal rationale — not proof" if result.telemetry.mode=="replay" else "Model rationale — not proof")
        st.text(result.rule.rationale)
    with gate:
        st.dataframe(check_table(report), hide_index=True, width="stretch")
        st.caption("Coarse validation feedback; only the final candidate was evaluated on sealed data.")
        st.json([f.model_dump() for f in result.validation_feedback])
        segments = pd.DataFrame(report.segment_results)
        if not segments.empty:
            st.write("Segment FPR • worst first; thin segments marked insufficient data")
            st.dataframe(segments.sort_values("fpr", ascending=False), hide_index=True, width="stretch")
            eligible = segments[segments.status!="insufficient data"].copy()
            eligible["segment_value"] = eligible.segment+"="+eligible.value.astype(str)
            st.bar_chart(eligible.set_index("segment_value")[["fpr","budget"]])
    with metrics:
        st.caption("Before candidate includes accepted rules. Candidate-only and cumulative results are distinguished below.")
        st.dataframe(metric_table(report), hide_index=True, width="stretch")
        st.write(f"Mode: {mode_label(result.telemetry.mode)} | Model used: {result.telemetry.model_used or 'None (replay)'}")
        st.write(f"Model latency: {result.telemetry.model_latency_ms:.0f} ms" if result.telemetry.model_latency_ms is not None else "Model latency: N/A (no API calls)")
        st.write(f"Final verification: {report.latency_ms:.0f} ms | API requests: {result.telemetry.attempts}")
        st.json(result.stage_timings_ms)
    st.download_button("Download run report (JSON)", json.dumps(result.to_dict(), indent=2), file_name=f"redqueen-{result.run_id[:12]}.json", mime="application/json")
st.divider()
st.subheader(f"Sandbox • {len(st.session_state.sandbox.active_rules)} active rules")
st.caption("Session memory only. New runs verify cumulative effects; rejected rules stay inactive.")
for index, rule in enumerate(st.session_state.sandbox.active_rules, start=1):
    st.code(f"{index}. {render_rule(rule)}", language=None)
rejected = [entry for entry in st.session_state.sandbox.audit if entry["verdict"]=="REJECTED"]
if rejected:
    with st.expander(f"Rejected (inactive) • {len(rejected)}"):
        for entry in rejected:
            st.text(entry["run_id"][:12]+": "+entry["reason"])
