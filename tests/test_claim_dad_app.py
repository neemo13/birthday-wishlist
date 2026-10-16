"""Claim / release / Dad Only journeys through the real app (AppTest) on local PostgreSQL; storage mocked."""
import pytest

from tests.conftest import ADMIN_PW, DAD_PIN, FAMILY_PIN
from tests.test_app_phase2 import card_titles, login, page_text, to_wishlist
from wishlist import claims

DAD_LABEL = "🔒 Dad Only"


@pytest.fixture(autouse=True)
def _storage(fake_storage):
    return fake_storage


def open_gift(at, pid):
    [b for b in at.button if b.key == f"open_{pid}"][0].click().run()
    assert not at.exception
    return at


def wishlist(slug, secret=FAMILY_PIN, role="Gift Giver"):
    at = login(role, secret, slug)
    if role == "Gift Giver":
        to_wishlist(at)
    else:
        at.session_state["nav_choice"] = "wishlist"; at.run()
    return at


def balloons(at):
    return len(at.get("balloons"))


def errors(at):
    return " ".join(e.value for e in at.error)


def start_claim(at, pid):
    open_gift(at, pid)
    at.button(key=f"claiming_{pid}_open").click().run()
    assert not at.exception


def submit(at, label):
    [b for b in at.button if b.label == label][0].click().run()
    assert not at.exception


