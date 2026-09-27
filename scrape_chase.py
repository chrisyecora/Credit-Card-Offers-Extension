"""Capture both cards' Chase offers through a locally authenticated browser."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from chase_offers import AccountOffers, offers_from_payload


USER_DATA_DIR = Path("user_data/chase")
OUTPUT_FILE = Path("offers_chase.json")
OFFERS_URL = "https://secure.chase.com/web/auth/dashboard#/dashboard/merchantOffers/offer-hub"
RESPONSE_PATH = "/digital-customer-targeted-offers/v3/customer-offers"
CARD_SELECTOR = '[data-testid="select-credit-card-account"]'


def save_offers(captures: list[tuple[str, list[AccountOffers]]]) -> None:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    conflicts: set[tuple[str, str]] = set()
    for label, accounts in captures:
        for account in accounts:
            print(
                f"{label}: captured {account.captured} usable offers in {account.returned_count} entries; "
                f"matched {len({item['raw_id'] for item in account.records})} offers "
                f"across {len(account.records)} domains; skipped {len(account.skipped)}."
            )
            if account.available_count is not None and account.returned_count < account.available_count:
                print(
                    f"  Warning: response reports {account.available_count} available offers "
                    f"but returned only {account.returned_count} entries. Review completeness."
                )
            for offer_id, reason in account.skipped:
                print(f"  {offer_id}: {reason}")
            for record in account.records:
                key = (record["raw_id"], record["domain"])
                if key in conflicts:
                    continue
                previous = merged.get(key)
                if previous is not None and previous != record:
                    merged.pop(key)
                    conflicts.add(key)
                else:
                    merged[key] = record
    for offer_id, domain in sorted(conflicts):
        print(f"  Conflict across cards for {offer_id} at {domain}; omitted pending review.")
    if not merged:
        raise RuntimeError("No domain-matchable Chase offers were captured; existing output was not replaced")
    records = sorted(merged.values(), key=lambda item: (item["merchant_name"].lower(), item["domain"], item["raw_id"]))
    temporary = OUTPUT_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT_FILE)
    print(f"Saved {len(records)} Chase domain matches to {OUTPUT_FILE}.")


def import_payload(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    save_offers([("Saved response", offers_from_payload(payload))])


async def main(cdp_url: str | None = None) -> None:
    async with async_playwright() as playwright:
        if cdp_url:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("The attached Chrome browser has no default context")
            context = browser.contexts[0]
            page = next((tab for tab in context.pages if "secure.chase.com" in tab.url), None)
            if page is None:
                page = await context.new_page()
        else:
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR), channel="chrome", headless=False
            )
            page = context.pages[0] if context.pages else await context.new_page()
        try:
            responses: asyncio.Queue[dict] = asyncio.Queue()

            async def handle_response(response) -> None:
                if RESPONSE_PATH not in response.url or response.status != 200:
                    return
                try:
                    payload = await response.json()
                    offers_from_payload(payload)
                except (ValueError, TypeError) as error:
                    print(f"Unable to parse Chase offers response: {error}")
                    return
                await responses.put(payload)

            context.on("response", handle_response)

            async def next_payload(timeout: int = 30, seen_accounts: set[str] | None = None) -> dict:
                while True:
                    payload = await asyncio.wait_for(responses.get(), timeout=timeout)
                    identifiers = {
                        str(account.get("digitalAccountIdentifier"))
                        for account in payload["customerOffers"]
                        if isinstance(account, dict) and account.get("digitalAccountIdentifier")
                    }
                    if not seen_accounts or not identifiers.issubset(seen_accounts):
                        return payload

            print("Opening Chase Offers. Log in manually if prompted.")
            await page.goto(OFFERS_URL, wait_until="domcontentloaded")
            try:
                first_payload = await next_payload(timeout=20)
            except TimeoutError:
                input("After signing in and opening Chase Offers, press ENTER here...")
                await page.goto(OFFERS_URL, wait_until="domcontentloaded")
                first_payload = await next_payload()

            selector = page.locator(CARD_SELECTOR)
            await selector.wait_for(state="visible", timeout=15000)
            selected = (await selector.locator('[data-mds-select-value-text="true"]').inner_text()).strip()
            captures = [(selected, offers_from_payload(first_payload))]
            seen_accounts = {
                str(account.get("digitalAccountIdentifier"))
                for account in first_payload["customerOffers"]
                if isinstance(account, dict) and account.get("digitalAccountIdentifier")
            }

            await selector.click()
            options = page.get_by_role("listbox").get_by_role("option")
            option_labels = [label.strip() for label in await options.all_text_contents()]
            await page.keyboard.press("Escape")
            if len(option_labels) < 2:
                raise RuntimeError("The Chase card menu did not expose both cards; existing output was not replaced")
            for index, label in enumerate(option_labels):
                if selected in label or label in selected:
                    continue
                while not responses.empty():
                    responses.get_nowait()
                await selector.click()
                await page.get_by_role("listbox").get_by_role("option").nth(index).click()
                try:
                    payload = await next_payload(seen_accounts=seen_accounts)
                except TimeoutError as error:
                    raise RuntimeError(f"No new offers response arrived after selecting {label}") from error
                captures.append((label, offers_from_payload(payload)))
                seen_accounts.update(
                    str(account.get("digitalAccountIdentifier"))
                    for account in payload["customerOffers"]
                    if isinstance(account, dict) and account.get("digitalAccountIdentifier")
                )
            save_offers(captures)
        finally:
            if not cdp_url:
                await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-payload", type=Path, help="parse a saved complete Chase offers response")
    parser.add_argument("--cdp-url", help="attach to a signed-in Chrome debugging endpoint")
    args = parser.parse_args()
    if args.input_payload and args.cdp_url:
        parser.error("--input-payload and --cdp-url cannot be used together")
    if args.input_payload:
        try:
            import_payload(args.input_payload)
        except (OSError, ValueError) as error:
            print(f"Unable to import Chase response: {error}", file=sys.stderr)
            raise SystemExit(1) from None
    else:
        asyncio.run(main(args.cdp_url))
