"""Pure validation helpers of the admin layer (no database)."""
from decimal import Decimal as D

import pytest

from wishlist import admin
from wishlist.security import ValidationError


@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), ("  ", None), (1200, D("1200.00")), ("1,200", D("1200.00")), ("₹ 899.5", D("899.50")),
    (0, D("0.00")), (12.345, D("12.35")), ("$10", D("10.00")),
])
def test_parse_price_accepts(raw, expected):
    assert admin.parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "-5", "NaN", "Infinity", "1e400", "100000000", "1.2.3"])
def test_parse_price_rejects(raw):
    with pytest.raises(ValidationError):
        admin.parse_price(raw)


def row(order, name="", url="", note=""):
    return {"order": order, "source_name": name, "url": url, "note": note}


def test_links_are_ordered_by_the_order_column_then_row_position():
    links = admin.build_links([row(2, "B", "https://b.example"), row(1, "A", "https://a.example"),
                               row(2, "C", "https://c.example"), row(3), row(4)])
    assert [l["source_name"] for l in links] == ["A", "B", "C"]


def test_blank_link_rows_are_ignored_and_half_filled_rows_rejected():
    assert admin.build_links([row(1), row(2)]) == []
    for bad in (row(1, "Only name"), row(1, url="https://only.url"), row(1, note="just a note")):
        with pytest.raises(ValidationError):
            admin.build_links([bad])


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x.y", "www.no-scheme.com", "https://a b.c", "//x.y"])
def test_links_reject_unsafe_urls(url):
    with pytest.raises(ValidationError):
        admin.build_links([row(1, "Shop", url)])


def test_too_many_links_rejected():
    rows = [row(i, f"S{i}", f"https://s{i}.example") for i in range(1, admin.MAX_LINKS + 2)]
    with pytest.raises(ValidationError):
        admin.build_links(rows)


def base(**kw):
    args = dict(product_id=None, name="Lip gloss", category_id=None, short_description="", price_min=None,
                price_max=None, preferences="", notes="", links=[])
    return admin.build_product_payload(**{**args, **kw})


def test_product_payload_rules():
    assert base(name="  Lip   gloss  ")["name"] == "Lip   gloss"
    assert base(price_min=100, price_max=100)["price_min"] == "100.00"
    assert base()["price_min"] is None and base()["category_id"] is None
    for bad in (dict(name="   "), dict(name="x" * 121), dict(price_min=500, price_max=100), dict(notes="n" * 2001)):
        with pytest.raises(ValidationError):
            base(**bad)


def test_sections_payload_validates_and_orders():
    rows = {"homepage": [("portrait", True, 3), ("message", True, 1), ("cta", False, 2)],
            "wishlist": [("intro", True, 1), ("search", True, 2), ("filters", True, 3), ("grid", True, 4)]}
    out = admin.build_sections_payload(rows)
    assert [s["id"] for s in out["homepage"]] == ["message", "cta", "portrait"] and out["homepage"][1]["visible"] is False
    with pytest.raises(ValidationError):
        admin.build_sections_payload({"homepage": [("portrait", True, 1), ("portrait", True, 2), ("cta", True, 3)], "wishlist": rows["wishlist"]})
    with pytest.raises(ValidationError):
        admin.build_sections_payload({"homepage": [("evil", True, 1), ("message", True, 2), ("cta", True, 3)], "wishlist": rows["wishlist"]})
