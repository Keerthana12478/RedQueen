"""RedQueen — Streamlit application entry point.

Currently a Phase 1 placeholder that confirms the package is installed and
importable.  Phase 5 implements the full dashboard.
"""
from __future__ import annotations

import streamlit as st

from redqueen.config import Settings

settings = Settings.from_env()

st.set_page_config(page_title="RedQueen", page_icon="♛", layout="wide")
st.title("♛ RedQueen — setup OK")
st.caption("*Let the fraudster go first* — adversarial fraud-testing arena")

st.info(
    f"**Mode:** `{settings.mode}`  |  "
    f"**Model:** `{settings.model}`  |  "
    f"**Seed:** `{settings.seed}`"
)

st.markdown(
    """
    ### Status
    Phase 1 skeleton is in place.  Later phases will replace this placeholder
    with the full interactive dashboard.

    > **Gemma proposes.  Python verifies.**
    """
)
