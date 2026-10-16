"""Dad Only access matrix against REAL local PostgreSQL."""
import json

import pytest

from wishlist import admin, auth, catalog, credentials, dad, family
from wishlist.security import PermissionDenied, ValidationError
from tests.conftest import ADMIN_PW, DAD_PIN

MESSAGE = "birthday to remember"


def sess(creds, slug):
    t = auth.login("Gift Giver", creds.family).token
    if slug:
        family.choose(t, slug)
    return t


def can_read(token):
    try:
        return MESSAGE in dad.get_page(token).get("message", "")
    except PermissionDenied:
        return False


def cat_names(t):
    return {c.name for c in catalog.load_catalog(t).categories}


def test_access_matrix_only_unlocked_dad_and_admin_can_read(pg, creds, tokens):
    nameless = sess(creds, None)
    others = {s: sess(creds, s) for s in ("mom", "brother", "grandmother")}
    locked_dad, unlocked_dad = sess(creds, "dad"), sess(creds, "dad")
    dad.unlock(unlocked_dad, DAD_PIN)
    for denied in (None, "forged", nameless, locked_dad, *others.values()):
        assert not can_read(denied), denied
    assert can_read(unlocked_dad) and can_read(tokens.admin)


def test_choosing_dads_name_without_the_pin_grants_nothing(pg, creds):
    t = sess(creds, "dad")
    assert not can_read(t)
    with pytest.raises(ValidationError):
        dad.unlock(t, "wrong-pin-123")
    with pytest.raises(ValidationError):
        dad.unlock(t, "")
    assert not can_read(t)
    dad.unlock(t, DAD_PIN)
    assert can_read(t)


def test_other_family_members_cannot_even_attempt_an_unlock(pg, creds):
    for slug in ("mom", "brother", "grandmother"):
        t = sess(creds, slug)
        with pytest.raises(PermissionDenied):
            dad.unlock(t, DAD_PIN)                                    # correct PIN, wrong name: still refused
        res = pg.rpc("dad_unlock", {"p_token_hash": auth.hash_token(t), "p_pin": DAD_PIN}).execute().data
        assert res == {"ok": False, "code": "forbidden"} and not can_read(t)


def test_family_pin_and_admin_password_are_not_the_dad_pin(pg, creds):
    t = sess(creds, "dad")
    for wrong in (creds.family, ADMIN_PW):
        with pytest.raises(ValidationError):
            dad.unlock(t, wrong)
    assert not can_read(t)


def test_switching_names_relocks_the_page(pg, creds):
    t = sess(creds, "dad")
    dad.unlock(t, DAD_PIN)
    assert can_read(t)
    family.choose(t, "mom")                                            # someone else now uses this session
    assert not can_read(t) and "Dad Only" not in cat_names(t)
    family.choose(t, "dad")
    assert not can_read(t)                                             # back to Dad: must enter the PIN again


def test_unlock_does_not_leak_to_other_sessions(pg, creds):
    a, b = sess(creds, "dad"), sess(creds, "dad")
    dad.unlock(a, DAD_PIN)
    assert can_read(a) and not can_read(b)


def test_disabling_the_page_locks_everyone_out_immediately(pg, creds, tokens):
    t = sess(creds, "dad")
    dad.unlock(t, DAD_PIN)
    assert can_read(t) and "Dad Only" in cat_names(t)
    credentials.change(tokens.admin, ADMIN_PW, "dad_only", enabled=False)
    assert not can_read(t) and "Dad Only" not in cat_names(t)
    assert can_read(tokens.admin) and "Dad Only" in cat_names(tokens.admin)      # admin can still preview/edit
    with pytest.raises(ValidationError, match="isn't open"):
        dad.unlock(t, DAD_PIN)
    credentials.change(tokens.admin, ADMIN_PW, "dad_only", enabled=True)
    assert not can_read(t)                                              # disabling re-locked every session; re-enabling does not unlock them
    dad.unlock(t, DAD_PIN)
    assert can_read(t)


