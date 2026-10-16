"""Authentication, sessions and credentials against the real SQL functions."""
import pytest

from wishlist import auth, credentials, family
from wishlist.security import PermissionDenied, ValidationError
from tests.conftest import ADMIN_PW, FAMILY_PIN


def sessions(pg):
    return pg.sql("select count(*) from sessions")[0][0]


def test_only_two_roles_exist_in_the_login_dropdown():
    assert list(auth.ROLE_LABELS) == ["Birthday Girl", "Gift Giver"]


def test_valid_admin_login_grants_admin(pg, creds):
    out = auth.login("Birthday Girl", ADMIN_PW)
    assert out.ok and out.token
    assert auth.require_admin(out.token).is_admin


def test_invalid_admin_credential_creates_no_session(pg, creds):
    out = auth.login("Birthday Girl", "wrong-password-xx")
    assert not out.ok and out.token is None and out.code == "invalid"
    assert sessions(pg) == 0


def test_valid_family_pin_needs_a_name_first(pg, creds):
    out = auth.login("Gift Giver", FAMILY_PIN)
    assert out.ok
    sess = auth.load_session(out.token)
    assert sess.role == "family" and sess.needs_name and not sess.is_admin
    with pytest.raises(PermissionDenied):
        auth.require_family(out.token)
    family.choose(out.token, "mom")
    assert auth.require_family(out.token).display_name == "Mom"


def test_invalid_family_pin_fails(pg, creds):
    assert not auth.login("Gift Giver", "000000").ok


def test_credentials_are_role_separated(pg, creds):
    assert not auth.login("Gift Giver", ADMIN_PW).ok       # admin password is not a family PIN
    assert not auth.login("Birthday Girl", FAMILY_PIN).ok  # family PIN is not an admin password


def test_unconfigured_credentials_never_log_anyone_in(pg):
    assert not auth.login("Birthday Girl", "anything-at-all").ok
    assert not auth.login("Gift Giver", "anything").ok


def test_logout_invalidates_the_session(pg, creds):
    tok = auth.login("Birthday Girl", ADMIN_PW).token
    assert auth.load_session(tok) is not None
    auth.logout(tok)
    assert auth.load_session(tok) is None
    with pytest.raises(PermissionDenied):
        auth.require_admin(tok)


def test_forged_or_empty_tokens_get_nothing(pg, creds):
    for bad in (None, "", "not-a-real-token", "A" * 43):
        assert auth.load_session(bad) is None
        with pytest.raises(PermissionDenied):
            auth.require_admin(bad)


def test_token_is_stored_only_as_a_hash(pg, creds):
    tok = auth.login("Birthday Girl", ADMIN_PW).token
    stored = [r[0] for r in pg.sql("select token_hash from sessions")]
    assert tok not in stored and auth.hash_token(tok) in stored


def test_family_session_cannot_use_admin_actions(pg, creds):
    tok = auth.login("Gift Giver", FAMILY_PIN).token
    family.choose(tok, "dad")
    with pytest.raises(PermissionDenied):
        auth.require_admin(tok)
    with pytest.raises(PermissionDenied):
        credentials.change(tok, ADMIN_PW, "family", "new-family-pin", "new-family-pin")
    with pytest.raises(PermissionDenied):
        family.rename_all(tok, {"grandmother": "G", "brother": "B", "mom": "M", "dad": "D"})
    # ...and the database itself refuses, even if the Python layer were bypassed:
    res = pg.rpc("credential_change", {"p_token_hash": auth.hash_token(tok), "p_admin_password": ADMIN_PW,
                                       "p_kind": "family", "p_new_secret": "hijacked-pin"}).execute().data
    assert res == {"ok": False, "code": "forbidden"}
    assert auth.login("Gift Giver", FAMILY_PIN).ok  # PIN unchanged


def test_admin_cannot_be_impersonated_by_editing_a_session_row_in_python_state(pg, creds):
    """Only a token the DB knows maps to a role; role claims in Python are never trusted."""
    tok = auth.login("Gift Giver", FAMILY_PIN).token
    family.choose(tok, "mom")
    sess = auth.load_session(tok)
    forged = auth.Session(sess.token_hash, "admin", None, None, False, False)  # attacker-built object
    assert forged.is_admin                                   # the object lies...
    assert not auth.load_session(tok).is_admin               # ...but every guard re-reads the DB
    with pytest.raises(PermissionDenied):
        auth.require_admin(tok)


def test_lockout_after_repeated_failures_blocks_even_the_right_secret(pg, creds):
    for _ in range(8):
        assert auth.login("Gift Giver", "bad-pin-000").code == "invalid"
    blocked = auth.login("Gift Giver", FAMILY_PIN)
    assert not blocked.ok and blocked.code == "locked" and blocked.retry_after > 0
    assert auth.login("Birthday Girl", ADMIN_PW).ok       # admin scope is independent
    pg.sql("update rate_limits set locked_until = now() - interval '1 second'")
    assert auth.login("Gift Giver", FAMILY_PIN).ok        # lock expires


def test_sessions_expire_when_idle_or_too_old(pg, creds):
    tok = auth.login("Birthday Girl", ADMIN_PW).token
    pg.sql("update sessions set last_seen = now() - interval '2 hours'")
    assert auth.load_session(tok) is None
    tok = auth.login("Birthday Girl", ADMIN_PW).token
    pg.sql("update sessions set expires_at = now() - interval '1 second'")
    assert auth.load_session(tok) is None
    assert sessions(pg) == 0


