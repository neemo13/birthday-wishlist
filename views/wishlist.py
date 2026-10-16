"""The shopping-style wishlist: category nav, search, filters, sorting, grid, product details."""
from __future__ import annotations

from decimal import Decimal

import math

import streamlit as st

from wishlist import catalog, claims, content, dad, family, state, storage, ui
from views import dad as dad_view
from wishlist.auth import Session
from wishlist.catalog import Filters, Product
from wishlist.claims import ClaimError
from wishlist.security import ValidationError, throttle_register_failure, throttle_remaining, throttle_reset, validate_url
from wishlist.ui import esc, esc_multiline

def _int_bounds(bounds):
    """Whole-number slider limits that always contain every price."""
    return (math.floor(bounds[0]), math.ceil(bounds[1])) if bounds else None


STATE_KEYS = ("wl_query", "wl_cat", "wl_budget", "wl_unpriced", "wl_status", "wl_sort")


# ---------------------------------------------------------------- pure HTML builders (unit-tested)
def card_html(p: Product, img_url: str | None, currency: str) -> str:
    img = (f'<img class="gw-img" src="{esc(img_url)}" alt="{esc(p.name)}" loading="lazy">'
           if img_url else '<div class="gw-img gw-img--placeholder" aria-hidden="true">🎀</div>')
    badge = f'<span class="gw-badge gw-badge--{"claimed" if p.claimed else "available"}">{p.status}</span>'
    by = f'<div class="gw-claimed-by">claimed by {esc(p.claimed_by)}</div>' if p.claimed and p.claimed_by else ""
    price = f'<div class="gw-price">{esc(catalog.format_price(p, currency))}</div>' if catalog.format_price(p, currency) else ""
    cat = f'<div class="gw-cat">{esc(p.category_name)}</div>' if p.category_name else '<div class="gw-cat">&nbsp;</div>'
    desc = f'<p class="gw-desc">{esc(p.short_description)}</p>' if p.short_description else ""
    return (f'{img}<div class="gw-card-body"><div class="gw-card-top">{cat}{badge}</div>'
            f'<div class="gw-card-title">{esc(p.name)}</div>{price}{desc}{by}</div>')


def links_html(p: Product) -> str:
    parts = []
    for link in p.links:
        try:
            url = validate_url(link.url)          # re-check at render time: only http(s) links are ever shown
        except ValidationError:
            continue
        note = f'<span class="gw-link-note">{esc(link.note)}</span>' if link.note else ""
        parts.append(f'<div class="gw-link-row"><a class="gw-link" href="{esc(url)}" target="_blank" '
                     f'rel="noopener noreferrer">{esc(link.source_name)} ↗</a>{note}</div>')
    return "".join(parts)


# ---------------------------------------------------------------- product details dialog
OPEN_KEY = "_open_product"


def _close_dialog() -> None:
    """Forget which gift is open (used when the dialog is dismissed or finished)."""
    st.session_state.pop(OPEN_KEY, None)


@st.dialog("Gift details", width="medium", on_dismiss=_close_dialog)
def product_dialog(p: Product, img_url: str | None, currency: str, sess: Session | None = None) -> None:
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown(f'<img class="gw-img gw-dialog-img" src="{esc(img_url)}" alt="{esc(p.name)}">' if img_url else
                    '<div class="gw-img gw-dialog-img gw-img--placeholder" aria-hidden="true">🎀</div>', unsafe_allow_html=True)
    with right:
        badge = f'<span class="gw-badge gw-badge--{"claimed" if p.claimed else "available"}">{p.status}</span>'
        by = f' <span class="gw-muted">by {esc(p.claimed_by)}</span>' if p.claimed and p.claimed_by else ""
        price = catalog.format_price(p, currency)
        st.markdown(f'<div class="gw-cat">{esc(p.category_name)}</div><h2 class="gw-dialog-title">{esc(p.name)}</h2>'
                    + (f'<div class="gw-price gw-price--lg">{esc(price)}</div>' if price else "")
                    + f'<div>{badge}{by}</div>'
                    + (f'<p class="gw-dialog-desc">{esc_multiline(p.short_description)}</p>' if p.short_description else ""),
                    unsafe_allow_html=True)
    if p.preferences:
        st.markdown(f'<div class="gw-block"><div class="gw-eyebrow">Details &amp; preferences</div>'
                    f'<p>{esc_multiline(p.preferences)}</p></div>', unsafe_allow_html=True)
    if p.notes:
        st.markdown(f'<div class="gw-block"><div class="gw-eyebrow">Extra notes</div>'
                    f'<p>{esc_multiline(p.notes)}</p></div>', unsafe_allow_html=True)
    links = links_html(p)
    if links:
        st.markdown(f'<div class="gw-block"><div class="gw-eyebrow">Where to find it</div>{links}</div>',
                    unsafe_allow_html=True)
    if sess is not None and not sess.is_admin:
        _claim_area(p, sess)
    elif sess is not None and p.claimed:
        st.caption("You can release claims from Admin Studio -> Claims.")


