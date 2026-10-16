from playwright.sync_api import Page, expect

ENTER = "Enter the World of Gifts ✨"


def open_login(page: Page) -> None:
    page.goto(page.base)
    expect(page.locator(".gw-login-title")).to_be_visible()


def login(page: Page, role: str, secret: str, name: str | None = None) -> None:
    open_login(page)
    if role != "Gift Giver":
        page.get_by_label("I am the…").click()
        page.get_by_role("option", name=role).click()
    label = "Family PIN" if role == "Gift Giver" else "Your secret password"
    page.get_by_label(label, exact=True).fill(secret)
    page.get_by_role("button", name=ENTER).click()
    if role == "Gift Giver":
        expect(page.locator(".st-key-pick_card")).to_be_visible()
        if name:
            page.locator(f".st-key-pick_{name} button").click()
            expect(page.locator(".gw-hero-title")).to_be_visible()
    else:
        expect(page.locator(".gw-hero-title")).to_be_visible()


def goto_wishlist(page: Page) -> None:
    page.locator(".st-key-hero_cta button").click()
    expect(page.locator(".st-key-grid")).to_be_visible()


def cards(page: Page):
    return page.locator('[class*="st-key-card_"]')


def no_horizontal_overflow(page: Page) -> bool:
    return not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
