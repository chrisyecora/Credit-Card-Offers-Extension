"""Capture available AmEx merchant offers through a locally authenticated browser."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import urlopen

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from amex_offers import offers_from_payload
from capture_artifact import write_capture, write_unverified_capture


CHROME_PROFILE_DIR = Path("user_data/amex-cdp")
CHROME_HOME_URL = "https://www.americanexpress.com/"
OUTPUT_FILE = Path("offers_amex.json")
OFFERS_URL = "https://global.americanexpress.com/offers/eligible"
RESPONSE_PATH = "ReadOffersHubPresentation.web.v1"


def chrome_executable() -> str:
    configured = os.environ.get("CHROME_BINARY")
    candidates = [configured] if configured else [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Google Chrome was not found; set CHROME_BINARY to its executable path")


def active_chrome_endpoint(port_file: Path) -> str | None:
    try:
        lines = port_file.read_text(encoding="utf-8").splitlines()
        port = int(lines[0])
        if not 1 <= port <= 65535:
            return None
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            details = json.load(response)
        if details.get("webSocketDebuggerUrl", "").endswith(lines[1]):
            return f"http://127.0.0.1:{port}"
    except (OSError, ValueError, IndexError, KeyError):
        pass
    return None


def open_manual_chrome() -> str:
    """Start or reuse a normal Chrome window with an isolated, persistent profile."""
    profile = CHROME_PROFILE_DIR.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    port_file = profile / "DevToolsActivePort"
    endpoint = active_chrome_endpoint(port_file)
    if endpoint:
        print("Using the existing Amex Chrome window.")
        return endpoint
    port_file.unlink(missing_ok=True)
    subprocess.Popen(
        [chrome_executable(), "--remote-debugging-address=127.0.0.1",
         "--remote-debugging-port=0", f"--user-data-dir={profile}", CHROME_HOME_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(50):
        endpoint = active_chrome_endpoint(port_file)
        if endpoint:
            return endpoint
        time.sleep(0.2)
    raise RuntimeError("Chrome did not open a local debugging port; close the Amex Chrome window and retry")


def save_offers(
    offers: dict[tuple[str, str], dict[str, str]],
    captured_merchant_ids: set[str],
    skipped: dict[str, str],
    page_counts: list[int],
    verified_source: bool = True,
) -> None:
    matched_ids = {offer_id for offer_id, _domain in offers}
    print(
        f"Captured {len(captured_merchant_ids)} merchant offers; matched "
        f"{len(matched_ids)} offers across {len(offers)} domains; skipped {len(skipped)}."
    )
    warnings = []
    if any(count == 100 for count in page_counts):
        warning = "A response contained exactly 100 offers; completeness beyond this page is unknown."
        warnings.append(warning)
        print(f"Warning: {warning}")
    for offer_id, reason in sorted(skipped.items()):
        print(f"  {offer_id}: {reason}")
    if not offers:
        raise RuntimeError("No domain-matchable merchant offers were captured; existing output was not replaced")
    sorted_offers = sorted(
        offers.values(),
        key=lambda offer: (offer["merchant_name"].lower(), offer["domain"], offer["raw_id"]),
    )
    if verified_source:
        write_capture(OUTPUT_FILE, sorted_offers, "american_express", warnings)
    else:
        write_unverified_capture(OUTPUT_FILE, sorted_offers)
    print(f"Saved {len(sorted_offers)} domain matches to {OUTPUT_FILE}.")


def import_payload(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records, _merchant_count, omitted = offers_from_payload(payload)
    page = payload["recommendedOffers"]["offersList"]["page1"]
    merchant_ids = {
        str(item.get("offerId") or item.get("title") or "unknown")
        for item in page
        if isinstance(item, dict) and item.get("offerType") == "MERCHANT"
    }
    offers = {(record["raw_id"], record["domain"]): record for record in records}
    save_offers(offers, merchant_ids, dict(omitted), [len(page)], verified_source=False)


async def main(cdp_url: str) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("The attached Chrome browser has no default context")
        context = browser.contexts[0]
        page = next((tab for tab in context.pages if "americanexpress.com/offers/" in tab.url), None)
        if page is None:
            page = next((tab for tab in context.pages if "americanexpress.com" in tab.url), None)
        if page is None:
            raise RuntimeError("Open an American Express tab in the Amex Chrome window and retry")
        try:
            captured = asyncio.Event()
            offers: dict[tuple[str, str], dict[str, str]] = {}
            skipped: dict[str, str] = {}
            captured_merchant_ids: set[str] = set()
            page_counts: list[int] = []

            async def handle_response(response) -> None:
                if RESPONSE_PATH not in response.url or response.status != 200:
                    return
                try:
                    payload = await response.json()
                    records, merchant_count, omitted = offers_from_payload(payload)
                    page_count = len(payload["recommendedOffers"]["offersList"]["page1"])
                except (ValueError, TypeError, KeyError) as error:
                    print(f"Unable to parse Offers Hub response: {error}")
                    return
                page_counts.append(page_count)
                for item in payload["recommendedOffers"]["offersList"]["page1"]:
                    if isinstance(item, dict) and item.get("offerType") == "MERCHANT":
                        captured_merchant_ids.add(str(item.get("offerId") or item.get("title") or "unknown"))
                for record in records:
                    offers[(record["raw_id"], record["domain"])] = record
                    skipped.pop(record["raw_id"], None)
                for offer_id, reason in omitted:
                    skipped[offer_id] = reason
                print(f"Captured response: {page_count} entries, {merchant_count} merchant offers, {len(records)} domain matches")
                if merchant_count:
                    captured.set()

            context.on("response", handle_response)
            print("Opening the signed-in Amex Offers page.")
            if "americanexpress.com/offers/" in page.url:
                await page.reload(wait_until="domcontentloaded")
            else:
                await page.goto(OFFERS_URL, wait_until="domcontentloaded")
            try:
                await asyncio.wait_for(captured.wait(), timeout=8)
            except TimeoutError:
                search_button = page.get_by_role("button", name="Search", exact=True).first
                try:
                    await search_button.wait_for(state="visible", timeout=8000)
                except PlaywrightTimeoutError:
                    raise RuntimeError("Search is not visible in attached Chrome; open the signed-in Amex Offers page and retry")
                print("Submitting the empty offers search to request the offer list...")
                await search_button.click()
                await asyncio.wait_for(captured.wait(), timeout=30000)

            save_offers(offers, captured_merchant_ids, skipped, page_counts)
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-payload", type=Path,
        help="read a locally saved Offers Hub response instead of opening a browser",
    )
    parser.add_argument(
        "--cdp-url", help="attach to an already-running Chrome debugging endpoint, such as http://127.0.0.1:9222",
    )
    args = parser.parse_args()
    if args.input_payload and args.cdp_url:
        parser.error("--input-payload and --cdp-url cannot be used together")
    if args.input_payload:
        import_payload(args.input_payload)
    else:
        endpoint = args.cdp_url or open_manual_chrome()
        if not args.cdp_url:
            input("Sign in in the Amex Chrome window, then press ENTER here...")
        asyncio.run(main(endpoint))
