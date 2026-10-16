"""Pure helpers: tokens, input validation, brute-force throttling. No Streamlit/DB imports."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from typing import MutableMapping


class PermissionDenied(Exception):
    """The caller's verified session is not allowed to do this."""


class ValidationError(ValueError):
    """User input is invalid. The message is safe to show to the user."""


# ---------- session tokens ------------------------------------------------
def new_session_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    """Only this hash is ever sent to / stored in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------- secret policies (must match the SQL functions) -----------------
SECRET_MIN_LENGTH = {"admin": 12, "family": 6, "dad_only": 6, "gift": 4}
SECRET_MAX_LENGTH = 128
GIFT_PIN_RE = re.compile(r"^\d{4,8}$")


def validate_new_secret(kind: str, value: str, confirm: str | None = None) -> str:
    if kind not in SECRET_MIN_LENGTH:
        raise ValidationError("Unknown credential type.")
    if confirm is not None and value != confirm:
        raise ValidationError("The two entries don't match.")
    if kind == "gift":
        if not GIFT_PIN_RE.match(value or ""):
            raise ValidationError("Please choose a PIN of 4 to 8 digits.")
        return value
    minimum = SECRET_MIN_LENGTH[kind]
    if not value or len(value) < minimum:
        raise ValidationError(f"Please use at least {minimum} characters.")
    if len(value) > SECRET_MAX_LENGTH:
        raise ValidationError(f"Please use at most {SECRET_MAX_LENGTH} characters.")
    return value


# ---------- text / url validation -----------------------------------------
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def clean_text(value: str | None, field: str, max_len: int, required: bool = False) -> str:
    text = _CONTROL_RE.sub("", (value or "")).strip()
    if required and not text:
        raise ValidationError(f"{field} is required.")
    if len(text) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return text


def validate_url(url: str | None) -> str:
    url = (url or "").strip()
    if len(url) > 2000 or not _URL_RE.match(url):
        raise ValidationError("Links must start with http:// or https:// and contain no spaces.")
    return url


# ---------- per-browser-session throttle (a speed bump, not the real lock) --
# The authoritative lockout lives in PostgreSQL (rate_limits). This only slows
# down a script hammering one Streamlit session and spares the database.
def throttle_remaining(state: MutableMapping, key: str, *, max_fails: int = 5,
                       lock_seconds: int = 60, now: float | None = None) -> int:
    now = time.time() if now is None else now
    until = state.get(f"{key}:until", 0.0)
    return max(0, int(until - now + 0.999)) if until > now else 0


def throttle_register_failure(state: MutableMapping, key: str, *, max_fails: int = 5,
                              lock_seconds: int = 60, now: float | None = None) -> None:
    now = time.time() if now is None else now
    fails = state.get(f"{key}:fails", 0) + 1
    if fails >= max_fails:
        state[f"{key}:until"] = now + lock_seconds
        fails = 0
    state[f"{key}:fails"] = fails


def throttle_reset(state: MutableMapping, key: str) -> None:
    state.pop(f"{key}:fails", None)
    state.pop(f"{key}:until", None)
