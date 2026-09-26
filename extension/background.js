importScripts("node_modules/tldts/dist/index.umd.min.js");

const API_BASE_URL = "https://offers-api.chris-yecora.workers.dev";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "lookup-offers" || typeof message.domain !== "string") {
    return false;
  }

  const hostname = message.domain.trim().toLowerCase();
  const domain = tldts.getDomain(hostname);
  console.info("[offer-checker] lookup requested", hostname, "as", domain);
  if (!domain) {
    sendResponse({ offers: [] });
    return false;
  }

  fetch(`${API_BASE_URL}/v1/offers?domain=${encodeURIComponent(domain)}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Offer API returned ${response.status}`);
      }
      return response.json();
    })
    .then((offers) => {
      console.info("[offer-checker] lookup returned", domain, offers.length, "offers");
      sendResponse({ offers: Array.isArray(offers) ? offers : [] });
    })
    .catch((error) => {
      console.error("[offer-checker] lookup failed", domain, error);
      sendResponse({ offers: [], error: String(error) });
    });

  return true;
});
