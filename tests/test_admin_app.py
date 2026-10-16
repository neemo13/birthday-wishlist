"""Admin Studio driven through the real app (AppTest) on local PostgreSQL; storage is mocked."""
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import ADMIN_PW, FAMILY_PIN
from tests.test_app_phase2 import card_titles, login, page_text

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def _storage(fake_storage):
    return fake_storage


def admin_at(open_studio=True):
    at = login("Birthday Girl", ADMIN_PW)
    if open_studio:
        at.session_state["nav_choice"] = "admin"
        at.run()
    assert not at.exception
    return at


def submit(at, label):
    [b for b in at.button if b.label == label][0].click().run()
    assert not at.exception
    return at


def test_admin_sees_the_studio_and_family_never_does(pg, creds, catalog_ids):
    at = admin_at()
    assert "Admin Studio" in page_text(at)
    assert [t.label for t in at.tabs] == ["Overview", "Gifts", "Categories", "Website", "Portrait", "Family & access", "Claims", "Dad Only"]
    for who in ("mom", "dad"):
        fam = login("Gift Giver", FAMILY_PIN, who)
        fam.session_state["nav_choice"] = None             # deselected nav + a forged "last page"
        fam.session_state["_last_page"] = "admin"
        fam.run()
        assert not fam.exception and "Admin Studio" not in page_text(fam)
        assert "Happy 21st Birthday!" in page_text(fam)     # fell back to a normal page
        assert not [t for t in fam.text_input if t.key and t.key.startswith("pf_")]


def test_overview_shows_counts(pg, creds, catalog_ids):
    at = admin_at()
    html = page_text(at)
    assert 'gw-metric-n">7<' in html and "Categories" in html


def test_admin_adds_a_gift_and_the_family_sees_it(pg, creds):
    at = admin_at()
    at.text_input(key="pf_name_new").input("Pearl Earrings")
    at.text_input(key="pf_short_new").input("Tiny and classy")
    at.number_input(key="pf_min_new").set_value(800.0)
    at.number_input(key="pf_max_new").set_value(1500.0)
    at.text_input(key="pf_ls_new_0").input("Amazon")
    at.text_input(key="pf_lu_new_0").input("https://amazon.example/pearls")
    submit(at, "Add gift ✨")
    assert pg.sql("select name, price_min, price_max from products") == [("Pearl Earrings", 800, 1500)]
    assert pg.sql("select source_name, url from product_links") == [("Amazon", "https://amazon.example/pearls")]
    fam = login("Gift Giver", FAMILY_PIN, "mom")
    fam.button(key="hero_cta_btn").click().run()
    assert card_titles(fam) == ["Pearl Earrings"]


def test_invalid_gift_shows_a_friendly_error_and_saves_nothing(pg, creds):
    at = admin_at()
    at.text_input(key="pf_name_new").input("Bad Link Gift")
    at.text_input(key="pf_ls_new_0").input("Shop")
    at.text_input(key="pf_lu_new_0").input("javascript:alert(1)")
    submit(at, "Add gift ✨")
    assert any("http" in e.value for e in at.error) and pg.sql("select count(*) from products")[0][0] == 0
    at.text_input(key="pf_lu_new_0").input("https://ok.example")
    at.number_input(key="pf_min_new").set_value(900.0)
    at.number_input(key="pf_max_new").set_value(100.0)
    submit(at, "Add gift ✨")
    assert any("minimum price" in e.value for e in at.error) and pg.sql("select count(*) from products")[0][0] == 0


def test_admin_edits_and_archives_a_gift_with_confirmation(pg, creds, catalog_ids):
    at = admin_at()
    pid = catalog_ids["Gentle Cleanser"]
    at.selectbox(key="adm_product_sel").set_value(pid).run()
    at.text_input(key=f"pf_name_{pid}").input("Gentle Cleanser 2")
    submit(at, "Save gift ✨")
    assert pg.sql("select name from products where id=%s", [pid]) == [("Gentle Cleanser 2",)]
    at.selectbox(key="adm_product_sel").set_value(pid).run()
    archive = at.button(key=f"arch_btn_{pid}")
    assert archive.disabled                                         # needs the confirmation checkbox first
    at.checkbox(key=f"arch_ok_{pid}").check().run()
    at.button(key=f"arch_btn_{pid}").click().run()
    assert pg.sql("select is_archived from products where id=%s", [pid]) == [(True,)]


