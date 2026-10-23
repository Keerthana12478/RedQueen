import json
import subprocess
import sys
from pathlib import Path


def test_headless_benchmark_is_real_and_offline(tmp_path):
    output = tmp_path / "benchmark.json"
    result = subprocess.run([sys.executable, "benchmarks/run_benchmark.py", "--mode", "replay", "--seed", "1337", "--scenarios", "all", "--json", str(output)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "OFFLINE REPLAY" in result.stdout
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert len(rows) >= 3
    assert {r["report"]["verdict"] for r in rows} == {"ACCEPTED", "REJECTED"}
    assert all(r["report"]["sealed_evaluated"] for r in rows)
