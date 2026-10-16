"""Admin Studio against REAL local PostgreSQL: authorization, validation, atomicity, audit."""
import json
import uuid

import pytest

from tests.conftest import ADMIN_PW
from wishlist import admin, auth, catalog, content, credentials, family
from wishlist.security import PermissionDenied, ValidationError

UID = str(uuid.uuid4())
ADMIN_CALLS = [
    ("admin_snapshot", {}),
    ("product_save", {"p_product": {"name": "Hacked"}}),
    ("product_set_archived", {"p_id": UID, "p_archived": True}),
    ("category_save", {"p_cat": {"name": "Hacked"}}),
    ("category_delete", {"p_id": UID}),
    ("settings_update", {"p_key": "wishlist", "p_value": {"heading": "Hacked"}}),
    ("dad_page_get_admin", {}), ("dad_page_set", {"p_title": "t", "p_message": "Hacked"}),
    ("claim_admin_release", {"p_claim_id": UID}), ("audit_recent", {}), ("credential_status", {}),
    ("family_rename", {"p_names": {"grandmother": "H", "brother": "H2", "mom": "H3", "dad": "H4"}}),
]


def raw(pg, fn, token, params):
    h = None if token is None else auth.hash_token(token)
    return pg.rpc(fn, {"p_token_hash": h, **params}).execute().data


def snap(tokens):
    return admin.load_snapshot(tokens.admin)


def prod_by_name(tokens, name):
    return next(p for p in snap(tokens).products if p.name == name)


# ------------------------------------------------------------------ authorization
@pytest.mark.parametrize("fn,params", ADMIN_CALLS, ids=[c[0] for c in ADMIN_CALLS])
def test_every_admin_function_refuses_non_admins(pg, creds, tokens, catalog_ids, fn, params):
    nameless = auth.login("Gift Giver", creds.family).token
    for who in (tokens.mom, tokens.dad, nameless, "forged-token", None, ""):
        assert raw(pg, fn, who, params) == {"ok": False, "code": "forbidden"}, (fn, who)
    # ...and nothing changed
    assert pg.sql("select count(*) from products")[0][0] == 7 and pg.sql("select count(*) from categories where name='Hacked'")[0][0] == 0
    assert content.get_settings(tokens.mom)["wishlist"]["heading"] == "The Wishlist"


def test_service_layer_blocks_family_sessions_before_touching_the_database(pg, creds, tokens, catalog_ids):
    for call in (lambda: admin.load_snapshot(tokens.dad), lambda: admin.save_category(tokens.mom, name="X"),
                 lambda: admin.set_archived(tokens.dad, UID, True), lambda: admin.save_dad_page(tokens.dad, title="t", message="m")):
        with pytest.raises(PermissionDenied):
            call()


# ------------------------------------------------------------------ products
def test_create_product_with_ordered_links_is_visible_to_the_family(pg, tokens):
    pid = admin.save_product(tokens.admin, name="Silk Scarf", short_description="Soft", price_min=500, price_max="1,500",
                             links=[{"order": 2, "source_name": "Amazon", "url": "https://amazon.example/x", "note": ""},
                                    {"order": 1, "source_name": "Myntra", "url": "https://myntra.example/y", "note": "Cheaper"}])
    mine = next(p for p in catalog.load_catalog(tokens.mom).products if p.id == pid)
    assert [l.source_name for l in mine.links] == ["Myntra", "Amazon"] and mine.links[0].note == "Cheaper"
    assert (mine.price_min, mine.price_max) == (500, 1500) and not mine.claimed


