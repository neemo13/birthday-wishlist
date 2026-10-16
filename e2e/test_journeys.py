"""Real-browser journeys. Each test starts from fresh sample data."""
import io

from PIL import Image
from playwright.sync_api import expect

from e2e.helpers import ENTER, cards, goto_wishlist, login, no_horizontal_overflow, open_login
from tests.conftest import ADMIN_PW, DAD_PIN, FAMILY_PIN


def test_login_is_first_and_shows_nothing_private(page):
    open_login(page)
    text = page.locator("body").inner_text()
    for private in ("Happy 21st", "The Wishlist", "Dad Only", "Admin Studio"):
        assert private not in text
    assert page.locator("img.gw-portrait").count() == 0
    page.get_by_label("I am the…").click()
    expect(page.get_by_role("option")).to_have_count(2)
    assert page.get_by_role("option").all_inner_texts() == ["Birthday Girl", "Gift Giver"]


def test_wrong_credentials_stay_on_login_with_a_generic_error(page):
    open_login(page)
    page.get_by_label("Family PIN", exact=True).fill("wrong-pin-123")
    page.get_by_role("button", name=ENTER).click()
    expect(page.get_by_text("That didn't match")).to_be_visible()
    assert page.locator(".st-key-pick_card").count() == 0 and "wrong-pin-123" not in page.locator("body").inner_text()


def test_direct_urls_and_query_parameters_grant_nothing(page):
    for suffix in ("?page=admin", "?nav_choice=admin", "?role=admin&dad=1", "#admin"):
        page.goto(page.base + "/" + suffix)
        expect(page.locator(".gw-login-title")).to_be_visible()
        assert "Admin Studio" not in page.locator("body").inner_text()


def test_family_journey_browse_search_details_and_logout(page):
    login(page, "Gift Giver", FAMILY_PIN, "mom")
    expect(page.locator(".gw-hero-title")).to_have_text("Happy 21st Birthday!")
    goto_wishlist(page)
    expect(cards(page)).to_have_count(7)
    page.get_by_placeholder("Search by name").fill("gloss")
    page.keyboard.press("Enter")
    expect(cards(page)).to_have_count(1)
    page.get_by_placeholder("Search by name").fill("")
    page.keyboard.press("Enter")
    expect(cards(page)).to_have_count(7)
    expect(page.locator("text=claimed by Mom")).to_be_visible()
    page.locator('[class*="st-key-card_"]', has_text="Rose Quartz Lip Gloss").get_by_role("button", name="View details").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("Shade: Rose Petal")).to_be_visible()
    links = dialog.locator("a.gw-link")
    assert links.all_inner_texts() == ["Amazon ↗", "Nykaa ↗"] and links.first.get_attribute("rel") == "noopener noreferrer"
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Log out").click()
    expect(page.locator(".gw-login-title")).to_be_visible()
    # Streamlit keeps the previous page's elements (dimmed) for a moment until the new run replaces them; wait for that,
    # then require that the private content is really gone, not merely hidden.
    expect(cards(page)).to_have_count(0)
    expect(page.locator("body")).not_to_contain_text("Rose Quartz")


def test_claim_then_release_end_to_end(page, data):
    login(page, "Gift Giver", FAMILY_PIN, "mom")
    goto_wishlist(page)
    card = page.locator('[class*="st-key-card_"]', has_text="Gentle Cleanser")
    card.get_by_role("button", name="View details").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Claim this gift 🎁").click()
    dialog.get_by_label("Gift PIN (4-8 digits)").fill("2468")
    dialog.get_by_label("Type the PIN again").fill("2468")
    dialog.get_by_text("Yes, I'm claiming this gift").click()
    dialog.get_by_role("button", name="Confirm claim ✨").click()
    expect(page.get_by_text("is now claimed")).to_be_visible()
    expect(page.locator('[data-testid="stBalloons"]').first).to_be_attached()
    assert data.pg.sql("select family_slug, status from claims where product_id=%s", [data.ids["Gentle Cleanser"]]) == [("mom", "active")]
    assert "2468" not in str(data.pg.sql("select * from claims"))

    page.get_by_role("button", name="Log out").click()                       # Dad releases using Mom's name + PIN
    login(page, "Gift Giver", FAMILY_PIN, "dad")
    goto_wishlist(page)
    page.locator('[class*="st-key-card_"]', has_text="Gentle Cleanser").get_by_role("button", name="View details").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("Claimed")).to_be_visible()
    dialog.get_by_role("button", name="Release this gift").click()
    dialog.get_by_label("This gift's PIN").fill("0000")
    dialog.get_by_text("Yes, make this gift available again").click()
    dialog.get_by_role("button", name="Release gift").click()
    expect(dialog.get_by_text("That name and PIN don't match")).to_be_visible()      # wrong PIN: nothing changes
    dialog.get_by_label("This gift's PIN").fill("2468")
    dialog.get_by_role("combobox").first.click()
    page.get_by_role("option", name="Mom").click()
    dialog.get_by_role("button", name="Release gift").click()
    expect(page.get_by_text("is available again")).to_be_visible()
    assert data.pg.sql("select status, pin_hash from claims where product_id=%s", [data.ids["Gentle Cleanser"]]) == [("released", None)]


