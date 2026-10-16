"""Tests the LOGIC of scripts/check_supabase.py with doubles (MOCKED). They do not talk to Supabase: only running the
script against your real project does that."""
import importlib.util
import pathlib
import sys
from types import SimpleNamespace

import pytest

from tests.fakes import FakeStorage

spec = importlib.util.spec_from_file_location("check_supabase", pathlib.Path(__file__).resolve().parent.parent / "scripts/check_supabase.py")
cs = importlib.util.module_from_spec(spec)
sys.modules["check_supabase"] = cs
spec.loader.exec_module(cs)

BASE, BUCKET, SECRET = "https://p.supabase.co", "wishlist-images", "SERVICE-KEY-VALUE-1234567890"


class Call:
    def __init__(self, fn): self.fn = fn
    def execute(self): return SimpleNamespace(data=self.fn())


class FakeClient:
    def __init__(self, **kw):
        self.rpc_overrides = kw.get("rpc", {})
        self.rows = {"family_members": [{"slug": s} for s in ("grandmother", "brother", "mom", "dad")],
                     "categories": [{"kind": "regular"}, {"kind": "dad_only"}],
                     "app_settings": [{"key": k} for k in ("homepage", "wishlist", "sections", "dad_page", "security")],
                     "app_credentials": [{"kind": "admin", "enabled": True, "secret_hash": "$2a$10$x"},
                                         {"kind": "family", "enabled": True, "secret_hash": "$2a$10$y"},
                                         {"kind": "dad_only", "enabled": False, "secret_hash": None}]}
        self.rows.update(kw.get("rows", {}))
        self.bucket = SimpleNamespace(public=kw.get("public", False))
        self.storage = SimpleNamespace(get_bucket=lambda name: self.bucket)

    def rpc(self, name, params):
        def run():
            if name in self.rpc_overrides:
                out = self.rpc_overrides[name]
                if isinstance(out, Exception): raise out
                return out
            return {"valid": False} if name == "session_get" else {"ok": False, "code": "forbidden"}
        return Call(run)

    def table(self, name):
        rows = self.rows[name]
        return SimpleNamespace(select=lambda cols: Call(lambda: rows))


def good_http(method, url, headers=None, body=None):
    if "/storage/v1/object/public/" in url: return 400, ""
    if "signed.invalid" in url: return 200, "JFIF"
    if "/rest/v1/rpc/" in url: return 401, ""
    return 401, ""


def statuses(results): return {r.name: r.status for r in results}
def failures(results): return [r.name for r in results if r.status == cs.FAIL]


def test_a_correct_project_passes_every_check():
    res = cs.run_all(FakeClient(), FakeStorage(), good_http, BASE, BUCKET, anon_key="ANON")
    assert failures(res) == [] and any(r.status == cs.PASS for r in res)
    assert statuses(res)["Dad Only PIN is set"] == cs.SKIP                  # optional, reported as skipped


def test_a_missing_migration_is_named_with_the_file_to_run():
    res = cs.check_functions(FakeClient(rpc={"claim_create": RuntimeError("PGRST202 could not find function")}))
    bad = [r for r in res if r.status == cs.FAIL]
    assert len(bad) == 1 and "006_claims_and_dad.sql" in bad[0].detail and "RuntimeError" in bad[0].detail
    assert "PGRST202" not in bad[0].detail                                  # provider text never echoed


def test_a_function_that_answers_instead_of_refusing_is_flagged():
    res = cs.check_functions(FakeClient(rpc={"admin_snapshot": {"ok": True, "counts": {}}}))
    assert failures(res) == ["function admin_snapshot refuses a fake session"]


def test_missing_credentials_and_seed_data_are_flagged():
    client = FakeClient(rows={"app_credentials": [{"kind": "admin", "enabled": True, "secret_hash": None}],
                              "family_members": [{"slug": "mom"}]})
    f = failures(cs.check_seed_and_credentials(client))
    assert "admin credential is set" in f and "family credential is set" in f and "four family names exist" in f


