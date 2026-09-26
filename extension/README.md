# Credit Card Offer Checker

This is the first Chrome MV3 prototype for the offer checker. It detects the current page hostname, queries the deployed Worker, and displays a small offer notice when the API returns matches.

## Load locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose this `extension/` directory.
4. Visit a supported domain such as `https://nike.com`.

The prototype currently uses Capital One as the only bank and links users to the Capital One offers page for activation. It intentionally does not complete activation or support accounts, card selection, per-offer activation URLs, or Safari packaging.
