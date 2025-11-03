from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse
import asyncio
from playwright.async_api import async_playwright
import os
import traceback
import sys

app = FastAPI()

# === Credentials / Config ===
COURTDRIVE_USERNAME = os.getenv("COURTDRIVE_USERNAME", "chad@cvhlawgroup.com")
COURTDRIVE_PASSWORD = os.getenv("COURTDRIVE_PASSWORD", "Ch@d2201")
HEADLESS = True
BASE_URL = "https://v2.courtdrive.com/cases/pacer/flsbke/1:25-bk-"

# === Health check route (for Render / Zapier tests) ===
@app.get("/")
async def root():
    return {"status": "✅ Alive", "message": "CourtDrive capture service running"}


# === Main capture endpoint ===
@app.post("/capture")
async def capture(case_number: str = Form(...)):
    filename = f"Voluntary_Petition_{case_number}.pdf"

    try:
        async with async_playwright() as p:
            # ✅ Launch Chromium safely in Render
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            # 1️⃣ Login
            await page.goto("https://v2.courtdrive.com/login")
            await page.fill('input[name="email"]', COURTDRIVE_USERNAME)
            await page.fill('input[name="password"]', COURTDRIVE_PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")

            # 2️⃣ Go to case
            case_url = f"{BASE_URL}{case_number}/dockets"
            await page.goto(case_url)
            await page.wait_for_load_state("networkidle")

            # 3️⃣ Search for Voluntary Petition
            await page.wait_for_selector("input[placeholder*='Search']")
            await page.fill("input[placeholder*='Search']", "Voluntary Petition")
            await page.keyboard.press("Enter")
            await page.wait_for_selector("text=Voluntary Petition", state="visible")

            # 4️⃣ Tab through the interface (21 + 3) to reach and download the PDF
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

        # ✅ Return the PDF file to Zapier
        return FileResponse(
            filename,
            media_type="application/pdf",
            filename=filename
        )

    except Exception as e:
        # Log the full traceback in Render logs for debugging
        traceback.print_exc(file=sys.stdout)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
















