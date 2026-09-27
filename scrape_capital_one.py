import os
import asyncio
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

from capture_artifact import write_capture, write_unverified_capture

USER_DATA_DIR = "./user_data/capitalone"
OUTPUT_FILE = Path("offers.json")
PARTIAL_OUTPUT_FILE = Path("offers_partial.json")
IGNORED_FEED_RESOURCES = {
    "merchant-categories.data",
    "activated-offers.data",
    "headline-offers.data",
}

def sanitize_domain(domain: str) -> str:
    """Cleans domain strings for exact matching (e.g., 'www.nike.com/foo' -> 'nike.com')."""
    if not domain:
        return ""
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/")[0]


def offer_feed_items(payload: object) -> list[dict] | None:
    """Other /feed/ endpoints return lists and unrelated resource objects."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("data")
    if not isinstance(items, list) or not items:
        return None
    if not any(isinstance(item, dict) and "merchantTLD" in item for item in items):
        return None
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("offer feed contains a non-object item")
    return items


def preserve_partial(all_offers: dict) -> str:
    if not all_offers:
        return ""
    write_unverified_capture(PARTIAL_OUTPUT_FILE, list(all_offers.values()))
    return f" {len(all_offers)} offers saved to {PARTIAL_OUTPUT_FILE} for review."


def finish_capture(all_offers: dict, captured_batches: int, response_errors: list[str]) -> None:
    offers_list = list(all_offers.values())
    if response_errors:
        details = "; ".join(response_errors[:3])
        extra = f"; {len(response_errors) - 3} more" if len(response_errors) > 3 else ""
        partial = preserve_partial(all_offers)
        raise RuntimeError(
            f"Capture had {len(response_errors)} feed error(s): {details}{extra}.{partial} "
            f"{OUTPUT_FILE} was not replaced."
        )
    if captured_batches == 0 or not offers_list:
        raise RuntimeError(f"No usable offer feed was captured; {OUTPUT_FILE} was not replaced")
    write_capture(OUTPUT_FILE, offers_list, "capital_one")
    PARTIAL_OUTPUT_FILE.unlink(missing_ok=True)


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
        response_errors = []
        captured_batches = 0

        # 1. Network interceptor
        async def handle_response(response):
            nonlocal captured_batches
            url = urlsplit(response.url)
            if url.hostname and (
                url.hostname == "capitaloneoffers.com" or
                url.hostname.endswith(".capitaloneoffers.com")
            ) and url.path.startswith("/feed/"):
                resource = url.path.rsplit("/", maxsplit=1)[-1]
                if resource in IGNORED_FEED_RESOURCES:
                    return
                if response.status != 200:
                    response_errors.append(f"HTTP {response.status} at {resource}")
                    return
                try:
                    payload = await response.json()
                    items = offer_feed_items(payload)
                    if items is None:
                        return
                    print(f"[Captured] {len(items)} items from feed batch.")
                    batch = {}
                    for item in items:
                        raw_domain = item.get("merchantTLD", "")
                        domain = sanitize_domain(raw_domain)
                        offer_id = item.get("id") or domain

                        if domain and offer_id and offer_id not in all_offers and offer_id not in batch:
                            batch[offer_id] = {
                                "domain": domain,
                                "merchant_name": item.get("merchantDisplayName"),
                                "reward_rate": item.get("buttonText"),
                                "channel": item.get("text"),
                                "bank": "Capital One",
                                "bank_slug": "capital_one",
                                "raw_id": item.get("id"),
                                "logo_url": item.get("imageSrc")
                            }
                    all_offers.update(batch)
                    captured_batches += 1
                except Exception as e:
                    error = f"{resource}: {type(e).__name__}: {e}"
                    print(f"Error parsing feed response: {error}")
                    response_errors.append(error)

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

        except TimeoutError as error:
            raise RuntimeError("Timed out opening the complete offers page") from error
        except Exception as e:
            raise RuntimeError("Could not open the complete offers page") from e

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
            except Exception as error:
                partial = preserve_partial(all_offers)
                raise RuntimeError(f"Offer pagination stopped unexpectedly.{partial}") from error

        if await view_more_btn.is_visible():
            partial = preserve_partial(all_offers)
            raise RuntimeError(f"Offer pagination reached the 50-page safety limit.{partial}")
        print(f"\nCaptured {len(all_offers)} total unique offers!")

        # 5. A partial file can be reviewed, but cannot be loaded into D1.
        finish_capture(all_offers, captured_batches, response_errors)

        print(f"Successfully saved data to '{OUTPUT_FILE}'.")
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
