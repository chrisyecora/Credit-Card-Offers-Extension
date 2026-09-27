## Fresh offer workflow

The API shows an offer for 14 days after it was last captured by a published
scrape. It hides all offers from a bank if that bank has not had a published
complete scrape in 14 days. A later scrape that omits an offer leaves its old
`last_seen_at` intact until that offer ages out. Unpublished and failed runs
never affect API results. Scrape each bank at least twice a week.

Apply migrations `0006_create_offer_observations.sql` through
`0008_index_published_scrape_freshness.sql` before loading new captures. Existing rows in
the legacy `offers` table are kept for rollback but
are not served by the new API. For production, publish a fresh capture for each
bank **before** deploying the API query change:

1. From the repository root, run `pipenv run python scrape_capital_one.py`,
   `pipenv run python scrape_amex.py`, and `pipenv run python scrape_chase.py`
   in their authenticated browsers. Each writes an offer array and a matching
   `.meta.json` file with its capture time, row count, SHA-256 digest, and any
   scraper warnings.
2. Review each scraper's captured and skipped counts, warnings, and the JSON
   output. A partial scrape must not be confirmed; rerun it instead. Empty
   captures are rejected.
   If Capital One encounters a bad feed response after collecting offers, it
   writes `offers_partial.json` for inspection without capture metadata and
   leaves the previous `offers.json` untouched. The partial file cannot be
   loaded into D1.
3. Dry-run each file, then publish it only after confirming it is complete:

   ```sh
   python offers-api/scripts/load_offers.py --input offers.json
   python offers-api/scripts/load_offers.py --input offers.json --apply --confirm-complete
   python offers-api/scripts/load_offers.py --input offers_amex.json
   python offers-api/scripts/load_offers.py --input offers_amex.json --apply --confirm-complete
   python offers-api/scripts/load_offers.py --input offers_chase.json
   python offers-api/scripts/load_offers.py --input offers_chase.json --apply --confirm-complete
   ```

The loader rejects files older than 24 hours, metadata mismatches, mixed banks,
duplicate identities, and empty captures. It stages rows under an unpublished
run and publishes the run after every batch uploads. Rerunning the same capture
is safe; if an upload failed, rerun the command to finish that run. Published
imports remove at most one expired run for that bank after 30 days, spreading
cleanup writes across scrape days. Use `--local`
alongside `--apply --confirm-complete` to load local D1 for testing.

Capital One's encoded `raw_id` includes a page context that changes between
scrapes. The loader keys those offers by the encoded inventory source and
merchant domain, while retaining the original `raw_id` in each observation.
An unrecognized Capital One ID fails validation instead of creating a new
identity for every scrape.

Apply production migrations intentionally from `offers-api/` with
`npm exec wrangler -- d1 migrations apply offers-db --remote`. Then publish all
three banks before deploying the new Worker with `npm run deploy`. For local
verification, apply migrations with `--local` and start the Worker with
`npm run dev --local`.

For Amex, `pipenv run python scrape_amex.py` opens or reuses a normal Chrome
window with a separate persistent profile under `user_data/amex-cdp`. Sign in
there, then press Enter in the terminal. The scraper opens Amex Offers in that
Chrome window and captures the Offers Hub response. Chrome chooses a
local debugging port automatically; the window stays open after the capture.
Close it when finished. If Chrome is installed elsewhere, set `CHROME_BINARY`
to its executable path. The advanced `--cdp-url` option remains available for
attaching to a Chrome window started separately.

If Amex login still fails in normal Chrome, sign in using your usual browser,
open DevTools Network, click Search with an empty query, and save the **Response**
body from `ReadOffersHubPresentation.web.v1` as `auth/amex-response.json`.
Then run `pipenv run python scrape_amex.py --input-payload auth/amex-response.json`
to inspect its parsed offers. This saved-response path does not create publishable
capture metadata; use a fresh browser scrape before loading D1. The `auth/`
directory is ignored by Git; do not commit or share the raw response.

The scraper captures only merchant offers with explicitly qualifying
website domains, reports skipped offers, and warns when a response reaches 100
entries. It never enrolls an offer. The Capital One scraper is now
`scrape_capital_one.py` and continues to write `offers.json`.

The Chase scraper checks whether its first response or a prefetched response
already contains both card accounts. If a card is still missing, it asks you
to switch cards in Chrome and press Enter. It verifies that the displayed card
changed and that a new account offers response arrived. If either check fails,
the scrape stops without replacing `offers_chase.json` or creating publishable
metadata.

New bank feeds should
provide `bank_slug` (lowercase letters, digits, and underscores) and `bank` (the
display name) on every offer. Raw offer IDs only need to be unique within their
bank and domain. `/v1/offers?domain=example.com` returns offers from every loaded bank,
including both `bank` and `bank_slug` in each result.

Apply migration `0005_add_bank_offers_urls.sql` before deploying the bank catalog
endpoint. It adds `offers_url` to `banks` and fills the existing Capital One,
American Express, and Chase destinations. New bank feeds should also set an
HTTPS `offers_url` in the `banks` table; offer loading updates bank names but
preserves this URL.

`GET /v1/banks` returns a list of `{ "slug", "name", "offers_url" }` objects,
sorted by name. `GET /v1/offers?domain=example.com&banks=capital_one,american_express`
returns only those banks. Omit `banks` for all banks. An empty or malformed
`banks` parameter returns HTTP 400; an unknown but well-formed slug simply has
no matching offers.

You can run the Worker defined by your new project by executing `wrangler dev` in this
directory. This will start up an HTTP server and will allow you to iterate on your
Worker without having to restart `wrangler`.

### Types and autocomplete

This project also includes a pyproject.toml with some requirements which
set up autocomplete and type hints for this Python Workers project.

To get these installed you'll need `uv`, which you can install by following
https://docs.astral.sh/uv/getting-started/installation/.

Once `uv` is installed, you can run the following:

```
uv venv
uv sync
```

Then point your editor's Python plugin at the `.venv` directory. You should then have working
autocomplete and type information in your editor.
