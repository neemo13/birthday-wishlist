"""Binds the database-verified session to Streamlit's per-browser-tab session_state."""
from __future__ import annotations

import streamlit as st

from . import auth, ui
from .db import BackendError

TOKEN_KEY = "_session_token"


def token() -> str | None:
    return st.session_state.get(TOKEN_KEY)


def sign_in(new_token: str) -> None:
    st.session_state[TOKEN_KEY] = new_token


def current_session() -> auth.Session | None:
    """Re-verified against the database on every rerun; stale or forged tokens yield None."""
    tok = token()
    if not tok:
        return None
    sess = auth.load_session(tok)
    if sess is None:
        st.session_state.pop(TOKEN_KEY, None)
        ui.flash("info", "Your session has ended - please sign in again. ♡")
    return sess


def sign_out() -> None:
    try:
        auth.logout(token())
    except BackendError:
        pass  # still clear locally; the server-side session expires on its own
    st.session_state.clear()
    ui.flash("info", "You've been signed out. See you soon! ♡")
