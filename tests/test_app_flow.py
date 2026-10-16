"""Drives the real app.py headlessly (Streamlit AppTest) against the real SQL functions."""
import pytest
import pathlib

from streamlit.testing.v1 import AppTest

from tests.conftest import ADMIN_PW, FAMILY_PIN

TOKEN = "_session_token"
APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


def fresh_app():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def submit(at, role, secret):
    at.selectbox(key="login_role").select(role).run()
    role_key = {"Birthday Girl": "admin", "Gift Giver": "family"}[role]
    at.text_input(key=f"login_secret_{role_key}").input(secret)
    [b for b in at.button if "Enter the World" in b.label][0].click()
    at.run()
    assert not at.exception
    return at


def texts(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(e.value for e in at.error)


def test_first_page_is_login_with_exactly_two_roles(pg, creds):
    at = fresh_app()
    assert "Welcome, lovely!" in texts(at).replace("&nbsp;", " ")
    assert at.selectbox(key="login_role").options == ["Birthday Girl", "Gift Giver"]
    assert TOKEN not in at.session_state
    assert not at.get("balloons")
    for private in ("Happy 21st", "Wishlist", "Dad Only"):
        assert private not in texts(at)


def test_secret_label_changes_with_role(pg, creds):
    at = fresh_app()
    assert at.text_input(key="login_secret_family").label == "Family PIN"
    at.selectbox(key="login_role").select("Birthday Girl").run()
    assert at.text_input(key="login_secret_admin").label == "Your secret password"


def test_wrong_credentials_show_generic_error_and_no_balloons(pg, creds):
    at = submit(fresh_app(), "Gift Giver", "wrong-pin-1")
    assert TOKEN not in at.session_state and not at.get("balloons")
    assert [e.value for e in at.error] and "didn't match" in at.error[0].value
    assert "wrong-pin-1" not in texts(at)          # the secret is never echoed back


def test_family_flow_login_then_pick_name_then_logout(pg, creds):
    at = submit(fresh_app(), "Gift Giver", FAMILY_PIN)
    assert at.session_state[TOKEN]
    assert len(at.get("balloons")) == 1            # celebration after a *successful* login
    assert "Who's joining the party?" in texts(at)
    labels = [b.label for b in at.button]
    assert {"Grandmother", "Brother", "Mom", "Dad"} <= set(labels)
    at.button(key="pick_mom").click().run()
    assert not at.exception and not at.get("balloons")   # no repeat celebration on later reruns
    assert "Happy 21st Birthday!" in texts(at)
    at.button(key="logout_btn").click().run()
    assert TOKEN not in at.session_state
    assert "Welcome, lovely!" in texts(at).replace("&nbsp;", " ")


def test_admin_login_and_forged_token_is_rejected(pg, creds):
    at = submit(fresh_app(), "Birthday Girl", ADMIN_PW)
    assert "Happy 21st Birthday!" in texts(at)
    at.session_state[TOKEN] = "forged-token-value"       # tampering with session state
    at.run()
    assert not at.exception
    assert TOKEN not in at.session_state
    assert "Welcome, lovely!" in texts(at).replace("&nbsp;", " ")               # back at the login page


def test_server_session_revoked_returns_user_to_login(pg, creds):
    at = submit(fresh_app(), "Birthday Girl", ADMIN_PW)
    pg.sql("delete from sessions")                        # e.g. expiry or credential rotation
    at.run()
    assert "Welcome, lovely!" in texts(at).replace("&nbsp;", " ") and TOKEN not in at.session_state


def test_missing_configuration_shows_friendly_message_not_traceback(monkeypatch):
    from wishlist import db
    db.set_client(None)
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir("/tmp")  # no secrets.toml here
    import os
    os.environ.pop("SUPABASE_URL", None)
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state[TOKEN] = "x"
    at.run()
    assert not at.exception
    assert any("Missing configuration" in e.value for e in at.error)