def test_update_replaces_links_and_clears_or_keeps_image(pg, tokens, fake_storage):
    pid = admin.save_product(tokens.admin, name="Mug", links=[{"order": 1, "source_name": "A", "url": "https://a.example", "note": ""}])
    old = "product/" + "1" * 32 + ".jpg"
    pg.sql("update products set image_path=%s where id=%s", [old, pid])
    admin.save_product(tokens.admin, product_id=pid, name="Mug v2", notes="blue",
                       links=[{"order": 1, "source_name": "B", "url": "https://b.example", "note": ""}])
    p = prod_by_name(tokens, "Mug v2")
    assert [l.source_name for l in p.links] == ["B"] and p.image_path == old and fake_storage.removed == []   # untouched image kept
    admin.save_product(tokens.admin, product_id=pid, name="Mug v2", remove_image=True)
    assert prod_by_name(tokens, "Mug v2").image_path is None and fake_storage.removed == [old]
    assert prod_by_name(tokens, "Mug v2").links == ()                                                      # all links removed


@pytest.mark.parametrize("bad", [
    dict(name=""), dict(name="x", price_min=10, price_max=5), dict(name="x", price_min="abc"), dict(name="x", price_min=-1),
    dict(name="x", links=[{"order": 1, "source_name": "S", "url": "javascript:alert(1)", "note": ""}]),
    dict(name="x", links=[{"order": 1, "source_name": "only name", "url": "", "note": ""}]),
    dict(name="x", category_id=str(uuid.uuid4())),
])
def test_invalid_products_are_rejected_and_nothing_is_saved(pg, tokens, bad):
    with pytest.raises(ValidationError):
        admin.save_product(tokens.admin, **bad)
    assert pg.sql("select count(*) from products")[0][0] == 0


def test_database_rejection_is_atomic_product_and_links_roll_back_together(pg, tokens):
    """Bypass Python validation: a bad link URL must also undo the product insert."""
    res = raw(pg, "product_save", tokens.admin, {"p_product": {"name": "Ghost", "links": [
        {"source_name": "ok", "url": "https://ok.example"}, {"source_name": "bad", "url": "ftp://nope"}]}})
    assert res == {"ok": False, "code": "invalid"}
    assert pg.sql("select count(*) from products where name='Ghost'")[0][0] == 0
    assert pg.sql("select count(*) from product_links")[0][0] == 0
    too_many = [{"source_name": f"s{i}", "url": f"https://s{i}.example"} for i in range(11)]
    assert raw(pg, "product_save", tokens.admin, {"p_product": {"name": "Many", "links": too_many}})["code"] == "too_many_links"


def test_products_cannot_be_put_in_the_dad_only_category(pg, tokens):
    dad_cat = pg.sql("select id::text from categories where kind='dad_only'")[0][0]
    with pytest.raises(ValidationError):
        admin.save_product(tokens.admin, name="Sneaky", category_id=dad_cat)
    assert pg.sql("select count(*) from products")[0][0] == 0


def test_editing_a_missing_product_gives_a_friendly_error(pg, tokens):
    with pytest.raises(ValidationError, match="no longer exists"):
        admin.save_product(tokens.admin, product_id=str(uuid.uuid4()), name="Ghost")


def test_archive_and_restore_round_trip(pg, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    assert snap(tokens).counts["active"] == 7
    assert admin.set_archived(tokens.admin, pid, True) is False
    assert "Gentle Cleanser" not in {p.name for p in catalog.load_catalog(tokens.mom).products}
    s = snap(tokens)
    assert s.counts["active"] == 6 and s.counts["archived"] == 1 and any(p.is_archived for p in s.products)   # admin still sees it
    admin.set_archived(tokens.admin, pid, False)
    assert "Gentle Cleanser" in {p.name for p in catalog.load_catalog(tokens.mom).products}


def test_archiving_a_claimed_product_keeps_the_claim(pg, tokens, catalog_ids):
    pid = catalog_ids["Linen Summer Dress"]
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'mom','$2a$x')", [pid])
    assert admin.set_archived(tokens.admin, pid, True) is True                       # tells the UI a claim exists
    assert pg.sql("select status from claims where product_id=%s", [pid]) == [("active",)]
    admin.set_archived(tokens.admin, pid, False)
    dress = next(p for p in catalog.load_catalog(tokens.mom).products if p.id == pid)
    assert dress.claimed and dress.claimed_by == "Mom"


# ------------------------------------------------------------------ categories
def cat_id(pg, name):
    return pg.sql("select id::text from categories where name=%s", [name])[0][0]


