(() => {
  if (window.top !== window.self || !/^https?:$/.test(window.location.protocol)) {
    return;
  }

  const domain = window.location.hostname;
  if (!domain) {
    return;
  }

  console.info("[offer-checker] content script loaded", domain);
  chrome.runtime.sendMessage({ type: "lookup-offers", domain }, (response) => {
    if (chrome.runtime.lastError) {
      console.error("[offer-checker] message failed", chrome.runtime.lastError.message);
      return;
    }
    if (response?.error) {
      console.error("[offer-checker] API error", response.error);
      return;
    }
    if (!response?.offers?.length) {
      console.info("[offer-checker] no offers", domain);
      return;
    }

    console.info("[offer-checker] rendering", response.offers.length, "offers");
    renderNotice(response.offers);
  });

  function renderNotice(offers) {
    document.getElementById("credit-card-offer-checker")?.remove();

    const host = document.createElement("div");
    host.id = "credit-card-offer-checker";
    const shadow = host.attachShadow({ mode: "open" });
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = chrome.runtime.getURL("content.css");
    shadow.append(stylesheet);

    const panel = document.createElement("aside");
    panel.className = "offer-panel";
    panel.setAttribute("role", "status");
    panel.setAttribute("aria-live", "polite");

    const header = document.createElement("div");
    header.className = "offer-header";

    const heading = document.createElement("strong");
    heading.textContent = "Offer found";
    header.append(heading);

    const close = document.createElement("button");
    close.className = "offer-close";
    close.type = "button";
    close.title = "Dismiss offer notice";
    close.setAttribute("aria-label", "Dismiss offer notice");
    close.textContent = "x";
    close.addEventListener("click", () => host.remove());
    header.append(close);
    panel.append(header);

    const merchant = document.createElement("p");
    merchant.className = "offer-merchant";
    merchant.textContent = offers[0].merchant_name || domain;
    panel.append(merchant);

    const list = document.createElement("div");
    list.className = "offer-list";
    offers.slice(0, 3).forEach((offer) => list.append(createOfferRow(offer)));
    panel.append(list);

    if (offers.length > 3) {
      const more = document.createElement("p");
      more.className = "offer-more";
      more.textContent = `+${offers.length - 3} more offers`;
      panel.append(more);
    }

    shadow.append(panel);
    document.documentElement.append(host);
  }

  function createOfferRow(offer) {
    const row = document.createElement("div");
    row.className = "offer-row";

    const details = document.createElement("div");
    details.className = "offer-details";

    const reward = document.createElement("strong");
    reward.textContent = offer.reward_rate || "Offer available";
    details.append(reward);

    const metadata = document.createElement("span");
    metadata.textContent = `${offer.bank || "Credit card"} · ${offer.channel || "Online"}`;
    details.append(metadata);

    const seen = document.createElement("small");
    seen.textContent = `Last confirmed ${formatDate(offer.last_seen_at)}`;
    details.append(seen);
    row.append(details);

    const link = document.createElement("a");
    const destinations = {
      capital_one: { url: "https://capitaloneoffers.com", label: "Open Capital One offers" },
      american_express: { url: "https://global.americanexpress.com/offers/eligible", label: "Open AmEx offers" },
    };
    const destination = destinations[offer.bank_slug];
    if (!destination) {
      return row;
    }
    link.href = destination.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = destination.label;
    row.append(link);
    return row;
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "recently";
    }
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
})();
