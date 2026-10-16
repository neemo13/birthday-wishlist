"""Admin-only credential management (family PIN, admin password, Dad Only PIN)."""
from __future__ import annotations

from . import auth, db
from .security import PermissionDenied, ValidationError, validate_new_secret

KINDS = {"family": "Family PIN", "admin": "Admin password", "dad_only": "Dad Only PIN"}

_MESSAGES = {
    "wrong_password": "That admin password isn't right.",
    "weak_secret": "That's too short - please choose a longer one.",
    "cannot_disable_admin": "The admin login can't be switched off.",
    "no_secret": "Set a PIN before enabling this.",
    "invalid": "That change isn't allowed.",
}


def status(token: str | None) -> list[dict]:
    sess = auth.require_admin(token)
    res = db.rpc("credential_status", {"p_token_hash": sess.token_hash})
    if not res or not res.get("ok"):
        raise PermissionDenied("This area is only for the Birthday Girl.")
    return res["items"]


def change(token: str | None, admin_password: str, kind: str,
           new_secret: str | None = None, confirm: str | None = None,
           enabled: bool | None = None) -> None:
    """Re-checks the admin session AND the current admin password server-side."""
    sess = auth.require_admin(token)
    if new_secret is not None:
        validate_new_secret(kind, new_secret, confirm)
    if not admin_password:
        raise ValidationError("Please enter your current admin password to confirm.")
    res = db.rpc("credential_change", {
        "p_token_hash": sess.token_hash, "p_admin_password": admin_password,
        "p_kind": kind, "p_new_secret": new_secret, "p_enabled": enabled})
    if res and res.get("ok"):
        return
    code = (res or {}).get("code", "invalid")
    if code == "forbidden":
        raise PermissionDenied("This area is only for the Birthday Girl.")
    if code == "locked":
        raise ValidationError("Too many wrong passwords. Please wait a few minutes and try again.")
    raise ValidationError(_MESSAGES.get(code, "That change isn't allowed."))
