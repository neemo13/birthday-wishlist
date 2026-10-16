"""The first (and, when logged out, only) page."""
from __future__ import annotations

import streamlit as st

from wishlist import auth, state, ui
from wishlist.security import throttle_register_failure, throttle_remaining, throttle_reset

SECRET_LABELS = {
    "Birthday Girl": ("Your secret password", "Only you know this one ♡"),
    "Gift Giver": ("Family PIN", "The PIN you were given by the birthday girl"),
}


def render() -> None:
    st.markdown(
        '<div class="gw-motif" aria-hidden="true"><span class="gw-sparkle">✦</span>🎀'
        '<span class="gw-sparkle">✦</span></div>', unsafe_allow_html=True)
    with st.container(key="login_card"):
        st.markdown('<h1 class="gw-login-title">Welcome, lovely!&nbsp;♡</h1>'
                    '<p class="gw-login-sub">A little something special awaits you.</p>', unsafe_allow_html=True)
        role_label = st.selectbox("I am the…", list(auth.ROLE_LABELS), index=1, key="login_role")  # most visitors are family
        label, hint = SECRET_LABELS[role_label]
        with st.form("login_form", clear_on_submit=True, border=False):
            secret = st.text_input(label, type="password", max_chars=128, help=hint,
                                   placeholder="••••••", key=f"login_secret_{auth.ROLE_LABELS[role_label]}")
            submitted = st.form_submit_button("Enter the World of Gifts ✨", type="primary", width="stretch")
        st.markdown('<p class="gw-fineprint">Private party · invitation only</p>', unsafe_allow_html=True)

        if submitted:
            _handle_submit(role_label, secret)


def _handle_submit(role_label: str, secret: str) -> None:
    wait = throttle_remaining(st.session_state, "login")
    if wait:
        st.error(f"Too many tries. Please wait {wait} seconds and try again.", icon="⏳")
        return
    if not secret:
        st.error("Please enter your " + SECRET_LABELS[role_label][0].lower() + ".", icon="🎀")
        return
    outcome = auth.login(role_label, secret)  # BackendError is caught by app.py's guard
    if outcome.ok:
        throttle_reset(st.session_state, "login")
        state.sign_in(outcome.token)
        ui.celebrate("login")   # balloons only fire after the database confirmed the login
        st.rerun()
    throttle_register_failure(st.session_state, "login")
    if outcome.code == "locked":
        mins = max(1, -(-outcome.retry_after // 60))
        st.error(f"Too many wrong tries. Please wait about {mins} minute(s) and try again.", icon="⏳")
    else:
        st.error("That didn't match. Please check it and try again.", icon="🎀")
