const bankList = document.getElementById("bank-list");
const status = document.getElementById("status");
const retry = document.getElementById("retry");
let disabled = new Set();
let saveQueue = Promise.resolve();

function requestCatalog() {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type: "get-bank-catalog", forceRefresh: true }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (response?.error) {
        reject(new Error(response.error));
      } else {
        resolve(response);
      }
    });
  });
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
      requestCatalog(),
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

retry.addEventListener("click", loadBanks);
loadBanks();
