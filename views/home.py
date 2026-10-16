"""The private birthday homepage: portrait, message, and the button into the wishlist."""
from __future__ import annotations

import streamlit as st

from wishlist import content, state, storage
from wishlist.auth import Session
from wishlist.ui import esc, esc_multiline


def _go_wishlist() -> None:
    st.session_state["nav_choice"] = "wishlist"     # callback runs before the rerun, so this is allowed


def render(sess: Session) -> None:
    token = state.token()
    settings = content.get_settings(token)
    hp = settings["homepage"]
    order = content.visible_sections(settings, "homepage")

    portrait_url = None
    if "portrait" in order and hp.get("portrait_path"):
        urls = storage.signed_urls(token, [hp["portrait_path"]], st.session_state.setdefault("_img_cache", {}))
        portrait_url = urls.get(hp["portrait_path"])

    with st.container(key="hero"):
        for section in order:
            if section == "portrait":
                inner = (f'<img class="gw-portrait" src="{esc(portrait_url)}" alt="Birthday portrait">'
                         if portrait_url else '<div class="gw-portrait gw-portrait--placeholder">21</div>')
                st.markdown(f'<div class="gw-portrait-wrap"><div class="gw-portrait-frame">{inner}</div></div>',
                            unsafe_allow_html=True)
            elif section == "message":
                st.markdown(
                    f'<div class="gw-hero-text"><div class="gw-eyebrow">{esc(hp["eyebrow"])}</div>'
                    f'<h1 class="gw-hero-title">{esc(hp["heading"])}</h1>'
                    f'<p class="gw-hero-sub">{esc_multiline(hp["subtitle"])}</p>'
                    f'<p class="gw-hero-msg">{esc_multiline(hp["message"])}</p></div>',
                    unsafe_allow_html=True)
            elif section == "cta":
                with st.container(key="hero_cta"):
                    st.button(hp["button_label"] or "Enter the World of Gifts ✨", type="primary",
                              on_click=_go_wishlist, key="hero_cta_btn")
