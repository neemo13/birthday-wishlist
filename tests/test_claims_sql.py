"""Gift claiming and releasing against REAL local PostgreSQL (through the same Python layer the app uses)."""
import threading

import pytest

from wishlist import auth, catalog, claims, family
from wishlist.claims import ClaimError
from wishlist.security import PermissionDenied, ValidationError
from tests.conftest import ADMIN_PW

PIN = "2468"


def session_for(creds, slug):
    t = auth.login("Gift Giver", creds.family).token
    family.choose(t, slug)
    return t


def find(tok, pid):
    return next(p for p in catalog.load_catalog(tok).products if p.id == pid)


def claim_row(pg, pid):
    return pg.sql("select status, family_slug, pin_hash, released_at, released_by from claims where product_id=%s order by created_at", [pid])


# ------------------------------------------------------------------ claiming
def test_valid_claim_succeeds_and_shows_the_claimant(pg, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.mom, pid, "mom", PIN, PIN)
    p = find(tokens.dad, pid)
    assert p.claimed and p.claimed_by == "Mom" and p.status == "Claimed"


def test_pin_is_hashed_never_plaintext_and_never_logged_in_db(pg, creds, tokens, catalog_ids):
    claims.claim(tokens.mom, catalog_ids["Gentle Cleanser"], "mom", PIN, PIN)
    (status, slug, pin_hash, *_), = claim_row(pg, catalog_ids["Gentle Cleanser"])
    assert pin_hash.startswith("$2") and PIN not in pin_hash
    everywhere = str(pg.sql("select * from audit_log")) + str(pg.sql("select * from rate_limits")) + str(pg.sql("select * from sessions"))
    assert PIN not in everywhere


def test_two_claims_with_the_same_pin_get_different_hashes(pg, tokens, catalog_ids):
    claims.claim(tokens.mom, catalog_ids["Gentle Cleanser"], "mom", PIN, PIN)
    claims.claim(tokens.mom, catalog_ids["Dog Squeaky Toy"], "mom", PIN, PIN)
    hashes = [r[0] for r in pg.sql("select pin_hash from claims")]
    assert len(set(hashes)) == 2                                     # salted: each gift has its own credential


def test_one_person_can_hold_several_claims_with_different_pins(pg, creds, tokens, catalog_ids):
    a, b = catalog_ids["Gentle Cleanser"], catalog_ids["Dog Squeaky Toy"]
    claims.claim(tokens.mom, a, "mom", "1111", "1111")
    claims.claim(tokens.mom, b, "mom", "9999", "9999")
    with pytest.raises(ClaimError):
        claims.release(tokens.dad, a, "Mom", "9999")                 # B's PIN does not open A
    claims.release(tokens.dad, a, "Mom", "1111")
    assert not find(tokens.mom, a).claimed and find(tokens.mom, b).claimed


def test_second_claim_on_the_same_gift_fails_and_changes_nothing(pg, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.mom, pid, "mom", PIN, PIN)
    before = claim_row(pg, pid)
    for who, slug in ((tokens.dad, "dad"), (tokens.mom, "mom")):
        with pytest.raises(ClaimError) as err:
            claims.claim(who, pid, slug, "1357", "1357")
        assert err.value.code == "already_claimed"
    assert claim_row(pg, pid) == before and find(tokens.dad, pid).claimed_by == "Mom"


@pytest.mark.parametrize("pin,confirm", [("abc", "abc"), ("123", "123"), ("123456789", "123456789"), ("12 34", "12 34"), ("", "")])
def test_invalid_pins_are_rejected_without_leaving_a_claim(pg, tokens, catalog_ids, pin, confirm):
    with pytest.raises(ValidationError):
        claims.claim(tokens.mom, catalog_ids["Gentle Cleanser"], "mom", pin, confirm)
    assert pg.sql("select count(*) from claims")[0][0] == 0


def test_pin_confirmation_must_match(pg, tokens, catalog_ids):
    with pytest.raises(ValidationError):
        claims.claim(tokens.mom, catalog_ids["Gentle Cleanser"], "mom", "1234", "1235")
    assert pg.sql("select count(*) from claims")[0][0] == 0


