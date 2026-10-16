"""Headless journeys through the real app (Streamlit AppTest) on a real local PostgreSQL.
Storage is the in-memory FakeStorage, so these are NOT tests of Supabase Storage."""
import pathlib
import re

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import ADMIN_PW, FAMILY_PIN

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def _storage(fake_storage):
    return fake_storage


def login(role, secret, name=None):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.selectbox(key="login_role").select(role).run()
    key = "admin" if role == "Birthday Girl" else "family"
    at.text_input(key=f"login_secret_{key}").input(secret)
    [b for b in at.button if "Enter the World" in b.label][0].click().run()
    if name:
        at.button(key=f"pick_{name}").click().run()
    assert not at.exception
    return at


def to_wishlist(at):
    at.button(key="hero_cta_btn").click().run()
    assert not at.exception
    return at


def card_titles(at):
    return [m for v in (x.value for x in at.markdown)
            for m in re.findall(r'class="gw-card-title">(.*?)</div>', v)]


def page_text(at):
    return " ".join(m.value for m in at.markdown)


def test_homepage_shows_editable_copy_and_cta_leads_to_wishlist(pg, creds, catalog_ids):
    at = login("Gift Giver", FAMILY_PIN, "mom")
    text = page_text(at)
    assert "Happy 21st Birthday!" in text and "celebrate the girl" in text
    assert [b.label for b in at.button if b.key == "hero_cta_btn"] == ["Enter the World of Gifts ✨"]
    to_wishlist(at)
    assert "The Wishlist" in page_text(at) and len(card_titles(at)) == 7


def test_homepage_text_comes_from_the_database(pg, creds, catalog_ids):
    pg.sql("update app_settings set value = value || '{\"heading\": \"Twenty-One!\", \"button_label\": \"Open sesame\"}' where key='homepage'")
    at = login("Gift Giver", FAMILY_PIN, "brother")
    assert "Twenty-One!" in page_text(at) and at.button(key="hero_cta_btn").label == "Open sesame"


def test_homepage_sections_can_be_hidden_and_reordered(pg, creds, catalog_ids):
    pg.sql("""update app_settings set value = '{"homepage":[{"id":"cta","visible":true},{"id":"message","visible":false},
              {"id":"portrait","visible":false}],"wishlist":[]}'::jsonb where key='sections'""")
    at = login("Gift Giver", FAMILY_PIN, "mom")
    assert "Happy 21st Birthday!" not in page_text(at) and at.button(key="hero_cta_btn")


def test_portrait_uses_a_short_lived_signed_url_never_a_public_one(pg, creds, catalog_ids, fake_storage):
    at = login("Gift Giver", FAMILY_PIN, "mom")
    img = re.search(r'<img class="gw-portrait" src="([^"]+)"', page_text(at))
    assert img and img.group(1).startswith("https://signed.invalid/portrait/") and "token=" in img.group(1)
    assert fake_storage.sign_calls and all(p.startswith("portrait/") for p in fake_storage.sign_calls[0])


def test_missing_portrait_shows_a_graceful_placeholder(pg, creds, catalog_ids, fake_storage):
    fake_storage.fail_sign = True
    at = login("Gift Giver", FAMILY_PIN, "mom")
    assert not at.exception and "gw-portrait--placeholder" in page_text(at)


def test_search_filters_and_sorting_work_together(pg, creds, catalog_ids):
    at = to_wishlist(login("Gift Giver", FAMILY_PIN, "mom"))
    at.text_input(key="wl_query").input("gloss").run()
    assert card_titles(at) == ["Rose Quartz Lip Gloss"]
    at.text_input(key="wl_query").input("").run()
    at.selectbox(key="wl_status").select("Available").run()
    assert len(card_titles(at)) == 7
    at.selectbox(key="wl_sort").select("Price: low to high").run()
    assert card_titles(at)[0] == "Dog Squeaky Toy" and card_titles(at)[-1] == "Poetry Collection"   # unpriced last
    at.selectbox(key="wl_sort").select("Alphabetical (A–Z)").run()
    assert card_titles(at) == sorted(card_titles(at), key=str.casefold)
    at.selectbox(key="wl_sort").select("Newest added").run()
    assert card_titles(at)[0] == "Mystery Treat Box"


