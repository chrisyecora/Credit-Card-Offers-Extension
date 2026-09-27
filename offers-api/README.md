## Usage

### Multi-bank data

Migration `0002_create_banks.sql` drops the old `offers` table and creates
`banks` plus bank-scoped offers. Applying it deletes existing offers. After
configuring Cloudflare credentials, run from `offers-api/`:

```
npm exec wrangler -- d1 migrations apply offers-db --remote
python3 scripts/load_offers.py --apply
```

The loader accepts the existing Capital One `offers.json`. To collect and load
American Express offers, run these commands from the repository root after
logging in through the scraper's browser:

```
pipenv run python scrape_amex.py
python offers-api/scripts/load_offers.py --input offers_amex.json
python offers-api/scripts/load_offers.py --input offers_amex.json --apply
```

If AmEx login fails in the scraper browser, sign in using your usual browser,
open DevTools Network, click Search with an empty query, and save the **Response**
body from `ReadOffersHubPresentation.web.v1` as `auth/amex-response.json`.
Then run `pipenv run python scrape_amex.py --input-payload auth/amex-response.json`.
The `auth/` directory is ignored by Git; do not commit or share the raw response.

Review the generated file and dry-run counts before `--apply`. Apply migration
`0004_allow_offer_multiple_domains.sql` to the target D1 database before loading
AmEx records. The scraper captures only merchant offers with explicitly qualifying
website domains, reports skipped offers, and warns when a response reaches 100
entries. It never enrolls an offer. The Capital One scraper is now
`scrape_capital_one.py` and continues to write `offers.json`.

If login fails in a Playwright-launched window, launch regular Chrome with a
separate local profile and a loopback-only debugging port. Log in manually in
that window, open AmEx Offers, then run the scraper in attach mode:

```
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$PWD/user_data/amex-cdp"
pipenv run python scrape_amex.py --cdp-url http://127.0.0.1:9222
```

Run these commands from the repository root. The scraper attaches to the open
offers tab, clicks Search with an empty query, captures the network response,
and writes normalized JSON. Close the debug-enabled Chrome window afterward.

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