def test_category_create_rename_hide_and_order(pg, tokens, catalog_ids):
    cid = admin.save_category(tokens.admin, name="Plants", description="Green things")
    assert "Plants" in {c.name for c in catalog.load_catalog(tokens.mom).categories}
    admin.save_category(tokens.admin, category_id=cid, name="Garden", description="x", is_hidden=True, sort_order=5)
    assert "Garden" not in {c.name for c in catalog.load_catalog(tokens.mom).categories}      # hidden from family
    names = [c.name for c in catalog.load_catalog(tokens.mom).categories]
    admin.save_category(tokens.admin, category_id=cid, name="Garden", is_hidden=False, sort_order=5)
    assert [c.name for c in catalog.load_catalog(tokens.mom).categories][0] == "Garden" and names != []


def test_duplicate_and_blank_category_names_are_rejected(pg, tokens):
    with pytest.raises(ValidationError, match="already uses"):
        admin.save_category(tokens.admin, name="  makeup ")
    with pytest.raises(ValidationError):
        admin.save_category(tokens.admin, name="   ")
    cid = admin.save_category(tokens.admin, name="Fresh")
    with pytest.raises(ValidationError, match="already uses"):
        admin.save_category(tokens.admin, category_id=cid, name="BOOKS")


def test_category_with_products_needs_a_decision_and_never_loses_gifts(pg, tokens, catalog_ids):
    makeup = cat_id(pg, "Makeup")
    with pytest.raises(ValidationError, match="still has gifts"):
        admin.delete_category(tokens.admin, makeup)
    assert pg.sql("select count(*) from categories where id=%s", [makeup])[0][0] == 1
    pg.sql("update products set is_archived=true where name='Rose Quartz Lip Gloss'")          # archived ones count too
    skin = cat_id(pg, "Skincare")
    assert admin.delete_category(tokens.admin, makeup, reassign_to=skin) == 1
    assert pg.sql("select category_id::text from products where name='Rose Quartz Lip Gloss'")[0][0] == skin
    assert pg.sql("select count(*) from products")[0][0] == 7


def test_delete_with_uncategorize_and_invalid_targets(pg, tokens, catalog_ids):
    books = cat_id(pg, "Books")
    with pytest.raises(ValidationError):
        admin.delete_category(tokens.admin, books, reassign_to=books)                          # itself
    with pytest.raises(ValidationError):
        admin.delete_category(tokens.admin, books, reassign_to=cat_id(pg, "Dad Only"))         # private category
    assert admin.delete_category(tokens.admin, books, uncategorize=True) == 1
    assert pg.sql("select category_id from products where name='Poetry Collection'")[0][0] is None
    empty = admin.save_category(tokens.admin, name="Temp")
    assert admin.delete_category(tokens.admin, empty) == 0


def test_dad_only_category_is_protected_from_ordinary_category_management(pg, tokens):
    dad = cat_id(pg, "Dad Only")
    with pytest.raises(ValidationError, match="protected"):
        admin.delete_category(tokens.admin, dad)
    admin.save_category(tokens.admin, category_id=dad, name="Dad's Corner", is_hidden=True, sort_order=1)   # hidden/order ignored
    row = pg.sql("select name, is_hidden, sort_order, kind from categories where id=%s", [dad])[0]
    assert row == ("Dad's Corner", False, 1000, "dad_only")


# ------------------------------------------------------------------ website content
def test_settings_persist_and_reach_other_sessions(pg, creds, tokens):
    admin.save_homepage(tokens.admin, eyebrow="e", heading="Twenty-One!", subtitle="s", message="m", button_label="Go")
    admin.save_wishlist_texts(tokens.admin, heading="My Gifts", intro="hi", currency="$")
    fresh = auth.login("Gift Giver", creds.family).token
    family.choose(fresh, "brother")
    s = content.get_settings(fresh)
    assert s["homepage"]["heading"] == "Twenty-One!" and s["homepage"]["button_label"] == "Go"
    assert s["wishlist"]["heading"] == "My Gifts" and s["wishlist"]["currency"] == "$"


