"""Browser smoke test (criteria 16 & 17): clicks through the store and every dashboard section on a
phone-sized and a desktop-sized screen, failing on JavaScript errors, failed sections or sideways scrolling.

Run against a running app:   python tests/ui_smoke.py http://127.0.0.1:8000 owner@unit.local <owner-password>
Requires:  pip install playwright && playwright install chromium
"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE, OWNER, PW = sys.argv[1], sys.argv[2], sys.argv[3]
SHOTS = sys.argv[4] if len(sys.argv) > 4 else None
problems = []


async def check_page(pg, label):
    await pg.wait_for_timeout(1300)
    over = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if over > 2:
        problems.append(f"{label}: page scrolls sideways by {over}px")
    failed = await pg.locator(".empty h3", has_text="Couldn't load").count()
    if failed:
        problems.append(f"{label}: section failed to load")
    if SHOTS:
        await pg.screenshot(path=f"{SHOTS}/{label.replace('/', '_').replace('#', '').replace(' ', '_')}.png")


async def run(width, height, tag, p):
    b = await p.chromium.launch()
    ctx = await b.new_context(viewport={"width": width, "height": height})
    pg = await ctx.new_page()
    pg.on("pageerror", lambda e: problems.append(f"[{tag}] JS error: {e}"))
    # ---- store (guest)
    for path in ["#/", "#/categories", "#/c/clothing", "#/search?q=shoes", "#/search?offers=1&sort=discount", "#/policy/returns"]:
        await pg.goto(BASE + "/" + path)
        await check_page(pg, f"{tag} store {path}")
    await pg.goto(BASE + "/#/")
    await pg.wait_for_timeout(800)
    await pg.click("#menu-btn")
    await pg.wait_for_timeout(500)
    for btn in await pg.locator("#drawer-tabs button").all():
        await btn.click()
        await pg.wait_for_timeout(200)
    await pg.keyboard.press("Escape")
    # department tabs
    for i in range(await pg.locator("#dept-tabs a").count()):
        await pg.locator("#dept-tabs a").nth(i).click()
        await check_page(pg, f"{tag} store tab {i}")
    # sort + filter on listing
    await pg.goto(BASE + "/#/c/headphones-audio")
    await pg.wait_for_timeout(900)
    await pg.select_option("#sort", "price_asc")
    await check_page(pg, f"{tag} store sorted")
    # ---- customer journey
    await pg.goto(BASE + "/#/login")
    await pg.wait_for_timeout(500)
    await pg.fill("[name=email]", "customer@demo.local")
    await pg.fill("[name=password]", "Demo@1234")
    await pg.click("#auth-f button")
    await pg.wait_for_timeout(1200)
    first = pg.locator("[data-add]:not([disabled])").first
    await pg.goto(BASE + "/#/")
    await pg.wait_for_timeout(1200)
    await first.click()
    await pg.wait_for_timeout(600)
    for path in ["#/cart", "#/checkout", "#/orders", "#/wishlist", "#/account", "#/notifications"]:
        await pg.goto(BASE + "/" + path)
        await check_page(pg, f"{tag} customer {path}")
    nav = pg.locator(".bottom-nav a")
    if await nav.first.is_visible():
        for i in range(await nav.count()):
            await nav.nth(i).click()
            await check_page(pg, f"{tag} bottom-nav {i}")
    await pg.goto(BASE + "/#/orders")
    await pg.wait_for_timeout(900)
    if await pg.locator(".ocard").count():
        await pg.locator(".ocard").first.click()
        await check_page(pg, f"{tag} order detail")
    await ctx.close()
    # ---- admin
    ctx = await b.new_context(viewport={"width": width, "height": height})
    pg = await ctx.new_page()
    pg.on("pageerror", lambda e: problems.append(f"[{tag}] admin JS error: {e}"))
    await pg.goto(BASE + "/admin")
    await pg.wait_for_timeout(800)
    await pg.fill("[name=email]", OWNER)
    await pg.fill("[name=password]", PW)
    await pg.click("#lf button")
    await pg.wait_for_timeout(2000)
    links = await pg.locator(".side a[data-nav]").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    for href in links:
        await pg.goto(BASE + "/admin" + href)
        await check_page(pg, f"{tag} admin {href}")
        # click every segmented / tab button on the page
        for sel in [".seg button", ".group-tabs button"]:
            n = await pg.locator(f"#content {sel}").count()
            for i in range(n):
                btn = pg.locator(f"#content {sel}").nth(i)
                if await btn.is_visible() and (await btn.text_content()).strip() != "Custom":
                    await btn.click()
                    await pg.wait_for_timeout(500)
        failed = await pg.locator(".empty h3", has_text="Couldn't load").count()
        if failed:
            problems.append(f"{tag} admin {href}: failed after clicking filters")
    # detail pages
    for href in ["#/orders", "#/customers", "#/products"]:
        await pg.goto(BASE + "/admin" + href)
        await pg.wait_for_timeout(1200)
        row = pg.locator("tr.click, td a.pname").first
        if await row.count():
            await row.click()
            await check_page(pg, f"{tag} admin detail {href}")
    await ctx.close()
    await b.close()


async def main():
    async with async_playwright() as p:
        await run(390, 844, "mobile", p)
        await run(1366, 900, "desktop", p)
    if problems:
        print("PROBLEMS:")
        for x in problems:
            print(" -", x)
        sys.exit(1)
    print("UI smoke test passed: store and dashboard work on mobile (390px) and desktop (1366px).")


asyncio.run(main())