# ------------------------------------------------------------------ claim
def test_family_member_claims_a_gift_and_celebrates_only_after_success(pg, creds, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    at = wishlist("mom")
    start_claim(at, pid)
    assert at.selectbox(key=f"cl_name_{pid}").value == "mom"                # defaults to the signed-in name
    at.text_input(key=f"cl_pin_{pid}").input("2468")
    at.text_input(key=f"cl_pin2_{pid}").input("2468")
    at.checkbox(key=f"cl_ok_{pid}").check()
    submit(at, "Confirm claim ✨")
    assert pg.sql("select family_slug, status from claims") == [("mom", "active")]
    assert balloons(at) == 1 and "now claimed" in " ".join(m.value for m in at.success)
    at.run()
    assert balloons(at) == 0                                                  # a later rerun never repeats the celebration


@pytest.mark.parametrize("pin,pin2,ticked,expected", [
    ("2468", "2469", True, "match"), ("12", "12", True, "4 to 8"), ("2468", "2468", False, "tick"), ("abcd", "abcd", True, "4 to 8"),
])
def test_failed_claims_show_a_message_and_never_celebrate(pg, creds, catalog_ids, pin, pin2, ticked, expected):
    pid = catalog_ids["Gentle Cleanser"]
    at = wishlist("mom")
    start_claim(at, pid)
    at.text_input(key=f"cl_pin_{pid}").input(pin)
    at.text_input(key=f"cl_pin2_{pid}").input(pin2)
    if ticked:
        at.checkbox(key=f"cl_ok_{pid}").check()
    submit(at, "Confirm claim ✨")
    assert expected in errors(at) and balloons(at) == 0 and pg.sql("select count(*) from claims")[0][0] == 0


def test_confirming_as_a_different_name_is_refused_by_the_server(pg, creds, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    at = wishlist("mom")
    start_claim(at, pid)
    at.selectbox(key=f"cl_name_{pid}").set_value("dad")
    at.text_input(key=f"cl_pin_{pid}").input("2468")
    at.text_input(key=f"cl_pin2_{pid}").input("2468")
    at.checkbox(key=f"cl_ok_{pid}").check()
    submit(at, "Confirm claim ✨")
    assert "signed in with" in errors(at) and balloons(at) == 0 and pg.sql("select count(*) from claims")[0][0] == 0


def test_losing_a_claim_race_never_creates_a_second_claim_or_celebrates(pg, creds, tokens, catalog_ids):
    """Someone else wins while Mom's form is open. On the next full rerun the dialog re-reads the catalog and offers
    the *release* form (the gift is now Dad's); Mom's submit cannot create a claim. (In a live browser the dialog is a
    fragment that keeps its old arguments, so the server's 'already claimed' answer is what is shown - covered in
    test_claims_sql.py::test_second_claim_on_the_same_gift_fails_and_changes_nothing.)"""
    pid = catalog_ids["Gentle Cleanser"]
    at = wishlist("mom")
    start_claim(at, pid)
    claims.claim(tokens.dad, pid, "dad", "1357", "1357")
    at.text_input(key=f"cl_pin_{pid}").input("2468")
    at.text_input(key=f"cl_pin2_{pid}").input("2468")
    at.checkbox(key=f"cl_ok_{pid}").check()
    submit(at, "Confirm claim ✨")
    assert balloons(at) == 0 and not at.exception
    assert pg.sql("select family_slug, status from claims") == [("dad", "active")]
    assert "claimed by Dad" in page_text(at)


def test_admin_sees_no_claim_or_release_buttons(pg, creds, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.mom, pid, "mom", "2468", "2468")
    at = wishlist(None, ADMIN_PW, "Birthday Girl")
    open_gift(at, pid)
    assert not [b for b in at.button if b.key and ("claiming_" in b.key or "releasing_" in b.key)]
    assert "Admin Studio" in " ".join(c.value for c in at.caption)


# ------------------------------------------------------------------ release
def test_release_with_name_and_pin_then_celebrate(pg, creds, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.dad, pid, "dad", "2468", "2468")
    at = wishlist("mom")
    open_gift(at, pid)
    at.button(key=f"releasing_{pid}_open").click().run()
    assert "Dad" in at.selectbox(key=f"rl_name_{pid}").options
    at.selectbox(key=f"rl_name_{pid}").set_value("Dad")
    at.text_input(key=f"rl_pin_{pid}").input("2468")
    at.checkbox(key=f"rl_ok_{pid}").check()
    submit(at, "Release gift")
    assert pg.sql("select status, pin_hash from claims") == [("released", None)]
    assert balloons(at) == 1 and "available again" in " ".join(m.value for m in at.success)


def test_wrong_pin_or_name_gives_the_same_generic_message_and_no_balloons(pg, creds, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.dad, pid, "dad", "2468", "2468")
    messages = []
    for name, pin in (("Dad", "0000"), ("Mom", "2468")):
        at = wishlist("mom")
        open_gift(at, pid)
        at.button(key=f"releasing_{pid}_open").click().run()
        at.selectbox(key=f"rl_name_{pid}").set_value(name)
        at.text_input(key=f"rl_pin_{pid}").input(pin)
        at.checkbox(key=f"rl_ok_{pid}").check()
        submit(at, "Release gift")
        messages.append(errors(at))
        assert balloons(at) == 0
    assert messages[0] == messages[1] and "don't match" in messages[0]
    assert pg.sql("select status from claims") == [("active",)]


def test_release_needs_the_confirmation_box(pg, creds, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.dad, pid, "dad", "2468", "2468")
    at = wishlist("mom")
    open_gift(at, pid)
    at.button(key=f"releasing_{pid}_open").click().run()
    at.selectbox(key=f"rl_name_{pid}").set_value("Dad")
    at.text_input(key=f"rl_pin_{pid}").input("2468")
    submit(at, "Release gift")
    assert "tick" in errors(at) and pg.sql("select status from claims") == [("active",)]


def test_session_throttle_blocks_rapid_wrong_guesses_in_the_ui(pg, creds, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.dad, pid, "dad", "2468", "2468")
    at = wishlist("mom")
    open_gift(at, pid)
    at.button(key=f"releasing_{pid}_open").click().run()
    for _ in range(6):
        at.selectbox(key=f"rl_name_{pid}").set_value("Dad")
        at.text_input(key=f"rl_pin_{pid}").input("0000")
        at.checkbox(key=f"rl_ok_{pid}").check()
        submit(at, "Release gift")
    assert any(w in errors(at) for w in ("wait", "Too many"))


# ------------------------------------------------------------------ Dad Only
def go_dad(at):
    at.session_state["wl_cat"] = DAD_LABEL
    at.run()
    assert not at.exception
    return at


def test_dad_sees_the_private_category_and_needs_the_pin(pg, creds, catalog_ids):
    at = wishlist("dad")
    assert len(card_titles(at)) == 7                                         # ordinary wishlist fully available
    go_dad(at)
    text = page_text(at)
    assert "Just for Dad" in text and "birthday to remember" not in text and card_titles(at) == []
    at.text_input(key="dad_pin_input").input("wrong-pin-000")
    submit(at, "Open ✨")
    assert "didn't match" in errors(at) and "birthday to remember" not in page_text(at)
    at.text_input(key="dad_pin_input").input(DAD_PIN)
    submit(at, "Open ✨")
    text = page_text(at)
    assert "birthday to remember" in text and "gw-dad-card" in text
    assert "₹" not in text and not [b for b in at.button if b.label and "claim" in b.label.lower()]   # a message, not a catalogue
    assert balloons(at) == 0
    at.button(key="dad_back").click().run()                                  # back to the ordinary wishlist, access intact
    assert len(card_titles(at)) == 7 and "birthday to remember" not in page_text(at)


def test_other_family_members_never_see_the_category_or_the_text(pg, creds, catalog_ids):
    for slug in ("mom", "brother", "grandmother"):
        at = wishlist(slug)
        text = page_text(at)
        assert "Just for Dad" not in text and "birthday to remember" not in text and "Dad Only" not in text
        assert len(card_titles(at)) == 7


def test_admin_can_preview_the_page_without_the_pin(pg, creds):
    at = wishlist(None, ADMIN_PW, "Birthday Girl")
    go_dad(at)
    assert "birthday to remember" in page_text(at) and not [t for t in at.text_input if t.key == "dad_pin_input"]


def test_disabling_the_page_removes_it_from_dads_view(pg, creds):
    at = wishlist("dad")
    go_dad(at)
    at.text_input(key="dad_pin_input").input(DAD_PIN)
    submit(at, "Open ✨")
    assert "birthday to remember" in page_text(at)
    pg.sql("update app_credentials set enabled=false where kind='dad_only'")
    pg.sql("update sessions set dad_unlocked=false")
    at.run()
    assert not at.exception and "birthday to remember" not in page_text(at)
