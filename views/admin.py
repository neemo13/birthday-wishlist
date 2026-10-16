"""Admin Studio (Birthday Girl only). The view never decides permission: admin.load_snapshot() and every
admin.* call re-verify the admin session in PostgreSQL."""
from __future__ import annotations

import streamlit as st

from wishlist import admin, content, credentials, family, state, storage, ui
from wishlist.auth import Session
from wishlist.security import PermissionDenied, ValidationError
from wishlist.storage import UploadError
from wishlist.ui import esc

NEW = "__new__"
ACCEPTED = ["jpg", "jpeg", "png", "webp"]


def _attempt(action, ok_message: str) -> bool:
    """Run an admin action; show a friendly error or flash success and rerun."""
    try:
        action()
    except (ValidationError, UploadError) as exc:
        st.error(str(exc), icon="🎀")
        return False
    ui.flash("success", ok_message)
    st.rerun()
    return True


def _img_cache() -> dict:
    return st.session_state.setdefault("_img_cache", {})


def render(sess: Session) -> None:
    token = state.token()
    snap = admin.load_snapshot(token)          # raises PermissionDenied unless the DB says admin
    st.markdown('<div class="gw-page-head"><div class="gw-eyebrow">only for you</div><h1>Admin Studio</h1>'
                '<p class="gw-muted">Everything about your wishlist, in one pretty place.</p></div>', unsafe_allow_html=True)
    tabs = st.tabs(["Overview", "Gifts", "Categories", "Website", "Portrait", "Family & access", "Claims", "Dad Only"])
    with tabs[0]:
        _overview(token, snap)
    with tabs[1]:
        _gifts(token, snap)
    with tabs[2]:
        _categories(token, snap)
    with tabs[3]:
        _website(token)
    with tabs[4]:
        _portrait(token)
    with tabs[5]:
        _family(token)
    with tabs[6]:
        _claims(token, snap)
    with tabs[7]:
        _dad(token)


# ------------------------------------------------------------------ overview
def _overview(token, snap) -> None:
    c = snap.counts
    cards = [("Active gifts", c["active"]), ("Available", snap.available), ("Claimed", c["claimed"]),
             ("Categories", c["categories"]), ("Archived", c["archived"])]
    st.markdown('<div class="gw-metrics">' + "".join(
        f'<div class="gw-metric"><div class="gw-metric-n">{n}</div><div class="gw-metric-l">{esc(label)}</div></div>'
        for label, n in cards) + "</div>", unsafe_allow_html=True)
    st.markdown('<div class="gw-eyebrow" style="margin-top:1.2rem">recent activity</div>', unsafe_allow_html=True)
    items = admin.recent_activity(token)
    if not items:
        st.caption("Nothing yet.")
    for it in items:
        st.markdown(f'<div class="gw-activity"><b>{esc(it["action"].replace("_", " "))}</b>'
                    f'<span class="gw-muted"> · {esc(it["created_at"][:16].replace("T", " "))} UTC</span></div>',
                    unsafe_allow_html=True)


# ------------------------------------------------------------------ gifts
def _gifts(token, snap) -> None:
    ss = st.session_state
    if "_adm_select_next" in ss:                                    # set before the widget exists (Streamlit rule)
        ss["adm_product_sel"] = ss.pop("_adm_select_next")
    show_archived = st.toggle("Include archived gifts in the list", key="adm_show_archived")
    visible = [p for p in snap.products if show_archived or not p.is_archived]
    options = {NEW: "➕ Add a new gift"} | {p.id: p.name + ("  (archived)" if p.is_archived else "") for p in visible}
    if ss.get("adm_product_sel") not in options:
        ss["adm_product_sel"] = NEW
    sel = st.selectbox("Choose a gift to edit", list(options), format_func=options.get, key="adm_product_sel")
    product = next((p for p in snap.products if p.id == sel), None)
    _gift_form(token, snap, product)
    if product:
        _archive_controls(token, product)


