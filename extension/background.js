importScripts("node_modules/tldts/dist/index.umd.min.js");

const API_BASE_URL = "https://offers-api.chris-yecora.workers.dev";
const CATALOG_TTL_MS = 24 * 60 * 60 * 1000;
let catalogRequest;

function validCatalog(banks) {
  return Array.isArray(banks) && banks.every((bank) =>
    bank && typeof bank.slug === "string" && /^[a-z0-9_]+$/.test(bank.slug) &&
    typeof bank.name === "string" &&
    (bank.offers_url === null || (typeof bank.offers_url === "string" &&
      bank.offers_url.startsWith("https://")))
  );
}

async function getBankCatalog(forceRefresh = false) {
  const { bankCatalog } = await chrome.storage.local.get("bankCatalog");
  const cached = bankCatalog && validCatalog(bankCatalog.banks) ? bankCatalog : null;
  if (!forceRefresh && cached && Date.now() - cached.fetchedAt < CATALOG_TTL_MS) {
    return { banks: cached.banks, stale: false };
  }

  if (!catalogRequest) {
    catalogRequest = (async () => {
      const response = await fetch(`${API_BASE_URL}/v1/banks`);
      if (!response.ok) {
        throw new Error(`Bank API returned ${response.status}`);
      }
      const banks = await response.json();
      if (!validCatalog(banks)) {
        throw new Error("Bank API returned an invalid catalog");
      }
      await chrome.storage.local.set({ bankCatalog: { banks, fetchedAt: Date.now() } });
      return banks;
    })().finally(() => { catalogRequest = null; });
  }

  try {
    return { banks: await catalogRequest, stale: false };
  } catch (error) {
    if (cached) {
      return { banks: cached.banks, stale: true };
    }
    throw error;
  }
}

async function lookupOffers(hostname) {
  const domain = tldts.getDomain(hostname.trim().toLowerCase());
  if (!domain) {
    return { offers: [] };
  }

  const { banks } = await getBankCatalog();
  const { disabledBankSlugs } = await chrome.storage.local.get("disabledBankSlugs");
  const disabled = new Set(Array.isArray(disabledBankSlugs) ? disabledBankSlugs : []);
  const enabled = banks.filter((bank) => !disabled.has(bank.slug));
  if (enabled.length === 0) {
    return { offers: [] };
  }

  const params = new URLSearchParams({
    domain,
    banks: enabled.map((bank) => bank.slug).join(","),
  });
  const response = await fetch(`${API_BASE_URL}/v1/offers?${params}`);
  if (!response.ok) {
    throw new Error(`Offer API returned ${response.status}`);
  }
  const offers = await response.json();
  if (!Array.isArray(offers)) {
    throw new Error("Offer API returned invalid data");
  }
  const destinations = new Map(banks.map((bank) => [bank.slug, bank.offers_url]));
  return {
    offers: offers.map((offer) => ({
      ...offer,
      offers_url: destinations.get(offer.bank_slug) || null,
    })),
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "get-bank-catalog") {
    getBankCatalog(message.forceRefresh === true)
      .then(sendResponse)
      .catch((error) => sendResponse({ error: String(error) }));
    return true;
  }
  if (message?.type === "lookup-offers" && typeof message.domain === "string") {
    lookupOffers(message.domain)
      .then(sendResponse)
      .catch((error) => {
        console.error("[offer-checker] lookup failed", error);
        sendResponse({ offers: [], error: String(error) });
      });
    return true;
  }
  return false;
});
