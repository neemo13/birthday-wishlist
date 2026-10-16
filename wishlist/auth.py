"""Authentication and authorization. Streamlit-free so it is easy to test.

Trust model: the browser/Streamlit session holds only a random token. Role, name and
Dad Only status live in the `sessions` table and are re-verified by the database on
every privileged call, so editing Streamlit session state cannot grant anything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import db
from .security import PermissionDenied, hash_token, new_session_token

log = logging.getLogger("wishlist.auth")

# The two (and only two) user-facing login choices -> internal roles.
ROLE_LABELS = {"Birthday Girl": "admin", "Gift Giver": "family"}


@dataclass(frozen=True)
class Session:
    token_hash: str
    role: str                      # 'admin' | 'family'
    family_slug: str | None
    display_name: str | None
    is_dad: bool
    dad_unlocked: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def needs_name(self) -> bool:
        return self.role == "family" and not self.family_slug


@dataclass(frozen=True)
class LoginOutcome:
    ok: bool
    code: str = ""                 # 'invalid' | 'locked'
    retry_after: int = 0
    token: str | None = None       # plaintext token, to be kept only in server-side session state


def login(role_label: str, secret: str) -> LoginOutcome:
    role = ROLE_LABELS.get(role_label)
    if role is None or not secret:
        return LoginOutcome(False, "invalid")
    token = new_session_token()
    res = db.rpc("auth_login", {"p_role": role, "p_secret": secret, "p_token_hash": hash_token(token)})
    if res and res.get("ok"):
        log.info("login ok role=%s", role)
        return LoginOutcome(True, token=token)
    code = (res or {}).get("code", "invalid")
    log.warning("login failed role=%s code=%s", role, code)    # never the secret itself
    return LoginOutcome(False, code if code == "locked" else "invalid", int((res or {}).get("retry_after", 0)))


def load_session(token: str | None) -> Session | None:
    """Ask the database whether this token is a live session. None = logged out."""
    if not token:
        return None
    res = db.rpc("session_get", {"p_token_hash": hash_token(token)})
    if not res or not res.get("valid"):
        return None
    return Session(
        token_hash=hash_token(token),
        role=res["role"],
        family_slug=res.get("family_slug"),
        display_name=res.get("display_name"),
        is_dad=bool(res.get("is_dad")),
        dad_unlocked=bool(res.get("dad_unlocked")),
    )


def logout(token: str | None) -> None:
    if token:
        db.rpc("session_destroy", {"p_token_hash": hash_token(token)})


def require_admin(token: str | None) -> Session:
    """Call at the start of EVERY privileged operation."""
    sess = load_session(token)
    if sess is None or not sess.is_admin:
        raise PermissionDenied("This area is only for the Birthday Girl.")
    return sess


def require_family(token: str | None) -> Session:
    """A Gift Giver who has also chosen a family name."""
    sess = load_session(token)
    if sess is None or sess.role != "family" or sess.needs_name:
        raise PermissionDenied("Please sign in as a Gift Giver first.")
    return sess


def require_member(token: str | None) -> Session:
    """Any fully signed-in visitor (admin, or family with a name chosen)."""
    sess = load_session(token)
    if sess is None or sess.needs_name:
        raise PermissionDenied("Please sign in first.")
    return sess
