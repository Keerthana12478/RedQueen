"""Security boundaries are structural and behavioral; no live network calls."""
import ast
from dataclasses import fields
import inspect
import json
from pathlib import Path
import re
import subprocess
import pytest
from pydantic import SecretStr
from redqueen.config import Settings
from redqueen.pipeline import run_redqueen

ROOT=Path(__file__).resolve().parents[1]


def test_model_modules_have_no_heldout_frame_access():
    for name in ["attack_lab","defender_forge","gemma_client"]:
        text=(ROOT/"src"/"redqueen"/(name+".py")).read_text(encoding="utf-8")
        assert not re.search(r'datasets\s*\[\s*[\"\'](?:sealed|validation)[\"\']',text)
        assert "sealed_df" not in text and "validation_df" not in text
        assert "redqueen.verification" not in text


def test_no_generated_code_execution_in_application():
    for file in (ROOT/"src").rglob("*.py"):
        tree=ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                if isinstance(node.func,ast.Name): assert node.func.id not in {"eval","exec","compile","__import__"}
                if isinstance(node.func,ast.Attribute): assert node.func.attr not in {"system","popen"}
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                imports=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ""]
                assert not any(name.startswith("subprocess") for name in imports)


def test_gate_has_no_model_dependency():
    text=(ROOT/"src/redqueen/verification.py").read_text(encoding="utf-8")
    assert "gemma_client" not in text and "google" not in text


def test_env_ignored_and_not_tracked():
    ignored=subprocess.run(["git","check-ignore",".env"],cwd=ROOT,capture_output=True,text=True)
    assert ignored.returncode==0
    tracked=subprocess.check_output(["git","ls-files"],cwd=ROOT,text=True).splitlines()
    assert ".env" not in tracked and ".streamlit/secrets.toml" not in tracked
    assert not any(Path(p).name.startswith(".env") and Path(p).name!=".env.example" for p in tracked)


def test_settings_repr_and_json_are_secret_safe():
    settings=Settings(api_key=SecretStr("sentinel-secret"))
    assert "sentinel-secret" not in repr(settings)+str(settings)+settings.model_dump_json()


def test_no_illustrative_result_literals():
    for file in (ROOT/"src").rglob("*.py"):
        tree=ast.parse(file.read_text(encoding="utf-8"))
        assert not any(isinstance(n,ast.Constant) and type(n.value)==float and n.value in {86.4,48.2,38.2} for n in ast.walk(tree))


def test_pipeline_result_exposes_json_aggregates_and_sample_features_only():
    import pandas as pd
    result=run_redqueen("GiftCardNightBurst",Settings(),"replay")
    assert not any(isinstance(getattr(result,f.name),pd.DataFrame) for f in fields(result))
    data=result.to_dict()
    assert "datasets" not in data
    assert data["dataset_metadata"]=={"sample":2000,"validation":5000,"sealed":10000}
    rows=result.evidence.missed_fraud+result.evidence.lookalike_legit
    assert all(not {"is_fraud","attack_name","txn_id","split"}.intersection(row) for row in rows)
    assert "T000" not in json.dumps(data) and "V000" not in json.dumps(data)


def test_replay_fixtures_store_no_metrics_or_verdicts():
    for file in (ROOT/"data/replay").glob("*.json"):
        data=json.loads(file.read_text(encoding="utf-8"))
        assert set(data)=={"name","label","scenario_text","attack_spec","proposed_rule"}
        assert data["label"]=="REPLAY"


def test_dashboard_enforces_600_character_limit(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("GEMINI_API_KEY","")
    app=AppTest.from_file(ROOT/"app.py",default_timeout=20).run()
    app.text_area(key="scenario_text").set_value("x"*601).run()
    next(b for b in app.button if b.label=="Run RedQueen").click().run()
    assert not app.exception
    assert len(app.text_area(key="scenario_text").value)==600
    assert len(app.session_state.result.scenario)==600
    assert app.session_state.result.telemetry.mode=="replay"


def test_live_smoke_no_key_has_clear_exit_code():
    import os
    import sys
    result=subprocess.run([sys.executable,"-X","utf8","scripts/smoke_gemma.py"],cwd=ROOT,
        env=dict(os.environ,GEMINI_API_KEY=""),capture_output=True,text=True,encoding="utf-8",timeout=10)
    assert result.returncode==2
    assert "No GEMINI_API_KEY" in result.stdout and "replay" in result.stdout