def test_secrets_are_stored_as_bcrypt_hashes_not_plaintext(pg, creds):
    rows = dict(pg.sql("select kind, secret_hash from app_credentials"))
    for secret, kind in ((ADMIN_PW, "admin"), (FAMILY_PIN, "family"), (creds.dad, "dad_only")):
        assert rows[kind].startswith("$2") and secret not in rows[kind]


def test_bootstrap_refuses_to_overwrite_without_rotate_flag(pg, creds):
    res = pg.rpc("credential_bootstrap", {"p_kind": "admin", "p_secret": "another-long-password"}).execute().data
    assert res["code"] == "already_set"
    assert auth.login("Birthday Girl", ADMIN_PW).ok
    forced = pg.rpc("credential_bootstrap", {"p_kind": "admin", "p_secret": "another-long-password",
                                             "p_force": True}).execute().data
    assert forced["ok"] and not auth.login("Birthday Girl", ADMIN_PW).ok


def test_changing_family_pin_requires_admin_password_and_signs_family_out(pg, creds):
    admin = auth.login("Birthday Girl", ADMIN_PW).token
    fam = auth.login("Gift Giver", FAMILY_PIN).token
    with pytest.raises(ValidationError):
        credentials.change(admin, "wrong-admin-pass!", "family", "brand-new-pin", "brand-new-pin")
    assert auth.login("Gift Giver", FAMILY_PIN).ok       # unchanged after the failed attempt
    with pytest.raises(ValidationError):
        credentials.change(admin, ADMIN_PW, "family", "abc", "abc")           # too short (client rule)
    with pytest.raises(ValidationError):
        credentials.change(admin, ADMIN_PW, "family", "brand-new-pin", "different-pin")
    credentials.change(admin, ADMIN_PW, "family", "brand-new-pin", "brand-new-pin")
    assert auth.load_session(fam) is None                # old family sessions are revoked
    assert not auth.login("Gift Giver", FAMILY_PIN).ok and auth.login("Gift Giver", "brand-new-pin").ok
    assert auth.load_session(admin) is not None          # admin stays signed in


def test_changing_admin_password_revokes_other_admin_sessions(pg, creds):
    a1 = auth.login("Birthday Girl", ADMIN_PW).token
    a2 = auth.login("Birthday Girl", ADMIN_PW).token
    credentials.change(a1, ADMIN_PW, "admin", "a-brand-new-password", "a-brand-new-password")
    assert auth.load_session(a1) and auth.load_session(a2) is None
    assert auth.login("Birthday Girl", "a-brand-new-password").ok


def test_admin_login_cannot_be_disabled_and_dad_pin_can_be_toggled(pg, creds):
    admin = auth.login("Birthday Girl", ADMIN_PW).token
    with pytest.raises(ValidationError):
        credentials.change(admin, ADMIN_PW, "admin", enabled=False)
    credentials.change(admin, ADMIN_PW, "dad_only", enabled=False)
    states = {i["kind"]: i for i in credentials.status(admin)}
    assert states["dad_only"]["enabled"] is False and states["dad_only"]["configured"] is True
    assert "secret" not in str(states) and "hash" not in str(states)   # status never exposes secrets


def test_reauth_attempts_are_rate_limited(pg, creds):
    admin = auth.login("Birthday Girl", ADMIN_PW).token
    for _ in range(5):
        with pytest.raises(ValidationError):
            credentials.change(admin, "nope-nope-nope!", "family", "brand-new-pin", "brand-new-pin")
    with pytest.raises(ValidationError, match="Too many"):
        credentials.change(admin, ADMIN_PW, "family", "brand-new-pin", "brand-new-pin")


def test_family_names_swap_atomically_and_reject_duplicates(pg, creds):
    admin = auth.login("Birthday Girl", ADMIN_PW).token
    family.rename_all(admin, {"grandmother": "Nani", "brother": "Bhai", "mom": "Dad", "dad": "Mom"})  # swap
    names = {i["slug"]: i["display_name"] for i in family.list_names(admin)}
    assert names == {"grandmother": "Nani", "brother": "Bhai", "mom": "Dad", "dad": "Mom"}
    with pytest.raises(ValidationError):
        family.rename_all(admin, {"grandmother": "Same", "brother": "same", "mom": "M", "dad": "D"})
    with pytest.raises(ValidationError):
        family.rename_all(admin, {"grandmother": "", "brother": "B", "mom": "M", "dad": "D"})
    assert {i["slug"]: i["display_name"] for i in family.list_names(admin)} == names   # unchanged


def test_logged_out_visitors_cannot_read_family_names(pg, creds):
    with pytest.raises(PermissionDenied):
        family.list_names(None)
    with pytest.raises(PermissionDenied):
        family.list_names("forged-token")


def test_anon_and_authenticated_roles_have_no_access_at_all(pg):
    """Even if the public anon key leaked, it could read or call nothing."""
    import psycopg

    with psycopg.connect(pg.dsn, autocommit=True) as conn:
        for role in ("anon", "authenticated"):
            conn.execute(f"set role {role}")
            for q in ("select * from public.app_credentials", "select * from public.products",
                      "select public.auth_login('admin','x','" + "a" * 40 + "')",
                      "select public.credential_bootstrap('admin','x' || 'y')"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(q)
            conn.execute("reset role")


def test_every_public_table_has_rls_enabled(pg):
    rows = pg.sql("select tablename from pg_tables where schemaname='public' and not rowsecurity")
    assert rows == []


def test_private_bucket_configuration(pg):
    row = pg.sql("select public, file_size_limit, allowed_mime_types from storage.buckets where id='wishlist-images'")[0]
    assert row[0] is False and row[1] == 5 * 1024 * 1024 and set(row[2]) == {"image/jpeg", "image/png", "image/webp"}