def test_database_itself_rejects_bad_pins_and_a_name_that_is_not_yours(pg, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    h = auth.hash_token(tokens.mom)
    call = lambda **kw: pg.rpc("claim_create", {"p_token_hash": h, "p_product_id": pid, "p_family_slug": "mom", "p_pin": PIN, **kw}).execute().data
    assert call(p_pin="12")["code"] == "invalid_pin" and call(p_pin="abcd")["code"] == "invalid_pin" and call(p_pin=None)["code"] == "invalid_pin"
    assert call(p_family_slug="dad")["code"] == "name_mismatch"      # confirm "as Dad" while signed in as Mom
    assert pg.sql("select count(*) from claims")[0][0] == 0


def test_only_signed_in_family_members_can_claim(pg, creds, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    nameless = auth.login("Gift Giver", creds.family).token
    for bad in (None, "forged", nameless, tokens.admin):
        with pytest.raises(PermissionDenied):
            claims.claim(bad, pid, "mom", PIN, PIN)
    for who in (None, "forged", tokens.admin):                        # and the DB agrees when Python is bypassed
        h = None if who is None else auth.hash_token(who)
        res = pg.rpc("claim_create", {"p_token_hash": h, "p_product_id": pid, "p_family_slug": "mom", "p_pin": PIN}).execute().data
        assert res == {"ok": False, "code": "forbidden"}
    assert pg.sql("select count(*) from claims")[0][0] == 0


def test_archived_hidden_and_missing_products_cannot_be_claimed(pg, tokens, catalog_ids):
    import uuid
    pg.sql("update products set is_archived=true where name='Gentle Cleanser'")
    pg.sql("update categories set is_hidden=true where name='Books'")
    for pid in (catalog_ids["Gentle Cleanser"], catalog_ids["Poetry Collection"], str(uuid.uuid4())):
        with pytest.raises(ClaimError) as err:
            claims.claim(tokens.mom, pid, "mom", PIN, PIN)
        assert err.value.code == "unavailable"
    pg.sql("update products set is_archived=false where name='Gentle Cleanser'")          # restored -> claimable again
    claims.claim(tokens.mom, catalog_ids["Gentle Cleanser"], "mom", PIN, PIN)


def test_concurrent_claims_through_the_rpc_produce_exactly_one_winner(pg, creds, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    slugs = ["mom", "dad", "brother", "grandmother"] * 3
    sessions = [(session_for(creds, s), s) for s in slugs]
    barrier, outcomes, lock = threading.Barrier(len(sessions)), [], threading.Lock()

    def attempt(tok, slug, pin):
        barrier.wait()
        try:
            claims.claim(tok, pid, slug, pin, pin)
            result = ("ok", slug, pin)
        except ClaimError as exc:
            result = (exc.code, slug, pin)
        with lock:
            outcomes.append(result)

    pins = [f"{1000 + i}" for i in range(len(sessions))]
    threads = [threading.Thread(target=attempt, args=(t, s, pins[i])) for i, (t, s) in enumerate(sessions)]
    [t.start() for t in threads]; [t.join() for t in threads]
    winners = [o for o in outcomes if o[0] == "ok"]
    assert len(winners) == 1 and [o[0] for o in outcomes].count("already_claimed") == len(sessions) - 1
    (status, slug, *_), = claim_row(pg, pid)
    assert (status, slug) == ("active", winners[0][1])
    claims.release(session_for(creds, "dad"), pid, {"mom": "Mom", "dad": "Dad", "brother": "Brother", "grandmother": "Grandmother"}[slug], winners[0][2])   # winner's PIN is the one stored


# ------------------------------------------------------------------ releasing
@pytest.fixture
def claimed(pg, tokens, catalog_ids):
    pid = catalog_ids["Gentle Cleanser"]
    claims.claim(tokens.mom, pid, "mom", PIN, PIN)
    return pid


def test_wrong_pin_and_wrong_name_fail_identically_and_change_nothing(pg, tokens, claimed):
    before = claim_row(pg, claimed)
    errors = []
    for name, pin in (("Mom", "0000"), ("Dad", PIN), ("Dad", "0000")):
        with pytest.raises(ClaimError) as err:
            claims.release(tokens.dad, claimed, name, pin)
        errors.append((err.value.code, str(err.value)))
    assert len(set(errors)) == 1 and errors[0][0] == "failed"        # attacker learns nothing about which part was right
    assert claim_row(pg, claimed) == before and find(tokens.dad, claimed).claimed


def test_correct_name_and_pin_release_the_gift_and_destroy_the_credential(pg, tokens, claimed):
    claims.release(tokens.dad, claimed, "Mom", PIN)                  # another family member's session may release with Mom's PIN
    (status, slug, pin_hash, released_at, released_by), = claim_row(pg, claimed)
    assert (status, pin_hash, released_by) == ("released", None, "claimant") and released_at is not None
    assert not find(tokens.mom, claimed).claimed and find(tokens.mom, claimed).claimed_by is None
    with pytest.raises(ClaimError) as err:
        claims.release(tokens.dad, claimed, "Mom", PIN)              # the PIN no longer opens anything
    assert err.value.code == "not_claimed"


def test_name_matching_ignores_case_and_spaces_but_follows_renames(pg, creds, tokens, claimed):
    family.rename_all(tokens.admin, {"grandmother": "Nani", "brother": "Bhai", "mom": "Amma", "dad": "Nanna"})
    with pytest.raises(ClaimError):
        claims.release(tokens.dad, claimed, "Mom", PIN)              # old label no longer valid
    claims.release(tokens.dad, claimed, "  amma ", PIN)
    assert not find(tokens.dad, claimed).claimed


def test_released_gift_can_be_claimed_again_and_history_is_kept(pg, tokens, claimed):
    claims.release(tokens.mom, claimed, "Mom", PIN)
    claims.claim(tokens.dad, claimed, "dad", "5555", "5555")
    rows = claim_row(pg, claimed)
    assert [r[0] for r in rows] == ["released", "active"] and rows[1][1] == "dad"


def test_release_requires_a_signed_in_family_member(pg, creds, tokens, claimed):
    nameless = auth.login("Gift Giver", creds.family).token
    for bad in (None, "forged", nameless, tokens.admin):
        with pytest.raises(PermissionDenied):
            claims.release(bad, claimed, "Mom", PIN)
    assert find(tokens.mom, claimed).claimed


def test_release_of_an_unclaimed_gift_is_a_friendly_error(pg, tokens, catalog_ids):
    with pytest.raises(ClaimError) as err:
        claims.release(tokens.mom, catalog_ids["Dog Squeaky Toy"], "Mom", PIN)
    assert err.value.code == "not_claimed"


def test_repeated_wrong_attempts_lock_the_gift_even_for_the_right_pin(pg, creds, tokens, claimed, catalog_ids):
    other = catalog_ids["Dog Squeaky Toy"]
    claims.claim(tokens.dad, other, "dad", "4321", "4321")
    for _ in range(5):
        with pytest.raises(ClaimError) as err:
            claims.release(tokens.dad, claimed, "Mom", "0000")
        assert err.value.code == "failed"
    brother = session_for(creds, "brother")                           # a DIFFERENT session is locked out of this gift too
    for who in (tokens.dad, brother):
        with pytest.raises(ClaimError) as err:
            claims.release(who, claimed, "Mom", PIN)
        assert err.value.code == "locked"
    assert find(tokens.mom, claimed).claimed
    claims.release(brother, other, "Dad", "4321")                     # other gifts are unaffected
    pg.sql("update rate_limits set locked_until = now() - interval '1 second'")
    claims.release(brother, claimed, "Mom", PIN)                      # lock expires
    assert not find(tokens.mom, claimed).claimed


def test_one_session_cannot_guess_across_many_gifts(pg, creds, tokens, catalog_ids):
    names = ["Gentle Cleanser", "Dog Squeaky Toy", "Poetry Collection", "Bluetooth Speaker", "Linen Summer Dress", "Rose Quartz Lip Gloss"]
    for n in names:
        claims.claim(tokens.mom, catalog_ids[n], "mom", PIN, PIN)
    for n in names[:5]:                                                # 5 wrong guesses, each on a different gift
        with pytest.raises(ClaimError) as err:
            claims.release(tokens.dad, catalog_ids[n], "Mom", "0000")
        assert err.value.code == "failed"
    with pytest.raises(ClaimError) as err:                             # the session is now throttled, even with the correct PIN
        claims.release(tokens.dad, catalog_ids[names[5]], "Mom", PIN)
    assert err.value.code == "locked"
    claims.release(session_for(creds, "brother"), catalog_ids[names[5]], "Mom", PIN)   # a fresh session is not affected by that counter


def test_concurrent_releases_release_exactly_once(pg, creds, claimed):
    sessions = [session_for(creds, s) for s in ["dad", "brother", "grandmother", "dad", "brother", "grandmother", "dad", "brother"]]
    barrier, outcomes, lock = threading.Barrier(len(sessions)), [], threading.Lock()

    def attempt(tok):
        barrier.wait()
        try:
            claims.release(tok, claimed, "Mom", PIN)
            r = "ok"
        except ClaimError as exc:
            r = exc.code
        with lock:
            outcomes.append(r)

    threads = [threading.Thread(target=attempt, args=(t,)) for t in sessions]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert outcomes.count("ok") == 1 and outcomes.count("not_claimed") == len(sessions) - 1
    assert [r[0] for r in claim_row(pg, claimed)] == ["released"]


def test_claim_and_release_are_audited_without_pins(pg, tokens, claimed):
    claims.release(tokens.mom, claimed, "Mom", PIN)
    actions = [r[0] for r in pg.sql("select action from audit_log where action like %s order by id", ["claim_%"])]
    assert actions == ["claim_create", "claim_release"]
    assert PIN not in str(pg.sql("select details::text from audit_log"))


def test_admin_override_still_works_and_clears_the_credential(pg, tokens, claimed):
    from wishlist import admin
    cid = admin.load_snapshot(tokens.admin).claims[0]["id"]
    admin.release_claim(tokens.admin, cid)
    assert claim_row(pg, claimed)[0][:3] == ("released", "mom", None)
    with pytest.raises(ClaimError):
        claims.release(tokens.dad, claimed, "Mom", PIN)