def _gift_form(token, snap, p) -> None:
    sid = p.id if p else "new"
    cats = [c for c in snap.categories if c["kind"] == "regular"]
    cat_ids = [""] + [c["id"] for c in cats]
    cat_names = {"": "Uncategorized"} | {c["id"]: c["name"] for c in cats}
    with st.form(f"gift_form_{sid}", clear_on_submit=p is None):
        name = st.text_input("Gift name *", value=p.name if p else "", max_chars=120, key=f"pf_name_{sid}")
        category = st.selectbox("Category", cat_ids, format_func=cat_names.get, key=f"pf_cat_{sid}",
                                index=cat_ids.index(p.category_id) if p and p.category_id in cat_ids else 0)
        short = st.text_input("Short description", value=p.short_description if p else "", max_chars=300, key=f"pf_short_{sid}")
        c1, c2 = st.columns(2)
        pmin = c1.number_input("Minimum price", min_value=0.0, step=50.0, format="%.2f", key=f"pf_min_{sid}",
                               value=float(p.price_min) if p and p.price_min is not None else None)
        pmax = c2.number_input("Maximum price", min_value=0.0, step=50.0, format="%.2f", key=f"pf_max_{sid}",
                               value=float(p.price_max) if p and p.price_max is not None else None)
        prefs = st.text_area("Details & preferences (shade, size, model, colour…)", value=p.preferences if p else "",
                             max_chars=2000, key=f"pf_prefs_{sid}")
        notes = st.text_area("Extra notes", value=p.notes if p else "", max_chars=2000, key=f"pf_notes_{sid}")

        st.markdown('<div class="gw-eyebrow">photo</div>', unsafe_allow_html=True)
        if p and p.image_path:
            url = storage.signed_urls(token, [p.image_path], _img_cache()).get(p.image_path)
            if url:
                st.markdown(f'<img class="gw-img gw-thumb" src="{esc(url)}" alt="Current photo">', unsafe_allow_html=True)
        upload = st.file_uploader("Upload or replace the photo (JPG, PNG or WebP, up to 5 MB)", type=ACCEPTED, key=f"pf_img_{sid}")
        remove = st.checkbox("Remove the current photo", key=f"pf_rmimg_{sid}", disabled=not (p and p.image_path))

        st.markdown('<div class="gw-eyebrow">shopping links (blank rows are ignored; "Order" sets the sequence)</div>', unsafe_allow_html=True)
        rows = []
        for i in range(5):
            link = p.links[i] if p and i < len(p.links) else None
            a, b, c, d = st.columns([1, 2, 3, 2])
            rows.append({"order": a.number_input("Order", 1, 5, i + 1, key=f"pf_lo_{sid}_{i}", label_visibility="collapsed"),
                         "source_name": b.text_input("Retailer", value=link.source_name if link else "", key=f"pf_ls_{sid}_{i}",
                                                     placeholder="Retailer", label_visibility="collapsed", max_chars=60),
                         "url": c.text_input("Web address", value=link.url if link else "", key=f"pf_lu_{sid}_{i}",
                                             placeholder="https://…", label_visibility="collapsed", max_chars=2000),
                         "note": d.text_input("Note", value=link.note if link else "", key=f"pf_ln_{sid}_{i}",
                                              placeholder="Note (optional)", label_visibility="collapsed", max_chars=200)})
        submitted = st.form_submit_button("Save gift ✨" if p else "Add gift ✨", type="primary")
    if submitted:
        def run():
            new_id = admin.save_product(token, product_id=p.id if p else None, name=name, category_id=category or None,
                                        short_description=short, price_min=pmin, price_max=pmax, preferences=prefs,
                                        notes=notes, links=rows, image=upload.getvalue() if upload else None,
                                        remove_image=remove)
            st.session_state["_adm_select_next"] = new_id
        _attempt(run, "Gift saved ♡")


