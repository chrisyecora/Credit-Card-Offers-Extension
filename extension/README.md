# Credit Card Offer Checker

This is the first Chrome MV3 prototype for the offer checker. It detects the current page hostname, queries the deployed Worker, and displays a small offer notice when the API returns matches.

## Load locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose this `extension/` directory.
4. Visit a supported domain such as `https://nike.com`.

The prototype displays loaded Capital One and American Express offers and links each bank's results to its offers page. AmEx offers must be added to the eligible card on the AmEx site before a purchase. The extension does not complete enrollment or support accounts, card selection, per-offer activation URLs, or Safari packaging.

Click the extension icon to see offers for the active website at any time, even
if its automatic notice is in cooldown. Use **Settings** in that popup to choose
which banks appear. The checklist is saved in this browser's local extension
storage; newly added banks are on by default.
The extension fetches bank names and offers-page links from `/v1/banks`, caches
them for 24 hours, and refreshes the list when the checklist opens. If refresh
fails, it uses the saved list. If no list has ever loaded, offer lookups pause
until the bank list is available. The current shopping domain is sent to the
API on each offer lookup. Offers may be targeted and unavailable on
your own account.

An offer notice appears at most once per site per hour. The extension stores
the time it last found offers for a site in local browser storage, so moving
between pages or subdomains does not reopen the notice. A later page load can
show it again after the hour has passed. Sites without offers do not start a
cooldown.
