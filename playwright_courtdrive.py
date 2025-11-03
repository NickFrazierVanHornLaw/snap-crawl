import asyncio
from playwright.async_api import async_playwright
import sys

# === Config ===
COURTDRIVE_USERNAME = "chad@cvhlawgroup.com"
COURTDRIVE_PASSWORD = "Ch@d2201"
HEADLESS = True
PAUSE_MS = 0

BASE_URL = "https://v2.courtdrive.com/cases/pacer/flsbke/1:25-bk-"

async def run(case_number: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        # Large viewport to minimize layout jumps
        context = await browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 1800})
        page = await context.new_page()
        page.set_default_timeout(20000)

        # 1) Login
        await page.goto("https://v2.courtdrive.com/login")
        await page.fill('input[name="email"]', COURTDRIVE_USERNAME)
        await page.fill('input[name="password"]', COURTDRIVE_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        print("✅ Logged in")

        # 2) Go to case dockets
        case_url = f"{BASE_URL}{case_number}/dockets"
        await page.goto(case_url)
        await page.wait_for_load_state("networkidle")
        print(f"✅ Opened case {case_number}")

        # 3) Search for Voluntary Petition
        print("🔎 Searching…")
        await page.wait_for_selector("input[placeholder*='Search']")
        search = await page.query_selector("input[placeholder*='Search']")
        await search.click()
        await search.fill("")
        await search.type("Voluntary Petition", delay=60)
        await page.keyboard.press("Enter")

        # Wait until visible and stable
        await page.wait_for_selector("text=Voluntary Petition", state="visible")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1.0)
        print("✅ Results visible")

        # 4) Tab 21× then click (no expand logic)
        print("⌨️ Tabbing 21×, then clicking…")
        for _ in range(21):
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.15)

        # Click (Enter), fallback Space if needed
        try:
            await page.keyboard.press("Enter")
            print("✅ First click (Enter) sent")
        except Exception as e:
            print(f"ℹ️ Enter click failed ({e}); trying Space…")
            await page.keyboard.press("Space")

        await page.wait_for_timeout(600 + PAUSE_MS)

        # 5) Tab 3× then click to download (capture)
        print("⌨️ Tabbing 3× to the PDF, then clicking to download…")
        for _ in range(3):
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.15)

        try:
            async with page.expect_download() as dl_info:
                await page.keyboard.press("Enter")
            download = await dl_info.value
            out_name = f"Voluntary_Petition_{case_number}.pdf"
            await download.save_as(out_name)
            print(f"✅ Downloaded: {out_name}")
        except Exception as e:
            print(f"ℹ️ Enter didn’t trigger download ({e}); trying Space once…")
            async with page.expect_download() as dl_info2:
                await page.keyboard.press("Space")
            download2 = await dl_info2.value
            out_name = f"Voluntary_Petition_{case_number}.pdf"
            await download2.save_as(out_name)
            print(f"✅ Downloaded: {out_name}")

        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python playwright_courtdrive.py <CASE_NUMBER>")
    else:
        asyncio.run(run(sys.argv[1]))












