from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
import asyncio, os, subprocess, traceback
from playwright.async_api import async_playwright

app = FastAPI()

COURTDRIVE_USERNAME = os.getenv("COURTDRIVE_USERNAME", "chad@cvhlawgroup.com")
COURTDRIVE_PASSWORD = os.getenv("COURTDRIVE_PASSWORD", "Ch@d2201")
HEADLESS = True
BASE_URL = "https://v2.courtdrive.com/cases/pacer/flsbke/1:25-bk-"
BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

SEARCH_SELECTORS = [
    "input[placeholder*='Search']",
    "input[placeholder*='search']",
    "input[aria-label*='Search']",
    "input[aria-label*='search']",
]

BLOCKER_TEXT = [
    "Sign in", "Log in", "Two-Factor", "MFA", "Access denied",
    "Upgrade", "Cookies", "Accept all", "verification code",
]

@app.get("/")
async def root():
    return {"ok": True, "msg": "snap-crawl alive", "endpoint": "/capture (POST form: case_number)"}

@app.get("/debug/launch")
async def debug_launch():
    try:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
        subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            await b.close()
        return {"ok": True, "msg": "Chromium launch OK"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.on_event("startup")
def ensure_chromium():
    try:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
        subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
        print("✅ Playwright Chromium ready")
    except Exception as e:
        print("⚠️ Startup Chromium install failed:", e)

async def wait_for_any_selector(page, selectors, timeout=30000):
    """Return the first selector that becomes visible, or None."""
    tasks = [asyncio.create_task(page.wait_for_selector(sel, state="visible", timeout=timeout))
             for sel in selectors]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    # Cancel the rest
    for p in pending:
        p.cancel()
    # Figure out which selector won
    for idx, t in enumerate(tasks):
        if t in done and not t.cancelled() and t.exception() is None:
            return selectors[idx]
    return None

async def dump_debug(page, tag="case"):
    html_path = f"/opt/render/project/src/debug_{tag}.html"
    png_path = f"/opt/render/project/src/debug_{tag}.png"
    try:
        content = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        await page.screenshot(path=png_path, full_page=True)
        return html_path, png_path
    except Exception:
        return None, None

@app.post("/capture")
async def capture(case_number: str = Form(...)):
    filename = f"Voluntary_Petition_{case_number}.pdf"

    try:
        # Make sure Chromium is present (belt & suspenders)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
        subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                accept_downloads=True,
                viewport={"width": 1400, "height": 1800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            )

            # 🚫 Block heavy assets to speed up navigation
            page = await context.new_page()
            await page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in {"image", "font", "media"} else route.continue_()
            ))

            # 1) Login
            await page.goto("https://v2.courtdrive.com/login")
            await page.fill('input[name="email"]', COURTDRIVE_USERNAME)
            await page.fill('input[name="password"]', COURTDRIVE_PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")

            # 2) Go to case dockets
            case_url = f"{BASE_URL}{case_number}/dockets"
            await page.goto(case_url)
            await page.wait_for_load_state("networkidle")

            # 3) Find the docket row that contains "Voluntary Petition"
            #    We try a few robust locators; fastest match wins.
            row = None
            try:
                # Try role-based row match
                row = page.get_by_role("row", name=lambda n: n and "voluntary petition" in n.lower()).first
                await row.wait_for(state="visible", timeout=8000)
            except Exception:
                row = None

            if row is None:
                # Fallback: broader text match
                # Find any element with the text, then climb to nearest row/container
                match = page.locator("text=Voluntary Petition").first
                await match.wait_for(state="visible", timeout=12000)
                # Try to get the closest row-like ancestor
                row = match.locator("xpath=ancestor-or-self::*[self::tr or contains(@role,'row')][1]")

            # Ensure row is visible and stable
            await row.scroll_into_view_if_needed()
            await row.wait_for(state="visible", timeout=5000)

            # 4) Inside that row, click the PDF link (or expand if needed)
            pdf_link = row.get_by_role("link", name=lambda n: n and "pdf" in n.lower())
            if not await pdf_link.count():
                # If the row needs expanding, try a chevron/toggle within the row
                toggle = row.locator("button[aria-label*='toggle'], .chevron, .expand-icon").first
                if await toggle.count():
                    await toggle.click()
                    await page.wait_for_load_state("networkidle")
                    pdf_link = row.get_by_role("link", name=lambda n: n and "pdf" in n.lower())

            # Wait for a PDF link to become visible
            await pdf_link.first.wait_for(state="visible", timeout=10000)

            # 5) Download the PDF
            async with page.expect_download() as dl_info:
                await pdf_link.first.click()
            download = await dl_info.value
            await download.save_as(filename)

            await browser.close()

        return FileResponse(filename, media_type="application/pdf", filename=filename)

    except Exception as e:
        traceback.print_exc()
        # quick HTML dump for debugging when it fails
        try:
            html = await page.content()
            with open("/opt/render/project/src/debug_last.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"error": str(e)})
        
@app.get("/debug/last-html", response_class=PlainTextResponse)
async def debug_last_html():
    path = "/opt/render/project/src/debug_nosel.html"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "No debug file found."


























