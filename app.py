"""Entry point:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="A Little Something Special", page_icon="🎀", layout="wide",
                   initial_sidebar_state="collapsed")

from wishlist import state, styles, ui  # noqa: E402  (after set_page_config)
from wishlist.config import ConfigError  # noqa: E402
from wishlist.db import BackendError  # noqa: E402
from wishlist.security import PermissionDenied  # noqa: E402
from wishlist.config import log_level  # noqa: E402
from wishlist.logging_setup import setup_logging  # noqa: E402
from views import admin as admin_view, choose_name, home, login, wishlist  # noqa: E402

NAV = {"home": "Home", "wishlist": "Wishlist"}


def main() -> None:
    setup_logging(log_level())
    styles.inject()
    try:
        sess = state.current_session()
        ui.render_flashes()
        if sess is None:
            login.render()
        elif sess.needs_name:
            choose_name.render(state.token())
        else:
            nav = NAV | ({"admin": "Admin Studio"} if sess.is_admin else {})
            page, logout = ui.topbar("Birthday Girl" if sess.is_admin else sess.display_name, nav=nav)
            if logout:
                state.sign_out()
                st.rerun()
            if page == "admin" and not sess.is_admin:
                raise PermissionDenied("This area is only for the Birthday Girl.")   # belt and braces
            {"home": home, "wishlist": wishlist, "admin": admin_view}[page].render(sess)
        ui.run_celebrations()
    except ConfigError as exc:
        st.error(str(exc), icon="⚙️")          # names missing keys, never values
    except BackendError as exc:
        st.error(str(exc), icon="🎀")
    except PermissionDenied as exc:
        st.warning(str(exc), icon="🔒")
        state.sign_out()


main()
