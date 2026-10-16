"""After the family PIN: who is joining? (A label for claims - not identity verification.)"""
from __future__ import annotations

import streamlit as st

from wishlist import family, state, ui


def render(token: str) -> None:
    names = family.list_names(token)
    with st.container(key="pick_card"):
        st.markdown('<h1 class="gw-login-title">Who\'s joining the party?</h1>'
                    '<p class="gw-login-sub">Pick your name - it\'s shown next to any gift you claim.</p>',
                    unsafe_allow_html=True)
        for item in names:
            if st.button(item["display_name"], key=f"pick_{item['slug']}", width="stretch"):
                family.choose(token, item["slug"])
                ui.flash("success", f"Lovely to see you, {item['display_name']}! ♡")
                st.rerun()
        st.markdown('<p class="gw-fineprint">This only labels your gifts. Private pages need their own PIN.</p>',
                    unsafe_allow_html=True)
        if st.button("← Back to sign in", key="pick_back", type="tertiary"):
            state.sign_out()
            st.rerun()
