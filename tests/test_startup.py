"""Verify the documented Streamlit command serves HTTP on localhost."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def test_streamlit_launch_command_serves_health_and_page(tmp_path):
    root=Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    with (tmp_path/"streamlit.log").open("w",encoding="utf-8") as log:
        server=subprocess.Popen([sys.executable,"-m","streamlit","run","app.py",
            "--server.headless","true","--server.address","127.0.0.1","--server.port",str(port)],
            cwd=root,stdout=log,stderr=subprocess.STDOUT,
            env=dict(os.environ,GEMINI_API_KEY="",REDQUEEN_MODE="replay"))
        try:
            deadline=time.monotonic()+20
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/_stcore/health",timeout=2) as response:
                        assert response.status==200 and response.read()==b"ok"
                    break
                except (URLError,TimeoutError):
                    if time.monotonic()>=deadline or server.poll() is not None:
                        raise AssertionError("Streamlit startup failed: "+(tmp_path/"streamlit.log").read_text(encoding="utf-8"))
                    time.sleep(.2)
            with urlopen(f"http://127.0.0.1:{port}/",timeout=2) as response:
                assert response.status==200
                assert b"Streamlit" in response.read()
        finally:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
