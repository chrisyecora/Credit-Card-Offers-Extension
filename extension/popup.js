const offersView = document.getElementById("offers-view");
const settingsView = document.getElementById("settings-view");
const siteName = document.getElementById("site-name");
const offersStatus = document.getElementById("offers-status");
const offersList = document.getElementById("offers-list");
const offersRetry = document.getElementById("offers-retry");
const settingsButton = document.getElementById("settings-button");
const backButton = document.getElementById("back-button");
const bankList = document.getElementById("bank-list");
const status = document.getElementById("status");
const retry = document.getElementById("retry");
let disabled = new Set();
let saveQueue = Promise.resolve();
let offerRequestId = 0;

function requestBackground(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (response?.error) {
        reject(new Error(response.error));
      } else if (!response) {
        reject(new Error("No response from the extension"));
      } else {
        resolve(response);
      }
    });
  });
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "recently";
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function renderOffers(offers, domain) {
  offersList.replaceChildren();
  if (!offers.length) {
    offersStatus.textContent = "No offers found from your enabled banks on this site.";
    return;
  }
  offersStatus.textContent = "";

  for (const offer of offers) {
    const card = document.createElement("article");
    card.className = "offer-card";

    const merchant = document.createElement("strong");
    merchant.className = "offer-merchant";
    merchant.textContent = offer.merchant_name || domain;
    card.append(merchant);

    const reward = document.createElement("strong");
    reward.className = "offer-reward";
    reward.textContent = offer.reward_rate || "Offer available";
    card.append(reward);

    const metadata = document.createElement("span");
    metadata.className = "offer-meta";
    metadata.textContent = `${offer.bank || "Credit card"} · ${offer.channel || "Online"}`;
    card.append(metadata);

    const seen = document.createElement("small");
    seen.className = "offer-seen";
    seen.textContent = `Last confirmed ${formatDate(offer.last_seen_at)}`;
    card.append(seen);

    if (offer.offers_url) {
      let url;
      try {
        url = new URL(offer.offers_url);
      } catch (error) {
        // An invalid bank link should not hide the rest of the offers.
      }
      if (url?.protocol === "https:") {
        const link = document.createElement("a");
        link.className = "offer-link";
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `Open ${offer.bank || "bank"} offers`;
        card.append(link);
      }
    }
    offersList.append(card);
  }
}

async function loadOffers() {
  const requestId = ++offerRequestId;
  offersRetry.hidden = true;
  offersList.replaceChildren();
  siteName.textContent = "";
  offersStatus.textContent = "Looking for offers…";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (requestId !== offerRequestId) return;
    const url = tab?.url ? new URL(tab.url) : null;
    if (!url || !["http:", "https:"].includes(url.protocol)) {
      offersStatus.textContent = "Open a shopping website to see available offers.";
      return;
    }

    siteName.textContent = url.hostname;
    const result = await requestBackground({ type: "lookup-offers-manual", domain: url.hostname });
    if (requestId !== offerRequestId) return;
    renderOffers(result.offers, url.hostname);
  } catch (error) {
    if (requestId !== offerRequestId) return;
    offersStatus.textContent = "Could not load offers right now.";
    offersRetry.hidden = false;
  }
}

function renderBanks(banks) {
  bankList.replaceChildren();
  if (banks.length === 0) {
    bankList.textContent = "No banks are available yet.";
    return;
  }

  for (const bank of banks) {
    const row = document.createElement("label");
    row.className = "bank-row";
    const name = document.createElement("span");
    name.textContent = bank.name;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !disabled.has(bank.slug);
    checkbox.setAttribute("aria-label", `Show ${bank.name} offers`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        disabled.delete(bank.slug);
      } else {
        disabled.add(bank.slug);
      }
      const next = [...disabled];
      saveQueue = saveQueue.catch(() => {}).then(() => chrome.storage.local.set({ disabledBankSlugs: next }));
      saveQueue.catch(() => { status.textContent = "Could not save your choice. Please try again."; });
      status.textContent = banks.every((item) => disabled.has(item.slug))
        ? "All banks are off. No offers will appear."
        : "Saved on this device.";
    });
    row.append(name, checkbox);
    bankList.append(row);
  }
}

async function loadBanks() {
  retry.hidden = true;
  bankList.textContent = "Loading banks…";
  status.textContent = "";
  try {
    const [catalog, stored] = await Promise.all([
      requestBackground({ type: "get-bank-catalog", forceRefresh: true }),
      chrome.storage.local.get("disabledBankSlugs"),
    ]);
    disabled = new Set(Array.isArray(stored.disabledBankSlugs) ? stored.disabledBankSlugs : []);
    renderBanks(catalog.banks);
    if (catalog.stale) {
      status.textContent = "Showing saved bank list. Could not refresh it right now.";
    } else if (catalog.banks.length && catalog.banks.every((bank) => disabled.has(bank.slug))) {
      status.textContent = "All banks are off. No offers will appear.";
    }
  } catch (error) {
    bankList.textContent = "Bank list unavailable.";
    status.textContent = "Connect to the internet and try again.";
    retry.hidden = false;
  }
}

settingsButton.addEventListener("click", () => {
  offerRequestId += 1;
  offersView.hidden = true;
  settingsView.hidden = false;
  loadBanks();
});
backButton.addEventListener("click", async () => {
  try {
    await saveQueue;
  } catch (error) {
    status.textContent = "Could not save your choice. Please try again.";
    return;
  }
  settingsView.hidden = true;
  offersView.hidden = false;
  loadOffers();
});
offersRetry.addEventListener("click", loadOffers);
retry.addEventListener("click", loadBanks);
loadOffers();
