"""The Dad Only page: separate PIN, server-side checks on every request."""
from __future__ import annotations

import logging

from . import auth, db
from .security import PermissionDenied, ValidationError

log = logging.getLogger("wishlist.dad")


def unlock(token: str | None, pin: str) -> None:
    """Needs a Dad-named family session AND the Dad Only PIN. The browser never receives the PIN or a 'unlocked' flag
    it could set itself - the flag lives in the database session row."""
    sess = auth.require_family(token)
    if not pin:
        raise ValidationError("Please enter the Dad Only PIN.")
    res = db.rpc("dad_unlock", {"p_token_hash": sess.token_hash, "p_pin": pin})
    if res and res.get("ok"):
        return
    code = (res or {}).get("code", "failed")
    log.info("dad unlock refused code=%s", code)
    if code == "locked":
        mins = max(1, -(-int(res.get("retry_after", 60)) // 60))
        raise ValidationError(f"Too many tries. Please wait about {mins} minute(s).")
    if code == "unavailable":
        raise ValidationError("This page isn't open right now.")
    if code == "forbidden":
        raise PermissionDenied("This page is only for Dad.")
    raise ValidationError("That PIN didn't match.")


def get_page(token: str | None) -> dict:
    """{'title','message'} - or PermissionDenied unless: admin, or a Dad session that unlocked it while it's enabled."""
    sess = auth.require_member(token)
    res = db.rpc("dad_page_get", {"p_token_hash": sess.token_hash})
    if not res or not res.get("ok"):
        raise PermissionDenied("This page isn't open for you.")
    return res.get("page") or {}