def _archive_controls(token, p) -> None:
    if p.is_archived:
        if st.button("Restore this gift", key=f"restore_{p.id}"):
            _attempt(lambda: admin.set_archived(token, p.id, False), "Gift restored ♡")
        return
    with st.expander("Archive this gift"):
        st.write("Archiving hides the gift from the family wishlist but keeps everything saved. "
                 + ("**It is currently claimed:** the claim stays on record and is still there if you restore it. "
                    "Use the Claims tab if you want to release it." if p.claimed else "You can restore it any time."))
        ok = st.checkbox("Yes, archive this gift", key=f"arch_ok_{p.id}")
        if st.button("Archive", key=f"arch_btn_{p.id}", disabled=not ok):
            _attempt(lambda: admin.set_archived(token, p.id, True), "Gift archived.")


# ------------------------------------------------------------------ categories
def _categories(token, snap) -> None:
    st.markdown('<div class="gw-eyebrow">add a category</div>', unsafe_allow_html=True)
    with st.form("cat_new", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        name = c1.text_input("Name *", max_chars=60, key="cat_new_name")
        desc = c2.text_input("Description", max_chars=300, key="cat_new_desc")
        if st.form_submit_button("Add category", type="primary"):
            _attempt(lambda: admin.save_category(token, name=name, description=desc), "Category added ♡")
    regular = [c for c in snap.categories if c["kind"] == "regular"]
    for c in snap.categories:
        label = f'{c["name"]}  ·  {c["product_count"]} gift(s)' + ("  ·  hidden" if c["is_hidden"] else "")
        with st.expander(("🔒 " if c["kind"] == "dad_only" else "") + label):
            with st.form(f"cat_form_{c['id']}"):
                n = st.text_input("Name", value=c["name"], max_chars=60, key=f"cat_name_{c['id']}")
                d = st.text_input("Description", value=c["description"], max_chars=300, key=f"cat_desc_{c['id']}")
                hidden, order = c["is_hidden"], c["sort_order"]
                if c["kind"] == "regular":
                    h1, h2 = st.columns(2)
                    hidden = h1.checkbox("Hidden from the family", value=c["is_hidden"], key=f"cat_hide_{c['id']}")
                    order = h2.number_input("Display order (smaller = earlier)", value=int(c["sort_order"]), step=10, key=f"cat_ord_{c['id']}")
                else:
                    st.caption("The private Dad Only page: you can rename it, but it can't be hidden, moved or deleted here.")
                if st.form_submit_button("Save category", type="primary"):
                    _attempt(lambda: admin.save_category(token, category_id=c["id"], name=n, description=d,
                                                         is_hidden=hidden, sort_order=order), "Category saved ♡")
            if c["kind"] == "regular":
                _delete_category(token, c, [x for x in regular if x["id"] != c["id"]])


def _delete_category(token, c, others) -> None:
    st.markdown("**Delete this category**")
    target = ""
    if c["product_count"]:
        choices = {"": "Make them uncategorized"} | {o["id"]: f"Move to {o['name']}" for o in others}
        st.caption(f'{c["product_count"]} gift(s) (including archived ones) are in this category - they are never deleted.')
        target = st.selectbox("What should happen to them?", list(choices), format_func=choices.get, key=f"cat_move_{c['id']}")
    ok = st.checkbox("Yes, delete this category", key=f"cat_del_ok_{c['id']}")
    if st.button("Delete category", key=f"cat_del_{c['id']}", disabled=not ok):
        _attempt(lambda: admin.delete_category(token, c["id"], reassign_to=target or None,
                                               uncategorize=bool(c["product_count"]) and not target), "Category deleted.")


# ------------------------------------------------------------------ website text + sections
def _website(token) -> None:
    settings = content.get_settings(token)
    hp, wl = settings["homepage"], settings["wishlist"]
    st.markdown('<div class="gw-eyebrow">birthday homepage text</div>', unsafe_allow_html=True)
    with st.form("site_home"):
        eyebrow = st.text_input("Small heading", value=hp["eyebrow"], max_chars=80, key="hp_eyebrow")
        heading = st.text_input("Big heading", value=hp["heading"], max_chars=100, key="hp_heading")
        subtitle = st.text_area("Subtitle", value=hp["subtitle"], max_chars=300, key="hp_subtitle", height=80)
        message = st.text_area("Birthday message", value=hp["message"], max_chars=600, key="hp_message", height=100)
        button = st.text_input("Button label", value=hp["button_label"], max_chars=60, key="hp_button")
        if st.form_submit_button("Save homepage text", type="primary"):
            _attempt(lambda: admin.save_homepage(token, eyebrow=eyebrow, heading=heading, subtitle=subtitle,
                                                 message=message, button_label=button), "Homepage text saved ♡")
    st.markdown('<div class="gw-eyebrow">wishlist page text</div>', unsafe_allow_html=True)
    with st.form("site_wish"):
        w_head = st.text_input("Heading", value=wl["heading"], max_chars=100, key="wl_heading")
        w_intro = st.text_area("Introduction", value=wl["intro"], max_chars=400, key="wl_intro", height=80)
        w_cur = st.text_input("Currency symbol shown before prices", value=wl["currency"], max_chars=5, key="wl_currency")
        if st.form_submit_button("Save wishlist text", type="primary"):
            _attempt(lambda: admin.save_wishlist_texts(token, heading=w_head, intro=w_intro, currency=w_cur), "Wishlist text saved ♡")
    st.markdown('<div class="gw-eyebrow">sections: show / hide and reorder</div>', unsafe_allow_html=True)
    with st.form("site_sections"):
        collected = {}
        for page, title in (("homepage", "Homepage"), ("wishlist", "Wishlist page")):
            st.markdown(f"**{title}**")
            rows = []
            for i, (sid, visible) in enumerate(content.section_items(settings, page)):
                a, b, c = st.columns([3, 1, 1])
                a.markdown(f'<div class="gw-sec-label">{esc(content.SECTION_LABELS[sid])}</div>', unsafe_allow_html=True)
                vis = b.checkbox("Show", value=visible, key=f"sec_vis_{page}_{sid}")
                order = c.number_input("Order", 1, 9, i + 1, key=f"sec_ord_{page}_{sid}", label_visibility="collapsed")
                rows.append((sid, vis, int(order)))
            collected[page] = rows
        if st.form_submit_button("Save sections", type="primary"):
            _attempt(lambda: admin.save_sections(token, collected), "Sections saved ♡")


# ------------------------------------------------------------------ portrait
def _portrait(token) -> None:
    path = content.get_settings(token)["homepage"].get("portrait_path")
    if path:
        url = storage.signed_urls(token, [path], _img_cache()).get(path)
        if url:
            st.markdown(f'<div class="gw-portrait-wrap"><div class="gw-portrait-frame"><img class="gw-portrait" src="{esc(url)}" alt="Your portrait"></div></div>',
                        unsafe_allow_html=True)
    else:
        st.info("No portrait yet - upload one below. It is stored privately and only shown after login.", icon="📷")
    with st.form("portrait_form", clear_on_submit=True):
        up = st.file_uploader("Choose your portrait (JPG, PNG or WebP, up to 5 MB)", type=ACCEPTED, key="portrait_upload")
        if st.form_submit_button("Save portrait", type="primary"):
            if up is None:
                st.error("Please choose a photo first.", icon="🎀")
            else:
                _attempt(lambda: admin.set_portrait(token, up.getvalue()), "Portrait saved ♡")
    if path and st.button("Remove portrait", key="portrait_remove"):
        _attempt(lambda: admin.set_portrait(token, None), "Portrait removed.")


# ------------------------------------------------------------------ family names + credentials
def _credential_form(token, key: str, kinds: dict[str, str]) -> None:
    kind_label = st.selectbox("Change", list(kinds), key=f"{key}_kind") if len(kinds) > 1 else next(iter(kinds))
    with st.form(f"{key}_form", clear_on_submit=True):
        new = st.text_input("New value", type="password", max_chars=128, key=f"{key}_new")
        again = st.text_input("Type it again", type="password", max_chars=128, key=f"{key}_again")
        current = st.text_input("Your current admin password (to confirm it's you)", type="password", max_chars=128, key=f"{key}_cur")
        if st.form_submit_button("Update", type="primary"):
            _attempt(lambda: credentials.change(token, current, kinds[kind_label], new, again), "Updated. ♡")


def _family(token) -> None:
    names = family.list_names(token)
    st.markdown('<div class="gw-eyebrow">family names (type them your own way)</div>', unsafe_allow_html=True)
    with st.form("family_names"):
        cols = st.columns(2)
        values = {n["slug"]: cols[i % 2].text_input({"grandmother": "Grandmother", "brother": "Brother", "mom": "Mom", "dad": "Dad"}[n["slug"]] + " (shown as)",
                                                    value=n["display_name"], max_chars=40, key=f"fam_{n['slug']}")
                  for i, n in enumerate(names)}
        if st.form_submit_button("Save names", type="primary"):
            _attempt(lambda: family.rename_all(token, values), "Names saved ♡")
    st.markdown('<div class="gw-eyebrow">passwords and PINs</div>', unsafe_allow_html=True)
    status = {i["kind"]: i for i in credentials.status(token)}
    st.caption("Current values are never shown. Status: " + ", ".join(
        f'{credentials.KINDS[k]} {"set ✓" if v["configured"] else "not set"}' for k, v in status.items() if k != "dad_only"))
    _credential_form(token, "cred", {"Family PIN": "family", "My admin password": "admin"})
    st.caption("Changing the family PIN signs every Gift Giver out. Changing your password signs out your other devices.")


# ------------------------------------------------------------------ claims
def _claims(token, snap) -> None:
    if not snap.claims:
        st.markdown('<div class="gw-empty"><div class="gw-empty-icon">🎁</div><h3>No active claims yet</h3></div>', unsafe_allow_html=True)
        return
    st.caption("If someone forgets their release PIN, you can release the claim here. The action is recorded in the activity log.")
    for cl in snap.claims:
        with st.container(key=f"claim_{cl['id']}"):
            st.markdown(f'**{esc(cl["product_name"])}** — claimed by {esc(cl["claimant"])}', unsafe_allow_html=True)
            ok = st.checkbox("Yes, release this claim", key=f"claim_ok_{cl['id']}")
            if st.button("Release claim", key=f"claim_rel_{cl['id']}", disabled=not ok):
                _attempt(lambda: admin.release_claim(token, cl["id"]), "Claim released.")


# ------------------------------------------------------------------ Dad Only settings
def _dad(token) -> None:
    status = {i["kind"]: i for i in credentials.status(token)}["dad_only"]
    st.caption(f'Dad Only page: PIN {"set ✓" if status["configured"] else "not set"}, '
               f'page is **{"on" if status["enabled"] else "off"}**. Dad only ever sees a message; there is no catalogue.')
    with st.form("dad_toggle", clear_on_submit=True):
        enabled = st.checkbox("Page is switched on", value=status["enabled"], key="dad_enabled")
        cur = st.text_input("Your current admin password", type="password", max_chars=128, key="dad_toggle_cur")
        if st.form_submit_button("Save", type="primary"):
            _attempt(lambda: credentials.change(token, cur, "dad_only", enabled=enabled), "Saved ♡")
    st.markdown('<div class="gw-eyebrow">set or change the Dad Only PIN</div>', unsafe_allow_html=True)
    _credential_form(token, "dadpin", {"Dad Only PIN": "dad_only"})
    st.markdown('<div class="gw-eyebrow">the message Dad sees</div>', unsafe_allow_html=True)
    page = admin.dad_page(token)
    with st.form("dad_msg"):
        title = st.text_input("Title", value=page.get("title", ""), max_chars=80, key="dad_title")
        msg = st.text_area("Message", value=page.get("message", ""), max_chars=1000, key="dad_msg_text", height=140)
        if st.form_submit_button("Save message", type="primary"):
            _attempt(lambda: admin.save_dad_page(token, title=title, message=msg), "Message saved ♡")