def test_admin_category_flow_add_and_guarded_delete(pg, creds, catalog_ids):
    at = admin_at()
    at.text_input(key="cat_new_name").input("Stationery")
    submit(at, "Add category")
    assert pg.sql("select count(*) from categories where name='Stationery'")[0][0] == 1
    makeup = pg.sql("select id::text from categories where name='Makeup'")[0][0]
    assert at.button(key=f"cat_del_{makeup}").disabled
    at.checkbox(key=f"cat_del_ok_{makeup}").check().run()
    at.selectbox(key=f"cat_move_{makeup}").set_value("").run()      # make uncategorized
    at.button(key=f"cat_del_{makeup}").click().run()
    assert pg.sql("select count(*) from categories where name='Makeup'")[0][0] == 0
    assert pg.sql("select category_id from products where name='Rose Quartz Lip Gloss'")[0][0] is None


def test_homepage_text_edit_shows_on_the_homepage(pg, creds):
    at = admin_at()
    at.text_input(key="hp_heading").input("Twenty-One & Fabulous")
    submit(at, "Save homepage text")
    fam = login("Gift Giver", FAMILY_PIN, "mom")
    assert "Twenty-One &amp; Fabulous" in page_text(fam)           # escaped when rendered


def test_family_pin_change_through_the_ui_needs_the_admin_password(pg, creds):
    at = admin_at()
    at.text_input(key="cred_new").input("new-family-pin-9")
    at.text_input(key="cred_again").input("new-family-pin-9")
    at.text_input(key="cred_cur").input("wrong-admin-pw!!")
    submit(at, "Update")
    assert any("admin password" in e.value for e in at.error)
    from wishlist import auth
    assert auth.login("Gift Giver", FAMILY_PIN).ok                  # unchanged
    at.text_input(key="cred_new").input("new-family-pin-9")
    at.text_input(key="cred_again").input("new-family-pin-9")
    at.text_input(key="cred_cur").input(ADMIN_PW)
    submit(at, "Update")
    assert not auth.login("Gift Giver", FAMILY_PIN).ok and auth.login("Gift Giver", "new-family-pin-9").ok


def test_admin_releases_a_claim_from_the_claims_tab(pg, creds, catalog_ids):
    cid = pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'brother','$2a$x') returning id::text",
                 [catalog_ids["Gentle Cleanser"]])[0][0]
    at = admin_at()
    assert at.button(key=f"claim_rel_{cid}").disabled
    at.checkbox(key=f"claim_ok_{cid}").check().run()
    at.button(key=f"claim_rel_{cid}").click().run()
    assert pg.sql("select status, pin_hash from claims where id=%s", [cid]) == [("released", None)]


def test_dad_only_settings_tab_can_set_message_and_toggle(pg, creds):
    at = admin_at()
    at.text_input(key="dad_title").input("For Dad")
    at.text_area(key="dad_msg_text").input("Please come celebrate!")
    submit(at, "Save message")
    assert pg.sql("select value->>'title' from app_settings where key='dad_page'") == [("For Dad",)]
    at.checkbox(key="dad_enabled").uncheck()
    at.text_input(key="dad_toggle_cur").input(ADMIN_PW)
    submit(at, "Save")
    assert pg.sql("select enabled from app_credentials where kind='dad_only'") == [(False,)]


def test_session_expiry_inside_the_studio_returns_to_login(pg, creds):
    at = admin_at()
    pg.sql("delete from sessions")
    at.run()
    assert not at.exception and "Welcome, lovely!" in page_text(at).replace("&nbsp;", " ")
