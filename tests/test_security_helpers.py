import pytest

from wishlist import security as sec


def test_token_hash_is_stable_and_not_the_token():
    t = sec.new_session_token()
    assert len(t) >= 40 and sec.hash_token(t) == sec.hash_token(t) != t
    assert sec.new_session_token() != t


@pytest.mark.parametrize("kind,value,ok", [
    ("admin", "short", False), ("admin", "long-enough-pw!", True),
    ("family", "12345", False), ("family", "123456", True),
    ("dad_only", "abc", False), ("gift", "123", False), ("gift", "1234", True),
    ("gift", "12345678", True), ("gift", "123456789", False), ("gift", "12ab", False),
])
def test_secret_policy(kind, value, ok):
    if ok:
        assert sec.validate_new_secret(kind, value) == value
    else:
        with pytest.raises(sec.ValidationError):
            sec.validate_new_secret(kind, value)


def test_secret_confirmation_must_match():
    with pytest.raises(sec.ValidationError):
        sec.validate_new_secret("family", "123456", "654321")


def test_clean_text_rules():
    assert sec.clean_text("  hi\x00 there ", "Name", 20) == "hi there"
    with pytest.raises(sec.ValidationError):
        sec.clean_text("  ", "Name", 20, required=True)
    with pytest.raises(sec.ValidationError):
        sec.clean_text("x" * 21, "Name", 20)


@pytest.mark.parametrize("url,ok", [
    ("https://shop.example/p?id=1", True), ("http://a.b", True),
    ("javascript:alert(1)", False), ("ftp://x.y", False), ("https://a b.c", False),
    ("https://x.y/<script>", False), ("", False),
])
def test_url_validation(url, ok):
    if ok:
        assert sec.validate_url(url) == url
    else:
        with pytest.raises(sec.ValidationError):
            sec.validate_url(url)


def test_session_throttle_locks_then_expires():
    st = {}
    for _ in range(5):
        assert sec.throttle_remaining(st, "login", now=100) == 0
        sec.throttle_register_failure(st, "login", now=100)
    assert sec.throttle_remaining(st, "login", now=101) > 0
    assert sec.throttle_remaining(st, "login", now=100 + 61) == 0
    sec.throttle_register_failure(st, "login", now=200)
    sec.throttle_reset(st, "login")
    assert st == {}
