"""Browser (Playwright) end-to-end tests. They start the REAL app (scripts/dev_harness.py) against a LOCAL PostgreSQL with
sample data and placeholder images - never against Supabase.

Setup (once):   pip install playwright && playwright install chromium
Run:            TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest e2e -q

Optional: E2E_CHROMIUM_PATH=/path/to/chromium (and E2E_CHROMIUM_ARGS=/path/args.json) to use an existing browser.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from types import SimpleNamespace

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from tests.conftest import (ADMIN_PW, DAD_PIN, FAMILY_PIN, RESET_TABLES, ROOT, SQL_ORDER, PgClient,  # noqa: E402
                            seed_catalog)

expect.set_options(timeout=20_000)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def db_dsn():
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute("drop database if exists wishlist_test with (force)")
        admin.execute("create database wishlist_test")
    dsn = base.rsplit("/", 1)[0] + "/wishlist_test"
    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in SQL_ORDER:
            conn.execute(f.read_text())
    return dsn


@pytest.fixture(scope="session")
def base_url(db_dsn):
    port = _free_port()
    env = {**os.environ, "TEST_DATABASE_URL": db_dsn.rsplit("/", 1)[0] + "/postgres", "APP_ENV": "dev"}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "scripts/dev_harness.py", "--server.port", str(port),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if urllib.request.urlopen(f"{url}/_stcore/health", timeout=2).status == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("Streamlit did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def _playwright():
    with sync_playwright() as p:
        yield p


@pytest.fixture
def browser(_playwright):
    """A fresh browser per test: slower by ~1 s, but isolated and robust for any Chromium build."""
    kwargs = {"headless": True}
    if os.environ.get("E2E_CHROMIUM_PATH"):
        kwargs["executable_path"] = os.environ["E2E_CHROMIUM_PATH"]
        if os.environ.get("E2E_CHROMIUM_ARGS"):
            kwargs["args"] = json.load(open(os.environ["E2E_CHROMIUM_ARGS"]))
    b = _playwright.chromium.launch(**kwargs)
    yield b
    try:
        b.close()
    except Exception:
        pass


@pytest.fixture
def data(db_dsn):
    """Fresh sample data for each test (credentials, catalogue, one existing claim)."""
    pg = PgClient(db_dsn)
    pg.sql(f"truncate {RESET_TABLES} restart identity cascade")
    pg.sql((ROOT / "sql/002_seed.sql").read_text())
    for kind, secret in (("admin", ADMIN_PW), ("family", FAMILY_PIN), ("dad_only", DAD_PIN)):
        pg.rpc("credential_bootstrap", {"p_kind": kind, "p_secret": secret}).execute()
    ids = seed_catalog(pg)
    pg.sql("insert into claims (product_id, family_slug, pin_hash) values (%s,'mom',crypt('1357', gen_salt('bf', 6)))"
           .replace("crypt(", "extensions.crypt(").replace("gen_salt(", "extensions.gen_salt("), [ids["Linen Summer Dress"]])
    return SimpleNamespace(pg=pg, ids=ids)


@pytest.fixture
def page(browser, base_url, data):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.base = base_url
    yield pg
    ctx.close()


@pytest.fixture
def mobile(browser, base_url, data):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    pg.base = base_url
    yield pg
    ctx.close()
