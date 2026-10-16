"""Read-path authorization and database integrity, on a REAL PostgreSQL (local, not Supabase)."""
import json
import threading

import psycopg
import pytest

from wishlist import auth, catalog, content
from wishlist.security import PermissionDenied


# ------------------------------------------------------------------ read-path authorization
@pytest.mark.parametrize("bad", [None, "", "forged-token"])
def test_logged_out_visitors_get_no_catalog_and_no_settings(pg, creds, catalog_ids, bad):
    with pytest.raises(PermissionDenied):
        catalog.load_catalog(bad)
    with pytest.raises(PermissionDenied):
        content.get_settings(bad)


def test_family_session_without_a_name_gets_nothing(pg, creds, catalog_ids):
    tok = auth.login("Gift Giver", creds.family).token          # PIN ok, name not chosen yet
    with pytest.raises(PermissionDenied):
        catalog.load_catalog(tok)
    with pytest.raises(PermissionDenied):
        content.get_settings(tok)


def test_catalog_contains_products_links_and_status(pg, tokens, catalog_ids):
    cat = catalog.load_catalog(tokens.mom)
    assert len(cat.products) == 7
    gloss = next(p for p in cat.products if p.name == "Rose Quartz Lip Gloss")
    assert [l.source_name for l in gloss.links] == ["Amazon", "Nykaa"]        # ordered by sort_order
    assert gloss.links[1].note == "Cheaper here" and gloss.category_name == "Makeup"
    assert not gloss.claimed


def test_claim_status_is_derived_from_the_active_claim(pg, tokens, catalog_ids):
    pid = catalog_ids["Linen Summer Dress"]
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'brother','$2a$x')", [pid])
    dress = next(p for p in catalog.load_catalog(tokens.mom).products if p.id == pid)
    assert dress.claimed and dress.claimed_by == "Brother" and dress.status == "Claimed"
    pg.sql("update claims set status='released', pin_hash=null, released_at=now(), released_by='admin'")
    dress = next(p for p in catalog.load_catalog(tokens.mom).products if p.id == pid)
    assert not dress.claimed and dress.claimed_by is None


def test_catalog_json_never_contains_pin_hashes(pg, tokens, catalog_ids):
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'mom','$2a$10$SECRETHASH')",
           [catalog_ids["Gentle Cleanser"]])
    raw = pg.rpc("catalog_list", {"p_token_hash": auth.hash_token(tokens.mom)}).execute().data
    assert "SECRETHASH" not in json.dumps(raw) and "pin_hash" not in json.dumps(raw)


def test_archived_products_and_hidden_categories_are_invisible(pg, tokens, catalog_ids):
    pg.sql("update products set is_archived = true, archived_at = now() where id = %s", [catalog_ids["Gentle Cleanser"]])
    pg.sql("update categories set is_hidden = true where name = 'Electronics'")
    cat = catalog.load_catalog(tokens.mom)
    shown = {p.name for p in cat.products}
    assert "Gentle Cleanser" not in shown and "Bluetooth Speaker" not in shown       # archived / hidden category
    assert "Electronics" not in {c.name for c in cat.categories}
    assert "Mystery Treat Box" in shown                                              # uncategorised stays visible


def test_dad_only_category_is_returned_only_to_dad_and_admin(pg, tokens, catalog_ids):
    def cat_names(t):
        return {c.name for c in catalog.load_catalog(t).categories}
    assert "Dad Only" not in cat_names(tokens.mom)
    assert "Dad Only" in cat_names(tokens.dad)
    assert "Dad Only" in cat_names(tokens.admin)
    # ordinary categories are still fully available to Dad
    assert {"Clothing", "Makeup", "Books"} <= cat_names(tokens.dad)


def test_switching_name_changes_what_the_session_sees(pg, creds, catalog_ids):
    from wishlist import family
    t = auth.login("Gift Giver", creds.family).token
    family.choose(t, "dad")
    assert "Dad Only" in {c.name for c in catalog.load_catalog(t).categories}
    family.choose(t, "mom")
    assert "Dad Only" not in {c.name for c in catalog.load_catalog(t).categories}


def test_settings_are_an_allow_list_and_never_leak_the_dad_message(pg, tokens):
    raw = pg.rpc("settings_get", {"p_token_hash": auth.hash_token(tokens.dad)}).execute().data
    assert set(raw["settings"]) == {"homepage", "wishlist", "sections"}
    assert "birthday to remember" not in json.dumps(raw) and "idle_minutes" not in json.dumps(raw)
    merged = content.get_settings(tokens.mom)
    assert merged["homepage"]["heading"] == "Happy 21st Birthday!" and merged["wishlist"]["currency"] == "₹"


