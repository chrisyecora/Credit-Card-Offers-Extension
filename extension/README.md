# Credit Card Offer Checker

This is the first Chrome MV3 prototype for the offer checker. It detects the current page hostname, queries the deployed Worker, and displays a small offer notice when the API returns matches.

## Load locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose this `extension/` directory.
4. Visit a supported domain such as `https://nike.com`.

The prototype displays loaded Capital One and American Express offers and links each bank's results to its offers page. AmEx offers must be added to the eligible card on the AmEx site before a purchase. The extension does not complete enrollment or support accounts, card selection, per-offer activation URLs, or Safari packaging.
