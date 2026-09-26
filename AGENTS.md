# Repository Guidelines

## Project Structure & Module Organization

This repository has two current components:

- `main.py` is the local Playwright scraper. It captures Capital One offer-feed responses and writes normalized records to `offers.json`.
- `offers-api/` is the Cloudflare Python Worker API. Its entry point is `offers-api/src/entry.py`; small reusable helpers belong beside it in `offers-api/src/`.
- `offers-api/wrangler.jsonc` defines the Worker and its `offers_db` D1 binding. Python dependencies live in `offers-api/pyproject.toml`; Node tooling is defined in `offers-api/package.json`.

Keep runtime session material in `auth/` and `user_data/` local only. Neither is application source or an asset directory.

## Build, Test, and Development Commands

Run commands from the directory that owns the component.

- `python main.py` runs the authenticated local scraper and updates `offers.json`.
- `cd offers-api && uv sync` creates or synchronizes the Python Worker environment.
- `cd offers-api && npm run dev` starts the Worker locally through `pywrangler`.
- `cd offers-api && npm run deploy` deploys the Worker to Cloudflare.
- `cd offers-api && npm exec wrangler -- d1 migrations apply offers-db --local` applies future D1 migrations locally. Use `--remote` only when intentionally changing production data.

## Coding Style & Naming Conventions

Use Python 3.12+ with four-space indentation, `snake_case` functions and variables, and `PascalCase` classes. Prefer type hints for new public helpers and keep request handling in `entry.py` thin. Name migration files with sortable prefixes, for example `offers-api/migrations/0001_create_offers.sql`. Format JSON with two-space indentation.

## Testing Guidelines

No automated test runner is configured yet. For Worker changes, run `npm run dev` and verify the affected route with a local HTTP request before deployment. For scraper changes, validate that `offers.json` remains valid JSON and includes normalized domains. Add focused `pytest` tests for pure Python parsing or normalization logic as it is extracted; name them `test_<behavior>.py`.

## Commit & Pull Request Guidelines

The repository has no commit history yet, so establish concise imperative commits such as `Add health endpoint` or `Normalize merchant domains`. Keep each commit scoped to one change. Pull requests should describe behavior, list verification commands, link the relevant issue when one exists, and include request/response examples for API changes.

## Security & Configuration

Never commit Capital One session files, browser profiles, API tokens, or `.dev.vars` files. Store deployment credentials in Cloudflare or GitHub secrets. Treat `offers.json` as generated data; do not manually edit it unless creating a clearly labeled test fixture.
