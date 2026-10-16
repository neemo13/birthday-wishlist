"""Family claim / release. Python validates for friendly messages; PostgreSQL decides (atomically)."""
from __future__ import annotations

import logging

from . import auth, db
from .security import PermissionDenied, ValidationError, validate_new_secret

log = logging.getLogger("wishlist.claims")


class ClaimError(ValidationError):
    """Expected, user-facing failure. `code` is machine readable for the UI (e.g. refresh the list)."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


_CLAIM_MESSAGES = {
    "already_claimed": "Someone just claimed this gift - the list has been refreshed.",
    "unavailable": "This gift isn't available any more.",
    "name_mismatch": "Please claim as the name you signed in with.",
    "invalid_pin": "Please choose a PIN of 4 to 8 digits.",
}


def claim(token: str | None, product_id: str, family_slug: str, pin: str, pin_confirm: str) -> str:
    """Claim a gift for the signed-in family member. Never logs the PIN. Returns the claim id."""
    sess = auth.require_family(token)
    validate_new_secret("gift", pin, pin_confirm)
    res = db.rpc("claim_create", {"p_token_hash": sess.token_hash, "p_product_id": product_id,
                                  "p_family_slug": family_slug, "p_pin": pin})
    if res and res.get("ok"):
        log.info("claim created by=%s", sess.family_slug)
        return res["claim_id"]
    code = (res or {}).get("code", "error")
    if code == "forbidden":
        raise PermissionDenied("Please sign in as a Gift Giver first.")
    log.info("claim refused code=%s", code)
    raise ClaimError(_CLAIM_MESSAGES.get(code, "That didn't work. Please try again."), code)


def release(token: str | None, product_id: str, claimant_name: str, pin: str) -> None:
    """Release with the claimant's name + the gift's own PIN. Failures are deliberately generic."""
    sess = auth.require_family(token)
    if not (claimant_name or "").strip() or not pin:
        raise ClaimError("Please choose the name and enter the gift's PIN.", "incomplete")
    res = db.rpc("claim_release", {"p_token_hash": sess.token_hash, "p_product_id": product_id,
                                   "p_name": claimant_name, "p_pin": pin})
    if res and res.get("ok"):
        log.info("claim released by=%s", sess.family_slug)
        return
    code = (res or {}).get("code", "failed")
    if code == "forbidden":
        raise PermissionDenied("Please sign in as a Gift Giver first.")
    if code == "locked":
        mins = max(1, -(-int(res.get("retry_after", 60)) // 60))
        raise ClaimError(f"Too many tries for this gift. Please wait about {mins} minute(s), "
                         "or ask the Birthday Girl to release it.", "locked")
    if code == "not_claimed":
        raise ClaimError("This gift isn't claimed any more - the list has been refreshed.", "not_claimed")
    log.info("release refused")                                   # no hint about which part was wrong
    raise ClaimError("That name and PIN don't match this claim.", "failed")
