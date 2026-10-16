"""Test harness. SQL-backed tests run the REAL migrations on a real PostgreSQL.

    export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
    pytest

Without TEST_DATABASE_URL those tests are skipped (the pure-logic tests still run).
"""
from __future__ import annotations

import json
import os
import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_ORDER = [ROOT / "tests/sql/00_supabase_stubs.sql", *sorted((ROOT / "sql").glob("*.sql"))]
RESET_TABLES = ("app_settings, app_credentials, rate_limits, family_members, claims, "
                "product_links, products, categories, sessions, audit_log")

ADMIN_PW = "correct-horse-battery"      # 12+ chars
FAMILY_PIN = "family-pin-2026"
DAD_PIN = "dad-secret-2026"


class _Resp(SimpleNamespace):
    pass


class _RpcCall:
    def __init__(self, dsn, name, params):
        self.dsn, self.name, self.params = dsn, name, params

    def execute(self):
        import psycopg

        keys = list(self.params)
        holders = ", ".join(f"{k} => %s{'::jsonb' if isinstance(self.params[k], (dict, list)) else ''}" for k in keys)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in self.params.values()]
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            row = conn.execute(f"select public.{self.name}({holders})", values).fetchone()
        return _Resp(data=row[0] if row else None)


class PgClient:
    """Minimal supabase-py look-alike: client.rpc(name, params).execute().data -> real SQL function call."""

    def __init__(self, dsn):
        self.dsn = dsn

    def rpc(self, name, params=None):
        return _RpcCall(self.dsn, name, params or {})

    # direct SQL for assertions / setup
    def sql(self, query, params=None):
        import psycopg

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            cur = conn.execute(query, params or [])
            return cur.fetchall() if cur.description else None


@pytest.fixture(scope="session")
def pg_dsn():
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL not set - skipping SQL-backed tests")
    import psycopg

    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute("drop database if exists wishlist_test with (force)")
        admin.execute("create database wishlist_test")
    dsn = base.rsplit("/", 1)[0] + "/wishlist_test"
    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in SQL_ORDER:
            conn.execute(f.read_text())
    return dsn


@pytest.fixture
def pg(pg_dsn):
    """Fresh data for every test + the app's db layer pointed at the real database."""
    from wishlist import db

    client = PgClient(pg_dsn)
    client.sql(f"truncate {RESET_TABLES} restart identity cascade")
    client.sql((ROOT / "sql/002_seed.sql").read_text())
    db.set_client(client)
    yield client
    db.set_client(None)


@pytest.fixture
def creds(pg):
    """Admin password, family PIN and Dad Only PIN configured (hashed by the DB)."""
    for kind, secret in (("admin", ADMIN_PW), ("family", FAMILY_PIN), ("dad_only", DAD_PIN)):
        assert pg.rpc("credential_bootstrap", {"p_kind": kind, "p_secret": secret}).execute().data["ok"]
    return SimpleNamespace(admin=ADMIN_PW, family=FAMILY_PIN, dad=DAD_PIN)


# ---------------------------------------------------------------- sample catalogue (dev + tests)
def seed_catalog(client):
    """Insert a small, clearly-sample catalogue. Returns {name: product_id}. DEV/TEST ONLY."""
    cat = {name: cid for name, cid in client.sql("select name, id::text from categories")}
    rows = [  # name, category, pmin, pmax, short, prefs, notes, image
        ("Rose Quartz Lip Gloss", "Makeup", 450, 900, "A glossy, juicy pink", "Shade: Rose Petal. Finish: glossy.", "Any brand is fine!", "product/" + "a" * 32 + ".jpg"),
        ("Linen Summer Dress", "Clothing", 2500, 4500, "Soft linen, midi length", "Size M. Colour: blush or cream.", "", "product/" + "b" * 32 + ".jpg"),
        ("Gentle Cleanser", "Skincare", 600, 600, "For sensitive skin", "Fragrance free", "", None),
        ("Poetry Collection", "Books", None, None, "A beautiful hardcover", "", "Hardcover please", "product/" + "c" * 32 + ".jpg"),
        ("Bluetooth Speaker", "Electronics", 3000, 8000, "Pastel colours", "Waterproof", "", None),
        ("Dog Squeaky Toy", "My Dog", 150, 300, "For the real princess", "", "", "product/" + "d" * 32 + ".jpg"),
        ("Mystery Treat Box", None, 1200, None, "Surprise me", "", "", None),
    ]
    ids = {}
    for name, c, lo, hi, short, prefs, notes, img in rows:
        pid = client.sql(
            "insert into products (name, category_id, price_min, price_max, short_description, preferences, notes, image_path) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id::text",
            [name, cat.get(c), lo, hi, short, prefs, notes, img])[0][0]
        ids[name] = pid
    client.sql("insert into product_links (product_id, source_name, url, note, sort_order) values "
               "(%s,'Nykaa','https://www.nykaa.com/example','Cheaper here',2),(%s,'Amazon','https://www.amazon.in/example','',1)",
               [ids["Rose Quartz Lip Gloss"], ids["Rose Quartz Lip Gloss"]])
    client.sql("update app_settings set value = jsonb_set(value, '{portrait_path}', to_jsonb(%s::text)) where key='homepage'",
               ["portrait/" + "e" * 32 + ".jpg"])
    return ids


@pytest.fixture
def tokens(pg, creds):
    """Logged-in tokens: admin, plus family sessions for Mom and Dad."""
    from wishlist import auth, family

    def fam(slug):
        t = auth.login("Gift Giver", creds.family).token
        family.choose(t, slug)
        return t
    return SimpleNamespace(admin=auth.login("Birthday Girl", creds.admin).token, mom=fam("mom"), dad=fam("dad"))


@pytest.fixture
def catalog_ids(pg):
    return seed_catalog(pg)


@pytest.fixture
def fake_storage():
    from tests.fakes import FakeStorage
    from wishlist import storage

    fake = FakeStorage()
    storage.set_backend(fake)
    yield fake
    storage.set_backend(None)
