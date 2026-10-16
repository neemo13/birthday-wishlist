"""Pure logic (no database): search, budget overlap, status filter, sorting, price formatting."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from wishlist import catalog as c
from wishlist.catalog import Filters, Product

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def prod(name, lo=None, hi=None, *, cat="", cid="c1", desc="", prefs="", notes="", claimed=False, age=0):
    return Product(id=name.lower().replace(" ", "-"), name=name, category_id=cid, category_name=cat,
                   short_description=desc, price_min=None if lo is None else D(lo), price_max=None if hi is None else D(hi),
                   preferences=prefs, notes=notes, image_path=None, created_at=T0 + timedelta(days=age), claimed=claimed)


CATALOG = [
    prod("Lip Gloss", 450, 900, cat="Makeup", prefs="Shade: rose petal", age=1),
    prod("Dress", 2500, 4500, cat="Clothing", notes="blush or cream colour", age=2),
    prod("Cleanser", 600, 600, cat="Skincare", desc="For sensitive skin", age=3),
    prod("Poetry Book", cat="Books", age=4),                       # unpriced
    prod("Treat Box", 1200, None, cat="", cid=None, age=5),         # only a minimum -> single price
    prod("Dog Toy", None, 300, cat="My Dog", claimed=True, age=6),  # only a maximum -> single price
]


def names(products):
    return [p.name for p in products]


def test_effective_price_when_only_one_end_is_set():
    assert (CATALOG[4].price_low, CATALOG[4].price_high) == (D(1200), D(1200))
    assert (CATALOG[5].price_low, CATALOG[5].price_high) == (D(300), D(300))
    assert CATALOG[3].price_low is None and CATALOG[3].price_high is None


@pytest.mark.parametrize("query,expected", [
    ("lip", ["Lip Gloss"]),                    # name
    ("SENSITIVE", ["Cleanser"]),               # short description, case-insensitive
    ("makeup", ["Lip Gloss"]),                 # category name
    ("rose petal", ["Lip Gloss"]),             # preferences, multiple words
    ("cream", ["Dress"]),                      # notes
    ("rose dress", []),                        # all terms must match (AND)
    ("   ", None),                             # blank = everything
])
def test_search_fields(query, expected):
    got = names(c.apply_filters(CATALOG, Filters(query=query, sort="name")))
    assert got == (sorted(names(CATALOG)) if expected is None else expected)


def test_budget_uses_range_overlap():
    f = lambda lo, hi, **kw: names(c.apply_filters(CATALOG, Filters(budget=(D(lo), D(hi)), sort="name", **kw)))
    assert f(800, 1000, include_unpriced=False) == ["Lip Gloss"]            # 450-900 overlaps 800-1000
    assert f(900, 950, include_unpriced=False) == ["Lip Gloss"]            # touching at the edge counts
    assert f(901, 1100, include_unpriced=False) == []                       # just outside every range
    assert f(0, 10000, include_unpriced=False) == sorted(n for n in names(CATALOG) if n != "Poetry Book")
    assert f(1200, 1200, include_unpriced=False) == ["Treat Box"]           # single price inside budget


def test_unpriced_products_follow_the_include_flag():
    on = names(c.apply_filters(CATALOG, Filters(budget=(D(0), D(10)), include_unpriced=True)))
    off = names(c.apply_filters(CATALOG, Filters(budget=(D(0), D(10)), include_unpriced=False)))
    assert on == ["Poetry Book"] and off == []


def test_status_and_category_filters_combine_with_search():
    assert names(c.apply_filters(CATALOG, Filters(status="Claimed"))) == ["Dog Toy"]
    assert "Dog Toy" not in names(c.apply_filters(CATALOG, Filters(status="Available")))
    assert names(c.apply_filters(CATALOG, Filters(category_id="c1", query="lip"))) == ["Lip Gloss"]
    assert names(c.apply_filters(CATALOG, Filters(category_id=c.UNCATEGORIZED))) == ["Treat Box"]
    assert c.apply_filters(CATALOG, Filters(category_id="c1", status="Claimed", query="lip")) == []


def test_sorting_is_deterministic_and_puts_unpriced_last():
    assert names(c.sort_products(CATALOG, "newest"))[0] == "Dog Toy"
    assert names(c.sort_products(CATALOG, "name")) == sorted(names(CATALOG))
    asc = names(c.sort_products(CATALOG, "price_asc"))
    assert asc == ["Dog Toy", "Lip Gloss", "Cleanser", "Treat Box", "Dress", "Poetry Book"]
    desc = names(c.sort_products(CATALOG, "price_desc"))
    assert desc == ["Dress", "Treat Box", "Lip Gloss", "Cleanser", "Dog Toy", "Poetry Book"]
    with pytest.raises(ValueError):
        c.sort_products(CATALOG, "bogus")


def test_equal_prices_break_ties_by_name():
    a, b = prod("Beta", 100, 100), prod("Alpha", 100, 100)
    assert names(c.sort_products([a, b], "price_asc")) == ["Alpha", "Beta"]


def test_filters_never_mutate_inputs():
    before = list(CATALOG)
    c.apply_filters(CATALOG, Filters(query="x", status="Claimed", sort="price_desc"))
    assert CATALOG == before


def test_price_bounds_and_formatting():
    assert c.price_bounds(CATALOG) == (D(300), D(4500))
    assert c.price_bounds([prod("x")]) is None
    assert c.format_price(CATALOG[0]) == "₹450 – ₹900"
    assert c.format_price(CATALOG[2]) == "₹600"
    assert c.format_price(CATALOG[4], "$") == "$1,200"
    assert c.format_price(CATALOG[3]) == ""
    assert c.format_price(prod("y", "10.5", "20.25")) == "₹10.50 – ₹20.25"


def test_parse_catalog_builds_typed_products():
    payload = {"categories": [{"id": "k1", "name": "Books", "kind": "regular"}],
               "products": [{"id": "p1", "name": "N", "category_id": "k1", "price_min": 10.5, "price_max": None,
                             "created_at": "2026-10-11T13:00:00.123456+00:00", "claimed": True, "claimed_by": "Mom",
                             "links": [{"source_name": "A", "url": "https://a.b", "note": None}]}]}
    p = c.parse_catalog(payload).products[0]
    assert p.category_name == "Books" and p.price_min == D("10.5") and p.claimed_by == "Mom"
    assert p.links[0].note == "" and p.created_at.year == 2026
