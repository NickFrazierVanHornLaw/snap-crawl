from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse
import asyncio
from playwright.async_api import async_playwright
import subprocess
import os
import traceback

app = FastAPI()

COURTDRIVE_USERNAME = os.getenv("COURTDRIVE_USERNAME", "chad@cvhlawgroup.com")
COURTDRIVE_PASSWORD = os.getenv("COURTDRIVE_PASSWORD", "Ch@d2201")
HEADLESS = True
BASE_URL = "https://v2.courtdrive.com/cases/pacer/flsbke/1:25-bk-"

BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

@app.get("/")
async def root():
    return {"status": "✅ Alive", "message": "CourtDrive capture service running"}

@app.on_event("startup")
def ensure_chromium_installed():
    """
    Idempotent: ensures Chromium for this Playwright version is available
    in PLAYWRIGHT_BROWSERS_PATH at runtime.
    """
    try:
        # Respect env path; default to Render cache
        browsers_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

        # This is quick if already cached
        subprocess.run(
            ["python", "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print(f"✅ Playwright Chromium ready in {browsers_path}")
    except Exception as e:
        print("⚠️ Failed to preinstall Chromium at startup:", e)

@app.post("/capture")
async def capture(case_number: str = Form(...)):
    filename = f"Voluntary_Petition_{case_number}.pdf"

    try:
        async with async_playwright() as p:
            # Try launching — if it fails, re-install once and retry
            async def launch_browser():
                return await p.chromium.launch(headless=HEADLESS, args=BROWSER_ARGS)

            try:
                browser = await launch_browser()
            except Exception:
                # One-time fallback install (helps when cache was purged)
                subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
                browser = await launch_browser()

            context = await browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 1800})
            page = await context.new_page()

            # Login
            await page.goto("https://v2.courtdrive.com/login")
            await page.fill('input[name="email"]', COURTDRIVE_USERNAME)
            await page.fill('input[name="password"]', COURTDRIVE_PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")

            # Case dockets
            case_url = f"{BASE_URL}{case_number}/dockets"
            await page.goto(case_url)
            await page.wait_for_load_state("networkidle")

            # Search “Voluntary Petition”
            await page.wait_for_selector("input[placeholder*='Search']")
            await page.fill("input[placeholder*='Search']", "Voluntary Petition")
            await page.keyboard.press("Enter")
            await page.wait_for_selector("text=Voluntary Petition", state="visible")
            await asyncio.sleep(1.0)

            # Tabbing sequence that worked for you earlier
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

# Optional: quick health probe that actually launches the browser
@app.get("/debug/launch")
async def debug_launch():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            await browser.close()
        return {"ok": True, "msg": "Chromium launch succeeded"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})




