def test_changing_the_dad_pin_revokes_unlocked_sessions(pg, creds, tokens):
    t = sess(creds, "dad")
    dad.unlock(t, DAD_PIN)
    credentials.change(tokens.admin, ADMIN_PW, "dad_only", "brand-new-dad-pin", "brand-new-dad-pin")
    assert not can_read(t)
    with pytest.raises(ValidationError):
        dad.unlock(t, DAD_PIN)
    dad.unlock(t, "brand-new-dad-pin")
    assert can_read(t)


def test_unconfigured_dad_pin_means_nobody_gets_in(pg):
    from wishlist import credentials as _c
    pg.rpc("credential_bootstrap", {"p_kind": "family", "p_secret": "family-pin-2026"}).execute()
    t = auth.login("Gift Giver", "family-pin-2026").token
    family.choose(t, "dad")
    with pytest.raises(ValidationError, match="isn't open"):
        dad.unlock(t, "anything-at-all")
    assert not can_read(t) and "Dad Only" not in cat_names(t)


def test_guessing_the_pin_is_rate_limited_per_session_and_globally(pg, creds):
    t = sess(creds, "dad")
    for _ in range(5):
        with pytest.raises(ValidationError, match="didn't match"):
            dad.unlock(t, "guess-000000")
    with pytest.raises(ValidationError, match="Too many"):
        dad.unlock(t, DAD_PIN)                                         # correct PIN is refused while locked
    other = sess(creds, "dad")                                          # global limiter protects against fresh sessions too
    with pytest.raises(ValidationError, match="Too many"):
        dad.unlock(other, DAD_PIN)
    pg.sql("update rate_limits set locked_until = now() - interval '1 second'")
    dad.unlock(other, DAD_PIN)
    assert can_read(other)


def test_dad_keeps_full_access_to_the_ordinary_wishlist(pg, creds, catalog_ids):
    locked, unlocked = sess(creds, "dad"), sess(creds, "dad")
    dad.unlock(unlocked, DAD_PIN)
    for t in (locked, unlocked):
        assert len(catalog.load_catalog(t).products) == 7
        assert {"Clothing", "Makeup", "Books"} <= cat_names(t)
    from wishlist import claims
    claims.claim(locked, catalog_ids["Gentle Cleanser"], "dad", "1234", "1234")   # and can claim like anyone else


def test_the_private_text_never_appears_in_any_other_response(pg, creds, tokens, catalog_ids):
    for slug in ("mom", "dad"):
        t = sess(creds, slug)
        h = auth.hash_token(t)
        for fn in ("catalog_list", "settings_get", "family_list", "session_get"):
            assert MESSAGE not in json.dumps(pg.rpc(fn, {"p_token_hash": h}).execute().data)
    assert MESSAGE not in json.dumps(pg.rpc("catalog_list", {"p_token_hash": auth.hash_token(tokens.admin)}).execute().data)


def test_forged_python_objects_cannot_bypass_the_server_check(pg, creds):
    t = sess(creds, "mom")
    real = auth.load_session(t)
    forged = auth.Session(real.token_hash, "admin", "dad", "Dad", True, True)     # attacker-built, claims everything
    assert forged.is_admin and forged.dad_unlocked
    assert not can_read(t)                                                         # but the token is what's checked, by the DB
    with pytest.raises(PermissionDenied):
        dad.get_page(t)


def test_pin_is_stored_hashed_and_unlock_is_audited_without_it(pg, creds):
    t = sess(creds, "dad")
    dad.unlock(t, DAD_PIN)
    h = pg.sql("select secret_hash from app_credentials where kind='dad_only'")[0][0]
    assert h.startswith("$2") and DAD_PIN not in h
    assert [r[0] for r in pg.sql("select action from audit_log where action='dad_unlock'")] == ["dad_unlock"]
    assert DAD_PIN not in str(pg.sql("select * from audit_log")) + str(pg.sql("select * from rate_limits"))