def test_sections_save_and_drive_visibility(pg, tokens):
    rows = {"homepage": [("cta", True, 1), ("message", True, 2), ("portrait", False, 3)],
            "wishlist": [("grid", True, 1), ("intro", True, 2), ("search", False, 3), ("filters", True, 4)]}
    admin.save_sections(tokens.admin, rows)
    s = content.get_settings(tokens.mom)
    assert content.visible_sections(s, "homepage") == ["cta", "message"]
    assert content.visible_sections(s, "wishlist") == ["grid", "intro", "filters"]


@pytest.mark.parametrize("key,value", [
    ("security", {"idle_minutes": 100000}), ("dad_page", {"message": "x"}), ("homepage", {"evil_key": "x"}),
    ("homepage", {"heading": 5}), ("homepage", {"heading": "h" * 2001}), ("wishlist", []), ("sections", {"homepage": []}),
    ("sections", {"homepage": [{"id": "bogus", "visible": True}], "wishlist": []}),
    ("sections", {"homepage": [{"id": "cta", "visible": "yes"}], "wishlist": []}),
])
def test_settings_update_is_a_strict_allow_list(pg, tokens, key, value):
    before = pg.sql("select key, value::text from app_settings order by key")
    assert raw(pg, "settings_update", tokens.admin, {"p_key": key, "p_value": value}) == {"ok": False, "code": "invalid"}
    assert pg.sql("select key, value::text from app_settings order by key") == before


def test_dad_page_text_is_admin_editable_and_validated(pg, tokens):
    admin.save_dad_page(tokens.admin, title="Hey Dad", message="Come on! 🥹")
    assert admin.dad_page(tokens.admin) == {"title": "Hey Dad", "message": "Come on! 🥹"}
    for bad in (dict(title="", message="m"), dict(title="t", message=""), dict(title="t" * 81, message="m"), dict(title="t", message="m" * 1001)):
        with pytest.raises(ValidationError):
            admin.save_dad_page(tokens.admin, **bad)
    log = pg.sql("select action, details::text from audit_log where action='dad_page_update'")
    assert log and "Come on" not in log[0][1]                                                  # text not copied into the log


# ------------------------------------------------------------------ claims override + audit
def test_admin_can_release_a_claim_and_it_is_audited(pg, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    cid = pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'dad','$2a$secret') returning id::text", [pid])[0][0]
    assert snap(tokens).claims[0]["claimant"] == "Dad"
    admin.release_claim(tokens.admin, cid)
    row = pg.sql("select status, pin_hash, released_by from claims where id=%s", [cid])[0]
    assert row == ("released", None, "admin")
    assert not next(p for p in catalog.load_catalog(tokens.mom).products if p.id == pid).claimed
    with pytest.raises(ValidationError, match="already been released"):
        admin.release_claim(tokens.admin, cid)
    assert pg.sql("select count(*) from audit_log where action='claim_release'")[0][0] == 1


def test_audit_log_records_admin_actions_but_never_secrets(pg, creds, tokens):
    admin.save_category(tokens.admin, name="Audited")
    credentials.change(tokens.admin, ADMIN_PW, "family", "audit-secret-pin", "audit-secret-pin")
    admin_tok = auth.login("Birthday Girl", ADMIN_PW).token
    actions = [i["action"] for i in admin.recent_activity(admin_tok, 50)]
    assert "category_save" in actions and "credential_change" in actions
    dump = json.dumps(pg.sql("select actor, action, target, details::text from audit_log"))
    assert "audit-secret-pin" not in dump and ADMIN_PW not in dump


def test_snapshot_counts(pg, tokens, catalog_ids):
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'mom','$2a$x')", [catalog_ids["Gentle Cleanser"]])
    pg.sql("update products set is_archived=true where name='Poetry Collection'")
    s = snap(tokens)
    assert s.counts == {"active": 6, "archived": 1, "claimed": 1, "categories": 9} and s.available == 5
