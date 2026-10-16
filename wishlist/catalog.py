"""Wishlist data + the pure search / filter / sort logic (no Streamlit, no database in the logic).

Price rules (documented, tested):
  * A product's effective range is [price_min, price_max]. If only one end is set, it is a single
    price (low == high). If neither is set the product is "unpriced".
  * A budget [lo, hi] matches a product when the ranges OVERLAP: product_low <= hi and product_high >= lo.
  * Unpriced products match only when `include_unpriced` is true (default).
  * Sorting by price uses product_low (ascending) or product_high (descending); unpriced products
    always come last. Ties are broken by name, then id, so ordering is deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from . import auth, db
from .security import PermissionDenied

UNCATEGORIZED = "__none__"
STATUS_OPTIONS = ("All", "Available", "Claimed")
SORT_OPTIONS = {
    "newest": "Newest added",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
    "name": "Alphabetical (A–Z)",
}


@dataclass(frozen=True)
class Link:
    source_name: str
    url: str
    note: str = ""


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str = ""
    kind: str = "regular"


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category_id: str | None
    category_name: str
    short_description: str
    price_min: Decimal | None
    price_max: Decimal | None
    preferences: str
    notes: str
    image_path: str | None
    created_at: datetime
    links: tuple[Link, ...] = ()
    claimed: bool = False
    claimed_by: str | None = None
    is_archived: bool = False

    @property
    def price_low(self) -> Decimal | None:
        return self.price_min if self.price_min is not None else self.price_max

    @property
    def price_high(self) -> Decimal | None:
        return self.price_max if self.price_max is not None else self.price_min

    @property
    def status(self) -> str:
        return "Claimed" if self.claimed else "Available"


@dataclass(frozen=True)
class Catalog:
    categories: list[Category] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)


@dataclass(frozen=True)
class Filters:
    query: str = ""
    category_id: str | None = None          # None = all, UNCATEGORIZED = no category
    budget: tuple[Decimal, Decimal] | None = None
    include_unpriced: bool = True
    status: str = "All"
    sort: str = "newest"


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def parse_catalog(payload: dict) -> Catalog:
    cats = [Category(c["id"], c["name"], c.get("description", ""), c.get("kind", "regular"))
            for c in payload.get("categories", [])]
    names = {c.id: c.name for c in cats}
    products = []
    for p in payload.get("products", []):
        products.append(Product(
            id=p["id"], name=p["name"], category_id=p.get("category_id"),
            category_name=names.get(p.get("category_id"), ""),
            short_description=p.get("short_description") or "", price_min=_dec(p.get("price_min")),
            price_max=_dec(p.get("price_max")), preferences=p.get("preferences") or "",
            notes=p.get("notes") or "", image_path=p.get("image_path"),
            created_at=datetime.fromisoformat(p["created_at"]),
            links=tuple(Link(l["source_name"], l["url"], l.get("note") or "") for l in p.get("links", [])),
            claimed=bool(p.get("claimed")), claimed_by=p.get("claimed_by"),
            is_archived=bool(p.get("is_archived"))))
    return Catalog(cats, products)


def load_catalog(token: str | None) -> Catalog:
    res = db.rpc("catalog_list", {"p_token_hash": auth.hash_token(token or "")})
    if not res or not res.get("ok"):
        raise PermissionDenied("Please sign in first.")
    return parse_catalog(res)


# ------------------------------------------------------------------ pure logic
def matches_query(p: Product, query: str) -> bool:
    """Every whitespace-separated term must appear somewhere in the searchable text."""
    terms = query.casefold().split()
    if not terms:
        return True
    haystack = " ".join([p.name, p.short_description, p.category_name, p.preferences, p.notes]).casefold()
    return all(t in haystack for t in terms)


def matches_budget(p: Product, budget: tuple[Decimal, Decimal] | None, include_unpriced: bool) -> bool:
    if budget is None:
        return True
    if p.price_low is None:
        return include_unpriced
    lo, hi = budget
    return p.price_low <= hi and p.price_high >= lo


def apply_filters(products: list[Product], f: Filters) -> list[Product]:
    out = []
    for p in products:
        if f.category_id == UNCATEGORIZED and p.category_id is not None:
            continue
        if f.category_id not in (None, UNCATEGORIZED) and p.category_id != f.category_id:
            continue
        if f.status == "Available" and p.claimed:
            continue
        if f.status == "Claimed" and not p.claimed:
            continue
        if not matches_query(p, f.query) or not matches_budget(p, f.budget, f.include_unpriced):
            continue
        out.append(p)
    return sort_products(out, f.sort)


def sort_products(products: list[Product], mode: str) -> list[Product]:
    by_name = sorted(products, key=lambda p: (p.name.casefold(), p.id))     # stable base order
    if mode == "name":
        return by_name
    if mode == "newest":
        return sorted(by_name, key=lambda p: p.created_at, reverse=True)
    priced = [p for p in by_name if p.price_low is not None]
    unpriced = [p for p in by_name if p.price_low is None]                   # always last
    if mode == "price_asc":
        return sorted(priced, key=lambda p: p.price_low) + unpriced
    if mode == "price_desc":
        return sorted(priced, key=lambda p: p.price_high, reverse=True) + unpriced
    raise ValueError(f"unknown sort mode: {mode}")


def price_bounds(products: list[Product]) -> tuple[Decimal, Decimal] | None:
    lows = [p.price_low for p in products if p.price_low is not None]
    highs = [p.price_high for p in products if p.price_high is not None]
    return (min(lows), max(highs)) if lows else None


def format_price(p: Product, currency: str = "₹") -> str:
    def money(d: Decimal) -> str:
        return f"{currency}{d:,.0f}" if d == d.to_integral_value() else f"{currency}{d:,.2f}"
    lo, hi = p.price_min, p.price_max
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None:
        return money(lo) if lo == hi else f"{money(lo)} – {money(hi)}"
    return money(lo if lo is not None else hi)      # one end only = a single price
