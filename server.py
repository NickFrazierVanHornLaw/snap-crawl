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
        # Ensure browsers are present (belt & suspenders)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
        subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)

        async with async_playwright() as p:
            async def launch():
                return await p.chromium.launch(headless=HEADLESS, args=BROWSER_ARGS)

            try:
                browser = await launch()
            except Exception:
                subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
                browser = await launch()

            context = await browser.new_context(
                accept_downloads=True,
                viewport={"width": 1400, "height": 1800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            )
            page = await context.new_page()

            # ---- Login ----
            await page.goto("https://v2.courtdrive.com/login")
            await page.fill('input[name="email"]', COURTDRIVE_USERNAME)
            await page.fill('input[name="password"]', COURTDRIVE_PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(0.8)

            # ---- Case page ----
            case_url = f"{BASE_URL}{case_number}/dockets"
            await page.goto(case_url)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1.0)

            # ---- Find search input OR detect blockers ----
            sel = await wait_for_any_selector(page, SEARCH_SELECTORS, timeout=30000)
            if not sel:
                text = (await page.content())[:100000]
                if any(t.lower() in text.lower() for t in BLOCKER_TEXT):
                    html_path, png_path = await dump_debug(page, tag="blocker")
                    await browser.close()
                    return JSONResponse(
                        status_code=502,
                        content={
                            "error": "Search input not visible; page likely blocked (login/MFA/cookies/upgrade).",
                            "debug_html": html_path,
                            "debug_png": png_path,
                        },
                    )
                html_path, png_path = await dump_debug(page, tag="nosel")
                await browser.close()
                return JSONResponse(
                    status_code=502,
                    content={
                        "error": "Search input selector not found on case dockets page.",
                        "debug_html": html_path,
                        "debug_png": png_path,
                    },
                )

            # ---- Use the found selector ----
            search = page.locator(sel).first
            await search.click()
            await search.fill("")
            await search.type("Voluntary Petition", delay=60)
            await page.keyboard.press("Enter")

            await page.wait_for_selector("text=Voluntary Petition", state="visible", timeout=30000)
            await asyncio.sleep(1.0)

            # ---- Your tabbing flow ----
            for _ in range(21):
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.1)
            await page.keyboard.press("Enter")
            for _ in range(3):
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.1)

            async with page.expect_download() as dl_info:
                await page.keyboard.press("Enter")
            download = await dl_info.value
            await download.save_as(filename)

            await browser.close()

        return FileResponse(filename, media_type="application/pdf", filename=filename)

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/debug/last-html", response_class=PlainTextResponse)
async def debug_last_html():
    path = "/opt/render/project/src/debug_nosel.html"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "No debug file found."

























