import os
import asyncio
import re
import json
from playwright.async_api import async_playwright

USER_DATA_DIR = "./user_data/capitalone"
OUTPUT_FILE = "offers.json"

def sanitize_domain(domain: str) -> str:
    """Cleans domain strings for exact matching (e.g., 'www.nike.com/foo' -> 'nike.com')."""
    if not domain:
        return ""
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/")[0]


async def main():
    async with async_playwright() as p:
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        all_offers = {}

        # 1. Network interceptor
        async def handle_response(response):
            if re.search(r"capitaloneoffers\.com/feed/", response.url) and response.status == 200:
                try:
                    payload = await response.json()
                    items = payload.get("data", [])
                    print(f"[Captured] {len(items)} items from feed batch.")
                    
                    for item in items:
                        raw_domain = item.get("merchantTLD", "")
                        domain = sanitize_domain(raw_domain)
                        offer_id = item.get("id") or domain
                        
                        if domain and offer_id and offer_id not in all_offers:
                            all_offers[offer_id] = {
                                "domain": domain,
                                "merchant_name": item.get("merchantDisplayName"),
                                "reward_rate": item.get("buttonText"),
                                "channel": item.get("text"),
                                "bank": "Capital One",
                                "raw_id": item.get("id"),
                                "logo_url": item.get("imageSrc")
                            }
                except Exception as e:
                    print(f"Error parsing payload: {e}")

        context.on("response", handle_response)

        # 2. Navigation & Authentication
        print("Navigating to Capital One...")
        await page.goto("https://capitalone.com/accountSummary", wait_until="networkidle")

        if "accountSummary" not in page.url and "dashboard" not in page.url:
            print("\n" + "="*60)
            print("NOT LOGGED IN!")
            print("1. Log in manually in the opened browser window.")
            print("2. Once on the main dashboard, return here and press ENTER.")
            print("="*60 + "\n")
            input("Press [ENTER] after completing login...")

        # 3. Route to Offers Hub
        print("Looking for 'View all offers' button on dashboard...")
        view_offers_btn = page.locator("button", has_text="View all offers").first

        try:
            await view_offers_btn.wait_for(state="visible", timeout=15000)
            await view_offers_btn.scroll_into_view_if_needed()
            
            async with context.expect_page(timeout=5000) as page_info:
                await view_offers_btn.click()
            
            page = await page_info.value
            print("Switched to Capital One Offers tab!")

        except TimeoutError:
            print("Timed out waiting for 'View all offers' button or new page load.")
        except Exception as e:
            print(f"Could not click 'View all offers': {e}")

        # 4. Expansion loop
        await page.wait_for_timeout(3000)
        view_more_btn = page.locator("button", has_text="View More Offers").first
        click_count = 0

        print("Starting pagination loop...")
        while click_count < 50:
            try:
                if await view_more_btn.is_visible():
                    await view_more_btn.scroll_into_view_if_needed()
                    await view_more_btn.click()
                    click_count += 1
                    print(f"Clicked 'View More Offers' (#{click_count})")
                    await page.wait_for_timeout(1500)
                else:
                    break
            except Exception as e:
                print(f"Pagination finished or stopped: {e}")
                break

        print(f"\nCaptured {len(all_offers)} total unique offers!")

        # 5. Save directly to local JSON file
        offers_list = list(all_offers.values())
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(offers_list, f, indent=2)

        print(f"Successfully saved data to '{OUTPUT_FILE}'.")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())