"""Capture both cards' Chase offers through a locally authenticated browser."""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

from chase_offers import AccountOffers, offers_from_payload
from capture_artifact import write_capture, write_unverified_capture


USER_DATA_DIR = Path("user_data/chase")
OUTPUT_FILE = Path("offers_chase.json")
OFFERS_URL = "https://secure.chase.com/web/auth/dashboard#/dashboard/merchantOffers/offer-hub"
RESPONSE_PATH = "/digital-customer-targeted-offers/v3/customer-offers"
CARD_SELECTOR = '[data-testid="select-credit-card-account"]'
EXPECTED_CARD_COUNT = 2


def account_ids(payload: dict) -> set[str]:
    return {
        str(account["digitalAccountIdentifier"])
        for account in payload["customerOffers"]
        if isinstance(account, dict) and account.get("digitalAccountIdentifier")
    }


def new_account_payload(payload: dict, seen_accounts: set[str]) -> dict | None:
    accounts = [
        account for account in payload["customerOffers"]
        if isinstance(account, dict) and
        account.get("digitalAccountIdentifier") and
        str(account["digitalAccountIdentifier"]) not in seen_accounts
    ]
    return {"customerOffers": accounts} if accounts else None


def same_card(selected: str, label: str) -> bool:
    selected_digits = re.findall(r"(?<!\d)\d{4}(?!\d)", selected)
    label_digits = re.findall(r"(?<!\d)\d{4}(?!\d)", label)
    if selected_digits and label_digits:
        return selected_digits[-1] == label_digits[-1]
    return " ".join(selected.casefold().split()) == " ".join(label.casefold().split())


def save_offers(captures: list[tuple[str, list[AccountOffers]]], verified_source: bool = True) -> None:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    conflicts: set[tuple[str, str]] = set()
    warnings = []
    for label, accounts in captures:
        for account in accounts:
            print(
                f"{label}: captured {account.captured} usable offers in {account.returned_count} entries; "
                f"matched {len({item['raw_id'] for item in account.records})} offers "
                f"across {len(account.records)} domains; skipped {len(account.skipped)}."
            )
            if account.available_count is not None and account.returned_count < account.available_count:
                warning = (
                    f"{label}: response reports {account.available_count} available offers "
                    f"but returned only {account.returned_count} entries."
                )
                warnings.append(warning)
                print(
                    f"  Warning: {warning} Review completeness."
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
        warning = f"Conflict across cards for {offer_id} at {domain}; omitted pending review."
        warnings.append(warning)
        print(f"  {warning}")
    if not merged:
        raise RuntimeError("No domain-matchable Chase offers were captured; existing output was not replaced")
    records = sorted(merged.values(), key=lambda item: (item["merchant_name"].lower(), item["domain"], item["raw_id"]))
    if verified_source:
        write_capture(OUTPUT_FILE, records, "chase", warnings)
    else:
        write_unverified_capture(OUTPUT_FILE, records)
    print(f"Saved {len(records)} Chase domain matches to {OUTPUT_FILE}.")


def import_payload(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    save_offers([("Saved response", offers_from_payload(payload))], verified_source=False)


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
                deadline = time.monotonic() + timeout
                while True:
                    payload = await asyncio.wait_for(responses.get(), timeout=max(0, deadline - time.monotonic()))
                    if not seen_accounts or account_ids(payload) - seen_accounts:
                        return payload
                    print("Ignored a Chase offers response for an account already captured.")

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
            seen_accounts = account_ids(first_payload)
            print(f"Initial Chase response included {len(seen_accounts)} card account(s).")

            print(f"Expecting offers from {EXPECTED_CARD_COUNT} Chase cards.")
            while not responses.empty():
                prefetched = responses.get_nowait()
                added = new_account_payload(prefetched, seen_accounts)
                if added:
                    captures.append(("Prefetched card", offers_from_payload(added)))
                    seen_accounts.update(account_ids(added))
            if len(seen_accounts) >= EXPECTED_CARD_COUNT:
                print(f"Already captured {len(seen_accounts)} card accounts; no card switch needed.")
                save_offers(captures)
                return
            while len(seen_accounts) < EXPECTED_CARD_COUNT:
                print(f"Current Chase card: {selected}. Switch to another card in Chrome.")
                await asyncio.to_thread(input, "Press ENTER after the other card's offers appear...")
                switched_to = (await selector.locator('[data-mds-select-value-text="true"]').inner_text()).strip()
                if same_card(selected, switched_to):
                    raise RuntimeError(
                        "The displayed Chase card did not change; existing output was not replaced"
                    )
                print(f"Chase card changed to {switched_to}; checking its offers response.")
                try:
                    payload = await next_payload(timeout=10, seen_accounts=seen_accounts)
                except TimeoutError as error:
                    raise RuntimeError(
                        f"No new account offers response arrived after switching to {switched_to}; "
                        f"captured {len(seen_accounts)} of {EXPECTED_CARD_COUNT} cards, so existing output was not replaced"
                    ) from error
                added = new_account_payload(payload, seen_accounts)
                if added is None:
                    raise RuntimeError("Card response had no new account; existing output was not replaced")
                captures.append((switched_to, offers_from_payload(added)))
                seen_accounts.update(account_ids(added))
                selected = switched_to
            if len(seen_accounts) < EXPECTED_CARD_COUNT:
                raise RuntimeError(
                    f"Captured {len(seen_accounts)} of {EXPECTED_CARD_COUNT} Chase cards; "
                    "existing output was not replaced"
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