def test_dad_only_page_is_gated_by_name_and_pin(page):
    login(page, "Gift Giver", FAMILY_PIN, "mom")
    goto_wishlist(page)
    assert "Dad Only" not in page.locator("body").inner_text()
    page.get_by_role("button", name="Log out").click()

    login(page, "Gift Giver", FAMILY_PIN, "dad")
    goto_wishlist(page)
    expect(cards(page)).to_have_count(7)                                      # Dad keeps the ordinary wishlist
    page.locator("button", has_text="Dad Only").click()
    expect(page.get_by_text("Just for Dad")).to_be_visible()
    assert "birthday to remember" not in page.locator("body").inner_text()
    page.get_by_label("Dad Only PIN").fill("wrong-pin-000")
    page.get_by_role("button", name="Open ✨").click()
    expect(page.get_by_text("That PIN didn't match")).to_be_visible()
    page.get_by_label("Dad Only PIN").fill(DAD_PIN)
    page.get_by_role("button", name="Open ✨").click()
    expect(page.get_by_text("birthday to remember")).to_be_visible()
    assert page.locator('[class*="st-key-card_"]').count() == 0 and "₹" not in page.locator(".gw-dad-card").inner_text()
    page.get_by_role("button", name="Back to the wishlist").click()
    expect(cards(page)).to_have_count(7)


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (240, 240), (200, 90, 130)).save(buf, "PNG")
    return buf.getvalue()


def test_admin_adds_a_gift_with_a_photo_and_the_family_sees_it(page, data):
    login(page, "Birthday Girl", ADMIN_PW)
    page.get_by_role("radio", name="Admin Studio").click() if page.get_by_role("radio", name="Admin Studio").count() else \
        page.locator('.st-key-topbar [role="radiogroup"] button', has_text="Admin Studio").click()
    expect(page.locator(".gw-metrics")).to_be_visible()
    page.get_by_role("tab", name="Gifts").click()
    page.get_by_label("Gift name *").fill("Pearl Earrings")
    page.get_by_label("Short description").fill("Tiny and classy")
    page.locator('input[type="file"]').first.set_input_files({"name": "pearls.png", "mimeType": "image/png", "buffer": _png_bytes()})
    expect(page.get_by_text("pearls.png")).to_be_visible()
    page.get_by_role("button", name="Add gift ✨").click()
    expect(page.get_by_text("Gift saved")).to_be_visible()
    row = data.pg.sql("select name, image_path from products where name='Pearl Earrings'")[0]
    assert row[1] and row[1].startswith("product/")
    page.get_by_role("button", name="Log out").click()

    login(page, "Gift Giver", FAMILY_PIN, "brother")
    goto_wishlist(page)
    card = page.locator('[class*="st-key-card_"]', has_text="Pearl Earrings")
    expect(card).to_be_visible()
    expect(card.locator("img.gw-img")).to_have_attribute("src", __import__("re").compile(r"^(data:image|https://)"))


def test_mobile_layouts_have_no_horizontal_overflow(mobile):
    open_login(mobile)
    assert no_horizontal_overflow(mobile)
    login(mobile, "Gift Giver", FAMILY_PIN, "mom")
    assert no_horizontal_overflow(mobile)
    goto_wishlist(mobile)
    expect(cards(mobile)).to_have_count(7)
    assert no_horizontal_overflow(mobile)
    columns = mobile.evaluate("""() => new Set([...document.querySelectorAll('[class*="st-key-card_"]')]
        .map(e => Math.round(e.getBoundingClientRect().left))).size""")
    assert columns == 2                                                       # two-column grid on phones
    smallest = mobile.evaluate("() => Math.min(...[...document.querySelectorAll('button')].filter(b => b.offsetParent).map(b => b.getBoundingClientRect().height))")
    assert smallest >= 32                                                     # tap targets are not tiny
