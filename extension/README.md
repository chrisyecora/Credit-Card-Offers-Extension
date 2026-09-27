# Credit Card Offer Checker

This is the first Chrome MV3 prototype for the offer checker. It detects the current page hostname, queries the deployed Worker, and displays a small offer notice when the API returns matches.

## Load locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose this `extension/` directory.
4. Visit a supported domain such as `https://nike.com`.

The prototype displays loaded Capital One and American Express offers and links each bank's results to its offers page. AmEx offers must be added to the eligible card on the AmEx site before a purchase. The extension does not complete enrollment or support accounts, card selection, per-offer activation URLs, or Safari packaging.

Click the extension icon to choose which banks appear. The checklist is saved
in this browser's local extension storage; newly added banks are on by default.
The extension fetches bank names and offers-page links from `/v1/banks`, caches
them for 24 hours, and refreshes the list when the checklist opens. If refresh
fails, it uses the saved list. If no list has ever loaded, offer lookups pause
until the bank list is available. The current shopping domain is sent to the
API on each offer lookup. Offers may be targeted and unavailable on
your own account.
