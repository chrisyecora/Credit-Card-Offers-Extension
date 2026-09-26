# Mobile Safari App Plan

## Goal

Package the existing offer-discovery extension for Safari on iPhone and iPad without creating a separate frontend or duplicating the extension logic.

The first Safari version should support:

1. Detecting the current shopping domain.
2. Querying the existing Worker API.
3. Showing available offers.
4. Redirecting users to the relevant bank's offers page.

## Before Safari Packaging

Continue improving the shared product first:

- Add additional banks to the D1 schema and scraper pipeline.
- Include a stable `bank` identifier for every offer.
- Add a bank-specific offers-page URL or fallback destination.
- Keep the API response shape consistent across banks.
- Update the extension UI to display multiple bank offers clearly.
- Document that the extension sends the current hostname to the API.

This work benefits both Chrome and Safari, so it should happen before creating the iOS wrapper.

## Safari Implementation

When ready:

1. Keep `extension/` as the shared WebExtension source.
2. Install full Xcode.
3. Run Apple's Safari Web Extension converter against `extension/`.
4. Generate an iOS app target containing the Safari extension.
5. Test on an iPhone and confirm extension enablement, website access prompts, API requests, popup rendering, and external offer-page links.
6. Add a minimal app screen explaining how to enable the extension.

Safari requires iOS extensions to be packaged inside an iOS app. Users manage website permissions through Safari's extension settings.

## Distribution

Use this progression:

- Xcode installation for personal development.
- TestFlight for beta testing.
- App Store release for general users.

## Revisit Criteria

Update this plan after multi-bank support exists, especially when deciding whether users need:

- Bank selection.
- Card selection.
- Account settings.
- A companion app dashboard.
- Per-bank activation links.
- Shared preferences between Chrome and Safari.
