"""Family display names: read after login, edited by the admin."""
from __future__ import annotations

from . import auth, db
from .security import PermissionDenied, ValidationError, clean_text

SLUG_ORDER = ["grandmother", "brother", "mom", "dad"]


def list_names(token: str | None) -> list[dict]:
    """[{slug, display_name}] in fixed order. Any signed-in session may read."""
    res = db.rpc("family_list", {"p_token_hash": auth.hash_token(token or "")})
    if not res or not res.get("ok"):
        raise PermissionDenied("Please sign in first.")
    return res["items"]


def choose(token: str | None, slug: str) -> None:
    res = db.rpc("session_set_family", {"p_token_hash": auth.hash_token(token or ""), "p_slug": slug})
    if not res or not res.get("ok"):
        raise PermissionDenied("That choice isn't available for this session.")


def rename_all(token: str | None, names: dict[str, str]) -> None:
    """Admin only. `names` maps slug -> new display name; all four must stay distinct."""
    sess = auth.require_admin(token)
    cleaned = {s: clean_text(names.get(s), "Name", 40, required=True) for s in SLUG_ORDER}
    if len({n.lower() for n in cleaned.values()}) != len(cleaned):
        raise ValidationError("The four names must all be different.")
    res = db.rpc("family_rename", {"p_token_hash": sess.token_hash, "p_names": cleaned})
    if not res or not res.get("ok"):
        if (res or {}).get("code") == "forbidden":
            raise PermissionDenied("This area is only for the Birthday Girl.")
        raise ValidationError("Those names couldn't be saved. Please check them and try again.")