def test_claimed_filter_and_label(pg, creds, catalog_ids):
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'brother','$2a$x')", [catalog_ids["Gentle Cleanser"]])
    at = to_wishlist(login("Gift Giver", FAMILY_PIN, "mom"))
    at.selectbox(key="wl_status").select("Claimed").run()
    assert card_titles(at) == ["Gentle Cleanser"] and "claimed by Brother" in page_text(at)
    at.selectbox(key="wl_status").select("Available").run()
    assert "Gentle Cleanser" not in card_titles(at)


def test_category_filter_and_empty_state(pg, creds, catalog_ids):
    at = to_wishlist(login("Gift Giver", FAMILY_PIN, "mom"))
    at.session_state["wl_cat"] = "Makeup"
    at.run()
    assert card_titles(at) == ["Rose Quartz Lip Gloss"]
    at.text_input(key="wl_query").input("zzzz-nothing").run()
    assert card_titles(at) == [] and "No gifts match that" in page_text(at)
    assert [b for b in at.button if b.key == "clear_filters"]


def test_empty_wishlist_has_a_friendly_state(pg, creds):
    at = to_wishlist(login("Gift Giver", FAMILY_PIN, "mom"))
    assert "still being wrapped" in page_text(at) and not at.exception


def test_hidden_wishlist_sections_disappear(pg, creds, catalog_ids):
    pg.sql("""update app_settings set value = '{"homepage":[],"wishlist":[{"id":"grid","visible":true},
              {"id":"search","visible":false},{"id":"filters","visible":false},{"id":"intro","visible":false}]}'::jsonb
              where key='sections'""")
    at = to_wishlist(login("Gift Giver", FAMILY_PIN, "mom"))
    assert not [t for t in at.text_input if t.key == "wl_query"] and "The Wishlist" not in page_text(at)
    assert len(card_titles(at)) == 7


def test_html_in_product_text_is_escaped_not_executed(pg, creds):
    pg.sql("insert into products (name, short_description) values ('<script>alert(1)</script>', '<img src=x onerror=alert(2)>')")
    at = to_wishlist(login("Gift Giver", FAMILY_PIN, "mom"))
    html = page_text(at)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html and "<img src=x onerror" not in html


def test_dad_only_content_is_not_reachable_from_the_wishlist(pg, creds, catalog_ids):
    for secret, role, name in ((FAMILY_PIN, "Gift Giver", "mom"), (FAMILY_PIN, "Gift Giver", "dad"), (ADMIN_PW, "Birthday Girl", None)):
        at = login(role, secret, name)
        if role == "Gift Giver":
            to_wishlist(at)
        else:
            at.session_state["nav_choice"] = "wishlist"; at.run()
        text = page_text(at)
        assert "birthday to remember" not in text and "Dad Only" not in text
        assert len(card_titles(at)) == 7                      # Dad (and admin) keep the ordinary wishlist


def test_wishlist_is_unreachable_when_logged_out_even_with_forged_state(pg, creds, catalog_ids):
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["nav_choice"] = "wishlist"
    at.session_state["_session_token"] = "forged"
    at.run()
    assert not at.exception and "Welcome, lovely!" in page_text(at).replace("&nbsp;", " ") and card_titles(at) == []


def test_backend_outage_shows_friendly_message_not_a_traceback(pg, creds, catalog_ids):
    from wishlist import db
    at = login("Gift Giver", FAMILY_PIN, "mom")

    class Down:
        def rpc(self, *a, **k): raise ConnectionError("db host 10.0.0.5 refused")
    db.set_client(Down())
    at.run()
    assert not at.exception
    assert any("couldn't reach" in e.value for e in at.error) and "10.0.0.5" not in " ".join(e.value for e in at.error)
