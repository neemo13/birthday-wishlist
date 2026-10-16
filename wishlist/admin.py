"""Admin Studio operations. Every function: (1) require_admin (fresh DB check), (2) validate input in Python
for friendly messages, (3) call a SQL function that re-checks admin and enforces the rules again."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import auth, catalog, content, db, storage
from .security import PermissionDenied, ValidationError, clean_text, validate_url

log = logging.getLogger("wishlist.admin")
MAX_LINKS = 10

_MESSAGES = {
    "invalid": "Please check the fields and try again.",
    "invalid_category": "That category isn't available. Please pick another.",
    "duplicate": "Another category already uses that name.",
    "too_many_links": f"A gift can have at most {MAX_LINKS} shopping links.",
    "not_found": "That item no longer exists - please refresh the page.",
    "has_products": "This category still has gifts. Choose where to move them first.",
    "invalid_target": "Please choose a different category to move the gifts to.",
    "protected": "The Dad Only category is protected and can't be deleted.",
    "not_active": "That claim has already been released.",
}


@dataclass(frozen=True)
class Snapshot:
    counts: dict
    categories: list[dict]
    products: list[catalog.Product]
    claims: list[dict]

    @property
    def available(self) -> int:
        return self.counts["active"] - self.counts["claimed"]


def _call(token: str | None, fn: str, params: dict) -> dict:
    """Admin check + RPC + error mapping. Returns the ok-result dict or raises."""
    sess = auth.require_admin(token)
    res = db.rpc(fn, {"p_token_hash": sess.token_hash, **params})
    if res and res.get("ok"):
        return res
    code = (res or {}).get("code", "invalid")
    if code == "forbidden":
        raise PermissionDenied("This area is only for the Birthday Girl.")
    log.info("admin action %s refused code=%s", fn, code)
    raise ValidationError(_MESSAGES.get(code, _MESSAGES["invalid"]))


# ------------------------------------------------------------------ pure validation helpers
def parse_price(value) -> Decimal | None:
    """Blank -> None. Accepts 1200, '1,200', '₹ 1200.50'. Rejects negatives, NaN, absurd values."""
    if value is None:
        return None
    text = str(value).replace(",", "").replace("₹", "").replace("$", "").strip()
    if text == "":
        return None
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValidationError("Prices must be numbers, like 1200 or 899.50.") from None
    if not d.is_finite() or d < 0:
        raise ValidationError("Prices can't be negative.")
    if d > Decimal("99999999.99"):
        raise ValidationError("That price is too large.")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)   # people expect 12.345 -> 12.35


def build_links(rows: list[dict]) -> list[dict]:
    """rows: [{order, source_name, url, note}] -> cleaned, ordered links. A fully blank row means 'no link'."""
    ordered = []
    for idx, row in enumerate(rows):
        name = clean_text(row.get("source_name"), "Retailer name", 60)
        url = (row.get("url") or "").strip()
        note = clean_text(row.get("note"), "Link note", 200)
        if not name and not url and not note:
            continue
        if not name or not url:
            raise ValidationError("Each shopping link needs both a retailer name and a web address.")
        ordered.append((row.get("order") or idx + 1, idx, {"source_name": name, "url": validate_url(url), "note": note}))
    if len(ordered) > MAX_LINKS:
        raise ValidationError(_MESSAGES["too_many_links"])
    return [item for _, _, item in sorted(ordered, key=lambda t: (t[0], t[1]))]


def build_product_payload(*, product_id, name, category_id, short_description, price_min, price_max,
                          preferences, notes, links) -> dict:
    lo, hi = parse_price(price_min), parse_price(price_max)
    if lo is not None and hi is not None and lo > hi:
        raise ValidationError("The minimum price can't be higher than the maximum price.")
    return {
        "id": product_id or None,
        "name": clean_text(name, "Gift name", 120, required=True),
        "category_id": category_id or None,
        "short_description": clean_text(short_description, "Short description", 300),
        "price_min": None if lo is None else str(lo), "price_max": None if hi is None else str(hi),
        "preferences": clean_text(preferences, "Preferences", 2000),
        "notes": clean_text(notes, "Extra notes", 2000),
        "links": build_links(links),
    }


def build_sections_payload(page_orders: dict[str, list[tuple[str, bool, int]]]) -> dict:
    """{'homepage': [(id, visible, order), ...], ...} -> ordered [{'id','visible'}] per page (validated by SQL too)."""
    out = {}
    for page, rows in page_orders.items():
        known = set(content.KNOWN_SECTIONS[page])
        ids = [r[0] for r in rows]
        if set(ids) != known or len(ids) != len(known):
            raise ValidationError("Unknown or duplicate section.")
        out[page] = [{"id": sid, "visible": bool(vis)} for sid, vis, _ in sorted(rows, key=lambda r: r[2])]
    return out


# ------------------------------------------------------------------ reads
def load_snapshot(token: str | None) -> Snapshot:
    res = _call(token, "admin_snapshot", {})
    cats = res["categories"]
    parsed = catalog.parse_catalog({"categories": [c for c in cats], "products": res["products"]})
    return Snapshot(res["counts"], cats, parsed.products, res["claims"])


def recent_activity(token: str | None, limit: int = 12) -> list[dict]:
    return _call(token, "audit_recent", {"p_limit": limit})["items"]


def dad_page(token: str | None) -> dict:
    return _call(token, "dad_page_get_admin", {})["page"] or {}


# ------------------------------------------------------------------ products
def save_product(token: str | None, *, product_id=None, name, category_id=None, short_description="",
                 price_min=None, price_max=None, preferences="", notes="", links=(),
                 image: bytes | None = None, remove_image: bool = False) -> str:
    auth.require_admin(token)
    payload = build_product_payload(product_id=product_id, name=name, category_id=category_id,
                                    short_description=short_description, price_min=price_min, price_max=price_max,
                                    preferences=preferences, notes=notes, links=list(links))
    new_path = None
    if image:
        new_path = storage.upload_image(token, image, "product")         # may raise UploadError: nothing saved yet
        payload["image_path"] = new_path
    elif remove_image:
        payload["image_path"] = None
    try:
        res = _call(token, "product_save", {"p_product": payload})
    except Exception:
        if new_path:                                                     # DB refused: don't leave an orphan photo
            storage.delete_image(token, new_path)
        raise
    if res.get("old_image_path"):
        storage.delete_image(token, res["old_image_path"])
    return res["id"]


def set_archived(token: str | None, product_id: str, archived: bool) -> bool:
    """Returns True if the product has an active claim (which is kept)."""
    return _call(token, "product_set_archived", {"p_id": product_id, "p_archived": archived})["had_active_claim"]


# ------------------------------------------------------------------ categories
def save_category(token: str | None, *, category_id=None, name, description="", is_hidden=False, sort_order=None) -> str:
    payload = {"id": category_id or None, "name": clean_text(name, "Category name", 60, required=True),
               "description": clean_text(description, "Description", 300), "is_hidden": bool(is_hidden)}
    if sort_order is not None:
        payload["sort_order"] = int(sort_order)
    return _call(token, "category_save", {"p_cat": payload})["id"]


def delete_category(token: str | None, category_id: str, *, reassign_to: str | None = None,
                    uncategorize: bool = False) -> int:
    return _call(token, "category_delete", {"p_id": category_id, "p_reassign_to": reassign_to,
                                            "p_uncategorize": uncategorize})["moved"]


# ------------------------------------------------------------------ website content
def save_homepage(token: str | None, *, eyebrow, heading, subtitle, message, button_label) -> None:
    _call(token, "settings_update", {"p_key": "homepage", "p_value": {
        "eyebrow": clean_text(eyebrow, "Small heading", 80), "heading": clean_text(heading, "Heading", 100, required=True),
        "subtitle": clean_text(subtitle, "Subtitle", 300), "message": clean_text(message, "Message", 600),
        "button_label": clean_text(button_label, "Button label", 60, required=True)}})


def save_wishlist_texts(token: str | None, *, heading, intro, currency) -> None:
    _call(token, "settings_update", {"p_key": "wishlist", "p_value": {
        "heading": clean_text(heading, "Heading", 100, required=True), "intro": clean_text(intro, "Introduction", 400),
        "currency": clean_text(currency, "Currency symbol", 5, required=True)}})


def save_sections(token: str | None, page_orders: dict) -> None:
    _call(token, "settings_update", {"p_key": "sections", "p_value": build_sections_payload(page_orders)})


def set_portrait(token: str | None, image: bytes | None) -> None:
    """Upload+save a new portrait, or (image=None) remove it. Old file is deleted only after the DB accepts the change."""
    auth.require_admin(token)
    new_path = storage.upload_image(token, image, "portrait") if image else None
    try:
        res = _call(token, "settings_update", {"p_key": "homepage", "p_value": {"portrait_path": new_path}})
    except Exception:
        if new_path:
            storage.delete_image(token, new_path)
        raise
    if res.get("old_portrait_path"):
        storage.delete_image(token, res["old_portrait_path"])


def save_dad_page(token: str | None, *, title: str, message: str) -> None:
    _call(token, "dad_page_set", {"p_title": clean_text(title, "Title", 80, required=True),
                                  "p_message": clean_text(message, "Message", 1000, required=True)})


# ------------------------------------------------------------------ claims
def release_claim(token: str | None, claim_id: str) -> None:
    _call(token, "claim_admin_release", {"p_claim_id": claim_id})