def test_plaintext_looking_secrets_are_flagged():
    client = FakeClient(rows={"app_credentials": [{"kind": "admin", "enabled": True, "secret_hash": "my-plain-password"},
                                                  {"kind": "family", "enabled": True, "secret_hash": "$2a$10$z"}]})
    assert "stored secrets are bcrypt hashes" in failures(cs.check_seed_and_credentials(client))


def test_wrong_key_type_is_reported_without_leaking_it():
    class Denied(FakeClient):
        def table(self, name): raise PermissionError(f"permission denied using {SECRET}")
    res = cs.check_seed_and_credentials(Denied())
    assert failures(res) == ["read tables with the service key"] and SECRET not in cs.render(res)


def test_public_bucket_is_a_failure():
    assert failures(cs.check_bucket(FakeClient(public=True), BUCKET)) == ["bucket is PRIVATE"]
    assert failures(cs.check_bucket(FakeClient(public=False), BUCKET)) == []


def test_missing_bucket_points_to_the_sql_file():
    class NoBucket(FakeClient):
        def __init__(self):
            super().__init__(); self.storage = SimpleNamespace(get_bucket=lambda n: (_ for _ in ()).throw(KeyError("nope")))
    res = cs.check_bucket(NoBucket(), BUCKET)
    assert res[0].status == cs.FAIL and "999_storage_and_lockdown.sql" in res[0].detail


def test_anon_key_that_can_read_data_is_a_failure():
    def leaky(method, url, headers=None, body=None):
        return (200, '[{"kind":"admin"}]') if "/rest/v1/app_credentials" in url else good_http(method, url, headers, body)
    assert failures(cs.check_anon_blocked(leaky, BASE, "ANON")) == ["anon cannot read app_credentials"]
    assert failures(cs.check_anon_blocked(good_http, BASE, "ANON")) == []
    assert statuses(cs.check_anon_blocked(good_http, BASE, None)) == {"public (anon) key can access nothing": cs.SKIP}


def test_anon_that_can_call_a_function_is_a_failure():
    def open_rpc(method, url, headers=None, body=None):
        return (200, "{}") if "/rpc/auth_login" in url else good_http(method, url, headers, body)
    assert failures(cs.check_anon_blocked(open_rpc, BASE, "ANON")) == ["anon cannot call auth_login"]


def test_public_object_url_that_serves_the_image_is_a_failure():
    def public(method, url, headers=None, body=None):
        return (200, "JFIF") if "/object/public/" in url else good_http(method, url, headers, body)
    store = FakeStorage()
    assert failures(cs.check_storage_roundtrip(store, public, BASE, BUCKET)) == ["plain public URL does NOT serve it"]
    assert len(store.removed) == 1                                           # cleaned up even though a check failed


def test_signed_url_that_does_not_work_is_a_failure():
    def broken(method, url, headers=None, body=None):
        return (403, "") if "signed.invalid" in url else good_http(method, url, headers, body)
    assert failures(cs.check_storage_roundtrip(FakeStorage(), broken, BASE, BUCKET)) == ["signed URL serves the image"]


def test_upload_failure_is_reported_and_nothing_is_left_to_clean():
    store = FakeStorage(fail_upload=True)
    res = cs.check_storage_roundtrip(store, good_http, BASE, BUCKET)
    assert failures(res) == ["storage upload / sign / fetch"] and store.removed == []
    assert "secret-details" not in cs.render(res)


def test_test_image_is_always_deleted_after_a_successful_run():
    store = FakeStorage()
    res = cs.check_storage_roundtrip(store, good_http, BASE, BUCKET)
    assert failures(res) == [] and len(store.removed) == 1 and store.removed[0].startswith("product/")


def test_render_summarises_and_never_prints_secrets():
    res = cs.run_all(FakeClient(public=True), FakeStorage(), good_http, BASE, BUCKET, anon_key=SECRET)
    text = cs.render(res)
    assert "FAIL" in text and "failed" in text.splitlines()[-1] and SECRET not in text
