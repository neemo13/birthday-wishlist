import logging

import pytest

from wishlist import auth
from wishlist.logging_setup import RedactingFilter, redact
from tests.conftest import ADMIN_PW, FAMILY_PIN


@pytest.mark.parametrize("raw,secret", [
    ("login pin=123456 failed", "123456"),
    ("password: hunter2hunter2", "hunter2hunter2"),
    ('payload {"pin": "987654"}', "987654"),
    ("Authorization: Bearer abc.def", "abc.def"),
    ("token=" + "A" * 43, "A" * 43),
    ("key eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZSJ9.c2lnbmF0dXJl", "eyJhbGciOiJIUzI1NiJ9"),
    ("hash " + "f" * 64, "f" * 64),
])
def test_redact_masks_secrets(raw, secret):
    assert secret not in redact(raw)


def test_redact_leaves_normal_text_alone():
    assert redact("login failed role=family code=invalid") == "login failed role=family code=invalid"


def test_filter_redacts_formatted_log_records():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "pin=%s", ("123456",), None)
    RedactingFilter().filter(rec)
    assert "123456" not in rec.getMessage()


def test_failed_and_successful_logins_never_log_the_secret_or_token(pg, creds, caplog):
    with caplog.at_level(logging.DEBUG):
        auth.login("Gift Giver", "wrong-pin-777")
        out = auth.login("Gift Giver", FAMILY_PIN)
        auth.login("Birthday Girl", ADMIN_PW)
        auth.load_session(out.token)
    text = caplog.text
    assert "login failed role=family" in text and "login ok role=family" in text
    for secret in ("wrong-pin-777", FAMILY_PIN, ADMIN_PW, out.token, auth.hash_token(out.token)):
        assert secret not in text


def test_backend_errors_log_only_the_exception_class(caplog):
    from wishlist import db

    class Boom:
        def rpc(self, name, params=None):
            raise RuntimeError("connection string postgres://user:SUPERSECRET@host")
    db.set_client(Boom())
    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(db.BackendError) as err:
            db.rpc("auth_login", {"p_secret": "my-pin-123456"})
    finally:
        db.set_client(None)
    assert "SUPERSECRET" not in caplog.text and "my-pin-123456" not in caplog.text
    assert "SUPERSECRET" not in str(err.value) and "RuntimeError" in caplog.text