# ---------------------------------------------------------------- claim / release (inside the dialog)
def _refresh_and_close(message: str, kind: str = "success", celebrate: str | None = None) -> None:
    _close_dialog()
    ui.flash(kind, message)
    if celebrate:
        ui.celebrate(celebrate)          # only reached after the database confirmed the operation
    st.rerun()                           # closes the dialog and reloads the list


def _claim_area(p: Product, sess: Session) -> None:
    token = state.token()
    step = f"claiming_{p.id}" if not p.claimed else f"releasing_{p.id}"
    with st.container(key=f"actions_{p.id}"):
        if not st.session_state.get(step):
            label = "Release this gift" if p.claimed else "Claim this gift 🎁"
            slot = st.empty()
            if not slot.button(label, key=f"{step}_open", type="secondary" if p.claimed else "primary", width="stretch"):
                return
            slot.empty()                                # swap the button for the form, in this same run (no rerun needed)
            st.session_state[step] = True
        (_release_form if p.claimed else _claim_form)(p, sess, token)


def _claim_form(p: Product, sess: Session, token: str) -> None:
    names = family.list_names(token)
    by_slug = {n["slug"]: n["display_name"] for n in names}
    st.markdown(f"**Claim “{esc(p.name)}”** - choose a PIN only you will know. You'll need it to release this gift later.")
    with st.form(f"claim_form_{p.id}", border=False):
        slug = st.selectbox("Who is claiming?", list(by_slug), format_func=by_slug.get, key=f"cl_name_{p.id}",
                            index=list(by_slug).index(sess.family_slug) if sess.family_slug in by_slug else 0)
        pin = st.text_input("Gift PIN (4-8 digits)", type="password", max_chars=8, key=f"cl_pin_{p.id}")
        pin2 = st.text_input("Type the PIN again", type="password", max_chars=8, key=f"cl_pin2_{p.id}")
        ok = st.checkbox("Yes, I'm claiming this gift", key=f"cl_ok_{p.id}")
        go = st.form_submit_button("Confirm claim ✨", type="primary", width="stretch")
    if go:
        if not ok:
            st.error("Please tick the box to confirm.", icon="🎀")
            return
        try:
            claims.claim(token, p.id, slug, pin, pin2)
        except ClaimError as exc:
            if exc.code in ("already_claimed", "unavailable"):
                _refresh_and_close(str(exc), "info")
            st.error(str(exc), icon="🎀")
            return
        except ValidationError as exc:
            st.error(str(exc), icon="🎀")
            return
        _refresh_and_close(f"It's yours to give! “{p.name}” is now claimed. ♡", celebrate="claim")


def _release_form(p: Product, sess: Session, token: str) -> None:
    names = family.list_names(token)
    st.markdown(f"**Release “{esc(p.name)}”** - enter the claimant's name and the PIN chosen for this gift.")
    with st.form(f"release_form_{p.id}", border=False):
        name = st.selectbox("Name of the person who claimed it", [n["display_name"] for n in names], key=f"rl_name_{p.id}")
        pin = st.text_input("This gift's PIN", type="password", max_chars=8, key=f"rl_pin_{p.id}")
        ok = st.checkbox("Yes, make this gift available again", key=f"rl_ok_{p.id}")
        go = st.form_submit_button("Release gift", type="primary", width="stretch")
    if go:
        wait = throttle_remaining(st.session_state, "release")
        if wait:
            st.error(f"Please wait {wait} seconds before trying again.", icon="⏳")
            return
        if not ok:
            st.error("Please tick the box to confirm.", icon="🎀")
            return
        try:
            claims.release(token, p.id, name, pin)
        except ClaimError as exc:
            if exc.code == "not_claimed":
                _refresh_and_close(str(exc), "info")
            if exc.code == "failed":
                throttle_register_failure(st.session_state, "release")
            st.error(str(exc), icon="🎀")
            return
        throttle_reset(st.session_state, "release")
        _refresh_and_close(f"“{p.name}” is available again. ♡", celebrate="release")


# ---------------------------------------------------------------- filters from widget state
def _clear_filters() -> None:
    for k in STATE_KEYS:
        st.session_state.pop(k, None)


def _filters_from_state(visible: list[str], cats: list, bounds) -> Filters:
    ss = st.session_state
    query = (ss.get("wl_query", "") or "").strip()[:100] if "search" in visible else ""
    if "filters" not in visible:
        return Filters(query=query)
    ib = _int_bounds(bounds)
    label_to_id = {c.name: c.id for c in cats} | {"Uncategorized": catalog.UNCATEGORIZED}
    chosen = ss.get("wl_cat")
    budget = ss.get("wl_budget")
    return Filters(
        query=query,
        category_id=label_to_id.get(chosen) if chosen and chosen != "All" else None,
        budget=(Decimal(str(budget[0])), Decimal(str(budget[1])))
        if ib and budget and tuple(budget) != ib else None,
        include_unpriced=ss.get("wl_unpriced", True),
        status=ss.get("wl_status") or "All",
        sort={v: k for k, v in catalog.SORT_OPTIONS.items()}.get(ss.get("wl_sort"), "newest"),
    )