def test_section_order_and_visibility_are_respected_and_forward_compatible():
    s = {"sections": {"wishlist": [{"id": "grid", "visible": True}, {"id": "search", "visible": False},
                                   {"id": "bogus", "visible": True}, {"id": "intro", "visible": True}]}}
    assert content.visible_sections(s, "wishlist") == ["grid", "intro", "filters"]   # filters appended, bogus ignored
    assert content.visible_sections({}, "homepage") == ["portrait", "message", "cta"]


# ------------------------------------------------------------------ integrity: rules the DB itself enforces
def test_dad_only_category_cannot_hold_products_or_be_deleted(pg):
    dad_cat = pg.sql("select id::text from categories where kind='dad_only'")[0][0]
    with pytest.raises(psycopg.errors.RaiseException):
        pg.sql("insert into products (name, category_id) values ('Sneaky', %s)", [dad_cat])
    with pytest.raises(psycopg.errors.RaiseException):
        pg.sql("delete from categories where id = %s", [dad_cat])
    with pytest.raises(psycopg.errors.RaiseException):
        pg.sql("update categories set kind='regular' where id = %s", [dad_cat])
    with pytest.raises(psycopg.errors.UniqueViolation):                       # only one Dad Only category, ever
        pg.sql("insert into categories (name, kind) values ('Another', 'dad_only')")


def test_product_check_constraints(pg):
    bad = [("''", "null", "null"), ("'x'", "-1", "null"), ("'x'", "500", "100")]   # blank name / negative / min>max
    for name, lo, hi in bad:
        with pytest.raises(psycopg.errors.CheckViolation):
            pg.sql(f"insert into products (name, price_min, price_max) values ({name}, {lo}, {hi})")
    pg.sql("insert into products (name, price_min, price_max) values ('ok', 100, 100)")   # equal is fine


def test_category_names_are_unique_ignoring_case_and_spaces(pg):
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg.sql("insert into categories (name) values ('  makeup ')")


def test_category_with_products_cannot_be_deleted(pg, catalog_ids):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg.sql("delete from categories where name = 'Makeup'")


def test_product_links_must_be_http_or_https(pg, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    for url in ("javascript:alert(1)", "ftp://x.y/z", "https://a b.c", "not a url"):
        with pytest.raises(psycopg.errors.CheckViolation):
            pg.sql("insert into product_links (product_id, source_name, url) values (%s,'X',%s)", [pid, url])
    pg.sql("insert into product_links (product_id, source_name, url) values (%s,'Ok','https://shop.example/p?a=1')", [pid])


def test_links_are_deleted_with_their_product_but_claimed_products_cannot_be_deleted(pg, catalog_ids):
    gloss = catalog_ids["Rose Quartz Lip Gloss"]
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'mom','$2a$x')", [gloss])
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg.sql("delete from products where id = %s", [gloss])               # history is protected
    pg.sql("update claims set status='released', pin_hash=null, released_at=now()")
    pg.sql("delete from claims")
    pg.sql("delete from products where id = %s", [gloss])
    assert pg.sql("select count(*) from product_links where product_id = %s", [gloss])[0][0] == 0


def test_at_most_one_active_claim_per_product_but_history_is_allowed(pg, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'mom','$2a$x')", [pid])
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'dad','$2a$y')", [pid])
    pg.sql("update claims set status='released', pin_hash=null, released_at=now(), released_by='claimant'")
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'dad','$2a$y')", [pid])
    assert pg.sql("select count(*) from claims where product_id=%s", [pid])[0][0] == 2


def test_claim_rows_cannot_be_in_an_inconsistent_state(pg, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    with pytest.raises(psycopg.errors.CheckViolation):          # active claim must have a PIN hash
        pg.sql("insert into claims (product_id, family_slug) values (%s,'mom')", [pid])
    with pytest.raises(psycopg.errors.CheckViolation):          # released claim must NOT keep its hash
        pg.sql("insert into claims (product_id, family_slug, pin_hash, status, released_at) "
               "values (%s,'mom','$2a$x','released', now())", [pid])
    with pytest.raises(psycopg.errors.ForeignKeyViolation):     # unknown family member
        pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'nobody','$2a$x')", [pid])


def test_concurrent_inserts_cannot_create_two_active_claims(pg, catalog_ids):
    """Race 12 connections at the same product. The unique index must let exactly one through."""
    pid = catalog_ids["Gentle Cleanser"]
    barrier, results = threading.Barrier(12), []

    def attempt(slug):
        try:
            with psycopg.connect(pg.dsn, autocommit=True) as conn:
                barrier.wait()
                conn.execute("insert into claims (product_id, family_slug, pin_hash) values (%s,%s,'$2a$x')", [pid, slug])
            results.append("ok")
        except psycopg.errors.UniqueViolation:
            results.append("duplicate")

    threads = [threading.Thread(target=attempt, args=(["mom", "dad", "brother", "grandmother"][i % 4],)) for i in range(12)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("duplicate") == 11
    assert pg.sql("select count(*) from claims where product_id=%s and status='active'", [pid])[0][0] == 1
