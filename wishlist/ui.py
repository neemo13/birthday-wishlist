"""Small Streamlit UI helpers: flash messages, one-shot celebrations, top bar."""
from __future__ import annotations

import html

import streamlit as st

_FLASH = "_flashes"
_CELEBRATE = "_celebrate"


def flash(kind: str, message: str) -> None:
    """Queue a message that survives exactly one rerun (e.g. before st.rerun())."""
    st.session_state.setdefault(_FLASH, []).append((kind, message))


def render_flashes() -> None:
    for kind, message in st.session_state.pop(_FLASH, []):
        {"success": st.success, "error": st.error, "info": st.info, "warning": st.warning}.get(kind, st.info)(message)


def celebrate(reason: str) -> None:
    """Call ONLY after the underlying operation has actually succeeded."""
    st.session_state[_CELEBRATE] = reason


def run_celebrations() -> None:
    """Fires at most once per celebrate() call, then forgets (reruns never repeat it)."""
    if st.session_state.pop(_CELEBRATE, None):
        st.balloons()


def friendly_error(message: str) -> None:
    st.error(message, icon="🎀")


def esc(text: str | None) -> str:
    """Escape user/admin-entered text for safe use inside HTML we build ourselves (prevents XSS)."""
    return html.escape(text or "", quote=True)


def esc_multiline(text: str | None) -> str:
    return esc(text).replace("\n", "<br>")


def topbar(label: str | None, *, nav: dict[str, str]) -> tuple[str, bool]:
    """Brand + page navigation + logout. Returns (current_page_key, logout_clicked)."""
    last = st.session_state.get("_last_page")
    if last not in nav:                                    # never trust a stored page: only pages this user may see
        last = next(iter(nav))
    if st.session_state.get("nav_choice") not in nav:      # None (re-clicked) or stale -> keep the page
        st.session_state["nav_choice"] = last
    with st.container(key="topbar"):
        left, right = st.columns([4, 2], vertical_alignment="center")
        with left:
            st.markdown('<div class="gw-brand">21 <span>♡</span> Gifts</div>', unsafe_allow_html=True)
        with right:
            who = f"Hi, {label} · " if label else ""
            logout = st.button(f"{who}Log out", key="logout_btn", width="stretch")
        st.segmented_control("Navigate", list(nav), format_func=nav.get, key="nav_choice",
                             label_visibility="collapsed")
    page = st.session_state.get("nav_choice") or last
    st.session_state["_last_page"] = page
    return page, logout
