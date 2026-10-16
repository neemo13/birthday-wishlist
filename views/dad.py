"""The private Dad Only page: one playful message, no catalogue. All access decisions are made by PostgreSQL
(dad_unlock / dad_page_get); this view only asks."""
from __future__ import annotations

import streamlit as st

from wishlist import dad, state
from wishlist.auth import Session
from wishlist.security import (PermissionDenied, ValidationError, throttle_register_failure, throttle_remaining,
                               throttle_reset)
from wishlist.ui import esc, esc_multiline


def _back() -> None:
    st.session_state["wl_cat"] = "All"            # callback: runs before the rerun, so setting a widget key is allowed


def render(sess: Session) -> None:
    token = state.token()
    if sess.is_admin or sess.dad_unlocked:
        try:
            page = dad.get_page(token)
        except PermissionDenied:                   # e.g. the page was switched off while Dad was looking
            _resting()
        else:
            _message(page)
    elif sess.is_dad:
        _pin_form(token)
    else:
        st.info("This page isn't open for you.", icon="🔒")
    st.button("← Back to the wishlist", key="dad_back", on_click=_back)


def _message(page: dict) -> None:
    st.markdown(
        '<div class="gw-dad-card"><div class="gw-dad-hearts" aria-hidden="true">♡ ✦ ♡</div>'
        f'<h2 class="gw-dad-title">{esc(page.get("title"))}</h2>'
        f'<p class="gw-dad-msg">{esc_multiline(page.get("message"))}</p>'
        '<div class="gw-dad-hearts" aria-hidden="true">🎀</div></div>', unsafe_allow_html=True)


def _resting() -> None:
    st.markdown('<div class="gw-empty"><div class="gw-empty-icon">🤫</div><h3>This page is resting</h3>'
                '<p class="gw-muted">It isn\'t open right now.</p></div>', unsafe_allow_html=True)


def _pin_form(token: str) -> None:
    st.markdown('<div class="gw-dad-card gw-dad-card--locked"><div class="gw-dad-hearts" aria-hidden="true">🔒</div>'
                '<h2 class="gw-dad-title">Just for Dad</h2>'
                '<p class="gw-dad-msg">Enter the special PIN you were given.</p></div>', unsafe_allow_html=True)
    with st.container(key="dad_pin_box"):
        with st.form("dad_pin_form", clear_on_submit=True, border=False):
            pin = st.text_input("Dad Only PIN", type="password", max_chars=128, key="dad_pin_input")
            go = st.form_submit_button("Open ✨", type="primary", width="stretch")
        if go:
            wait = throttle_remaining(st.session_state, "dadpin")
            if wait:
                st.error(f"Please wait {wait} seconds and try again.", icon="⏳")
                return
            try:
                dad.unlock(token, pin)
            except PermissionDenied:
                raise
            except ValidationError as exc:
                throttle_register_failure(st.session_state, "dadpin")
                st.error(str(exc), icon="🎀")
                return
            throttle_reset(st.session_state, "dadpin")
            st.rerun()
