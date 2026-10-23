from pathlib import Path
from redqueen.config import Settings
from redqueen.pipeline import run_redqueen
from redqueen.ui_components import check_table, metric_table, mode_label, render_rule, verdict_banner


def test_display_helpers_use_actual_report():
    result=run_redqueen("GiftCardNightBurst", Settings(), "replay")
    assert verdict_banner(result.report)=="ACCEPTED — ACTIVE IN SANDBOX"
    assert render_rule(result.rule).startswith("FLAG if")
    assert "AND" in render_rule(result.rule)
    assert len(check_table(result.report))==7
    assert len(metric_table(result.report))==4
    assert mode_label(result.telemetry.mode)=="OFFLINE REPLAY"
    assert mode_label("live")=="LIVE GEMMA"


def test_dashboard_replay_accept_reject_and_rerun(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("GEMINI_API_KEY", "")
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    assert not app.exception
    next(b for b in app.button if b.label=="Run RedQueen").click().run()
    assert not app.exception
    assert any(s.value=="ACCEPTED — ACTIVE IN SANDBOX" for s in app.success)
    assert len(app.session_state.sandbox.active_rules)==1
    run_id=app.session_state.result.run_id
    app.run()
    assert app.session_state.result.run_id==run_id
    app.selectbox(key="preset").select("HighAmountGeoMismatch").run()
    next(b for b in app.button if b.label=="Run RedQueen").click().run()
    assert not app.exception
    assert any(e.value.startswith("REJECTED — global_fpr") for e in app.error)
    assert len(app.session_state.sandbox.active_rules)==1
    assert any("Offline replay" in i.value for i in app.info)


def test_dashboard_no_key_explicit_switch_and_empty_input(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("GEMINI_API_KEY", "")
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    app.radio(key="run_mode").set_value("Live (Gemma)").run()
    next(b for b in app.button if b.label=="Run RedQueen").click().run()
    assert not app.exception
    assert any("missing_key" in e.value for e in app.error)
    app.button(key="error_replay").click().run()
    assert app.radio(key="run_mode").value=="Offline Replay"
    app.text_area(key="scenario_text").set_value("   ").run()
    assert next(b for b in app.button if b.label=="Run RedQueen").disabled
