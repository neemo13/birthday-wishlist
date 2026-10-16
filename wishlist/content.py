"""Editable website content (non-secret). Defaults fill anything the database doesn't have yet."""
from __future__ import annotations

import copy

from . import auth, db
from .security import PermissionDenied

DEFAULTS = {
    "homepage": {
        "eyebrow": "♡ a very special day ♡", "heading": "Happy 21st Birthday!",
        "subtitle": "A little list of things that would make me very happy.",
        "message": "Don't be stingy, come on, celebrate the girl! 🎀",
        "button_label": "Enter the World of Gifts ✨", "portrait_path": None,
    },
    "wishlist": {
        "heading": "The Wishlist",
        "intro": "Browse, peek at the details, and claim something lovely. ♡",
        "currency": "₹",
    },
    "sections": {
        "homepage": [{"id": "portrait", "visible": True}, {"id": "message", "visible": True},
                     {"id": "cta", "visible": True}],
        "wishlist": [{"id": "intro", "visible": True}, {"id": "search", "visible": True},
                     {"id": "filters", "visible": True}, {"id": "grid", "visible": True}],
    },
}
KNOWN_SECTIONS = {page: [s["id"] for s in items] for page, items in DEFAULTS["sections"].items()}


def get_settings(token: str | None) -> dict:
    res = db.rpc("settings_get", {"p_token_hash": auth.hash_token(token or "")})
    if not res or not res.get("ok"):
        raise PermissionDenied("Please sign in first.")
    merged = copy.deepcopy(DEFAULTS)
    for key, value in (res.get("settings") or {}).items():
        if key in merged and isinstance(value, dict):
            merged[key].update(value)
    return merged


def visible_sections(settings: dict, page: str) -> list[str]:
    """Ordered ids of the sections to draw. Unknown ids are ignored; known ones missing from the
    stored list are appended (visible), so adding a section in a later release can't hide it."""
    known = KNOWN_SECTIONS[page]
    stored = settings.get("sections", {}).get(page) or []
    seen, order = set(), []
    for item in stored:
        sid = item.get("id") if isinstance(item, dict) else None
        if sid in known and sid not in seen:
            seen.add(sid)
            if item.get("visible", True):
                order.append(sid)
    order += [sid for sid in known if sid not in seen]
    return order


SECTION_LABELS = {"portrait": "Portrait", "message": "Birthday message", "cta": "Enter button",
                  "intro": "Heading & intro", "search": "Search box", "filters": "Categories & filters",
                  "grid": "Gift grid"}


def section_items(settings: dict, page: str) -> list[tuple[str, bool]]:
    """All known sections in stored order WITH visibility (used by the editor; visible_sections hides the hidden)."""
    known = KNOWN_SECTIONS[page]
    items, seen = [], set()
    for item in settings.get("sections", {}).get(page) or []:
        sid = item.get("id") if isinstance(item, dict) else None
        if sid in known and sid not in seen:
            seen.add(sid)
            items.append((sid, bool(item.get("visible", True))))
    return items + [(sid, True) for sid in known if sid not in seen]
