# Credit Card Offer Checker

**A browser extension and data pipeline for surfacing credit-card-linked merchant offers while shopping online.** The project collects offer data from Capital One, American Express, and Chase, publishes verified captures to a Cloudflare-backed API, and matches offers to the shopping site a user is visiting.

## Project Highlights

- Built a Chrome Manifest V3 extension that detects the current merchant domain and displays matching offers in a page notification or the extension popup.
- Added per-bank controls, offer details, and links to each bank's offers page so users can review or activate offers with their card issuer.
- Developed authenticated Playwright scrapers for Capital One, American Express, and Chase, with bank-specific parsing and normalized merchant domains.
- Implemented a capture publishing workflow that validates scrape metadata and offer identities, stages records, and publishes only complete captures.
- Created a Cloudflare Worker API backed by D1 for bank catalogs and domain-based offer lookups, including bank filtering and freshness rules that serve offers confirmed within 14 days.

## Architecture

```text
Capital One / American Express / Chase
                 │
        Playwright capture scripts
                 │
       validated capture publishing
                 ▼
       Cloudflare D1 ◄── Worker API
                           ▲
                           │
                  Chrome extension
                           │
               matching merchant site
```

The extension uses the public-suffix list to match a page to its registrable merchant domain. It can show a contextual notice when offers are found, and its popup provides an on-demand lookup and bank preferences. The API filters out stale observations and banks without a recent published capture, so old or incomplete scrape runs do not appear as current offers.

## Technology

Python · Playwright · JavaScript · Chrome Extension Manifest V3 · Cloudflare Workers · Cloudflare D1 · SQL

## Scope

This is a prototype for discovering issuer-provided merchant offers. It does not enroll users in offers or guarantee that an offer is available to a particular card or account; users complete any activation with their issuer.