def render(sess: Session) -> None:
    token = state.token()
    settings = content.get_settings(token)
    data = catalog.load_catalog(token)
    currency = settings["wishlist"]["currency"]
    visible = content.visible_sections(settings, "wishlist")
    cats = [c for c in data.categories if c.kind == "regular"]
    dad_cat = next((c for c in data.categories if c.kind == "dad_only"), None)   # the database only returns it to Dad/admin
    dad_label = f"🔒 {dad_cat.name}" if dad_cat else None
    dad_selected = bool(dad_label) and st.session_state.get("wl_cat") == dad_label
    bounds = catalog.price_bounds(data.products)
    ib = _int_bounds(bounds)
    if ib and "wl_budget" in st.session_state:                   # drop a stale slider value if prices changed
        lo, hi = st.session_state["wl_budget"]
        if not (ib[0] <= lo <= hi <= ib[1]):
            st.session_state.pop("wl_budget")
    flt = _filters_from_state(visible, cats, bounds)
    results = catalog.apply_filters(data.products, flt)

    if dad_label and "filters" not in visible:                    # keep the private page reachable if filters are hidden
        st.pills("Category", ["All", dad_label], key="wl_cat", selection_mode="single", default="All",
                 label_visibility="collapsed")
    for section in visible:
        if section == "intro":
            st.markdown(f'<div class="gw-page-head"><h1>{esc(settings["wishlist"]["heading"])}</h1>'
                        f'<p class="gw-muted">{esc_multiline(settings["wishlist"]["intro"])}</p></div>',
                        unsafe_allow_html=True)
        elif section == "search" and not dad_selected:
            st.text_input("Search the wishlist", key="wl_query", max_chars=100, label_visibility="collapsed",
                          placeholder="🔍  Search by name, colour, brand, notes…")
        elif section == "filters":
            _render_filters(cats, data.products, bounds, currency, dad_label, dad_selected)
        elif section == "grid":
            if dad_selected:
                dad_view.render(sess)
            else:
                _render_grid(results, data.products, flt, token, currency, sess)


def _render_filters(cats, products, bounds, currency, dad_label=None, dad_selected=False) -> None:
    options = ["All"] + [c.name for c in cats]
    if any(p.category_id is None for p in products):
        options.append("Uncategorized")
    if dad_label:
        options.append(dad_label)
    st.pills("Category", options, key="wl_cat", selection_mode="single", default="All",
             label_visibility="collapsed")
    if dad_selected:
        return
    with st.container(key="filters_box"):
        c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
        with c1:
            ib = _int_bounds(bounds)
            if ib and ib[0] < ib[1]:
                step = max(1, 10 ** (len(str(ib[1] - ib[0])) - 2))
                st.slider("Budget", ib[0], ib[1], value=ib, step=step, key="wl_budget", format=f"{currency}%d")
                st.checkbox("Include gifts with no price", value=True, key="wl_unpriced")
            else:
                st.caption("Price filter appears once gifts have different prices.")
        with c2:
            st.selectbox("Availability", catalog.STATUS_OPTIONS, key="wl_status")
        with c3:
            st.selectbox("Sort by", list(catalog.SORT_OPTIONS.values()), key="wl_sort")


def _render_grid(results, all_products, flt, token, currency, sess) -> None:
    if not all_products:
        st.markdown('<div class="gw-empty"><div class="gw-empty-icon">🎁</div><h3>The list is still being wrapped</h3>'
                    '<p class="gw-muted">Nothing here yet - please check back soon ♡</p></div>', unsafe_allow_html=True)
        return
    st.markdown(f'<p class="gw-muted gw-count">Showing {len(results)} of {len(all_products)} gifts</p>',
                unsafe_allow_html=True)
    if not results:
        st.markdown('<div class="gw-empty"><div class="gw-empty-icon">🔍</div><h3>No gifts match that</h3>'
                    '<p class="gw-muted">Try a different word, or clear the filters.</p></div>', unsafe_allow_html=True)
        st.button("Clear filters", on_click=_clear_filters, key="clear_filters")
        return
    urls = storage.signed_urls(token, [p.image_path for p in results], st.session_state.setdefault("_img_cache", {}))
    with st.container(key="grid"):
        for p in results:
            with st.container(key=f"card_{p.id}"):
                st.markdown(card_html(p, urls.get(p.image_path), currency), unsafe_allow_html=True)
                if st.button("View details", key=f"open_{p.id}", width="stretch"):
                    st.session_state[OPEN_KEY] = p.id
    open_id = st.session_state.get(OPEN_KEY)                       # explicit state: survives full reruns
    if open_id:
        target = next((p for p in all_products if p.id == open_id), None)
        if target is None:                                         # archived / hidden meanwhile
            _close_dialog()
        else:
            img = storage.signed_urls(token, [target.image_path], st.session_state.setdefault("_img_cache", {}))
            product_dialog(target, img.get(target.image_path), currency, sess)
