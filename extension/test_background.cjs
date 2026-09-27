const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "background.js"), "utf8");
const banks = [
  { slug: "capital_one", name: "Capital One", offers_url: "https://capitaloneoffers.com" },
  { slug: "chase", name: "Chase", offers_url: "https://chase.example/offers" },
];

function makeBackground(initialStore = {}, fetcher) {
  const store = { ...initialStore };
  const requests = [];
  let now = Date.now();
  let onMessage;
  const context = vm.createContext({
    importScripts() {},
    tldts: { getDomain: (hostname) => hostname.endsWith(".example.com") ? "example.com" : hostname },
    chrome: {
      storage: { local: {
        async get(key) { return { [key]: store[key] }; },
        async set(value) { Object.assign(store, value); },
      } },
      runtime: { onMessage: { addListener(listener) { onMessage = listener; } } },
    },
    async fetch(url) {
      requests.push(url);
      return fetcher(url);
    },
    URLSearchParams,
    Date: class extends Date { static now() { return now; } },
    console,
  });
  vm.runInContext(source, context);
  return {
    store,
    requests,
    lookup: (domain) => vm.runInContext(`lookupOffers(${JSON.stringify(domain)})`, context),
    lookupNotice: (domain) => vm.runInContext(`lookupOffersForNotice(${JSON.stringify(domain)})`, context),
    message: (message) => new Promise((resolve) => { onMessage(message, {}, resolve); }),
    advance: (milliseconds) => { now += milliseconds; },
  };
}

test("enabled slugs are sent and catalog links are attached", async () => {
  const background = makeBackground({ disabledBankSlugs: ["chase"] }, async (url) => ({
    ok: true,
    async json() {
      return url.endsWith("/v1/banks") ? banks : [
        { bank_slug: "capital_one", merchant_name: "Example" },
      ];
    },
  }));
  const first = await background.lookup("example.com");
  const second = await background.lookup("example.com");
  assert.equal(first.offers[0].offers_url, "https://capitaloneoffers.com");
  assert.equal(second.offers.length, 1);
  assert.equal(background.requests.filter((url) => url.endsWith("/v1/banks")).length, 1);
  assert.equal(new URL(background.requests[1]).searchParams.get("banks"), "capital_one");
});

test("all banks disabled skips the offers call", async () => {
  const background = makeBackground({
    bankCatalog: { banks, fetchedAt: Date.now() },
    disabledBankSlugs: ["capital_one", "chase"],
  }, async () => { throw new Error("fetch should not run"); });
  assert.deepEqual(JSON.parse(JSON.stringify(await background.lookup("example.com"))), { offers: [] });
  assert.equal(background.requests.length, 0);
});

test("stale catalog is used when refresh fails", async () => {
  const background = makeBackground({
    bankCatalog: { banks, fetchedAt: 0 },
  }, async (url) => {
    if (url.endsWith("/v1/banks")) throw new Error("offline");
    return { ok: true, async json() { return []; } };
  });
  assert.equal((await background.lookup("example.com")).offers.length, 0);
  assert.equal(background.requests.length, 2);
});

test("missing catalog never triggers an unfiltered lookup", async () => {
  const background = makeBackground({}, async () => { throw new Error("offline"); });
  await assert.rejects(background.lookup("example.com"), /offline/);
  assert.equal(background.requests.length, 1);
  assert.ok(background.requests[0].endsWith("/v1/banks"));
});

test("notice cooldown spans subdomains, expires, and leaves other sites independent", async () => {
  const background = makeBackground({ bankCatalog: { banks, fetchedAt: Date.now() } }, async () => ({
    ok: true,
    async json() { return [{ bank_slug: "capital_one", merchant_name: "Example" }]; },
  }));

  assert.equal((await background.lookupNotice("shop.example.com")).offers.length, 1);
  assert.equal((await background.lookupNotice("checkout.example.com")).suppressed, true);
  assert.equal(background.requests.length, 1);
  const restarted = makeBackground(background.store, async () => {
    throw new Error("cooldown should survive a service worker restart");
  });
  assert.equal((await restarted.lookupNotice("example.com")).suppressed, true);
  assert.equal(restarted.requests.length, 0);
  assert.equal((await background.lookupNotice("other.com")).offers.length, 1);
  background.advance(60 * 60 * 1000);
  assert.equal((await background.lookupNotice("example.com")).offers.length, 1);
  assert.equal(background.requests.length, 3);
});

test("no offers and failed lookups do not start a cooldown", async () => {
  let calls = 0;
  const background = makeBackground({ bankCatalog: { banks, fetchedAt: Date.now() } }, async () => {
    calls += 1;
    if (calls === 2) throw new Error("offline");
    return { ok: true, async json() { return calls === 1 ? [] : [{ bank_slug: "chase" }]; } };
  });

  assert.equal((await background.lookupNotice("example.com")).offers.length, 0);
  await assert.rejects(background.lookupNotice("example.com"), /offline/);
  assert.equal((await background.lookupNotice("example.com")).offers.length, 1);
  assert.equal(calls, 3);
});

test("overlapping page loads only claim one notice", async () => {
  let resolveFetch;
  const background = makeBackground({ bankCatalog: { banks, fetchedAt: Date.now() } }, () =>
    new Promise((resolve) => { resolveFetch = resolve; }));

  const first = background.lookupNotice("shop.example.com");
  const second = background.lookupNotice("checkout.example.com");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(background.requests.length, 1);
  resolveFetch({ ok: true, async json() { return [{ bank_slug: "capital_one" }]; } });
  assert.equal((await first).offers.length, 1);
  assert.equal((await second).suppressed, true);
});

test("manual lookup shows offers during cooldown without extending it", async () => {
  const background = makeBackground({ bankCatalog: { banks, fetchedAt: Date.now() } }, async () => ({
    ok: true,
    async json() { return [{ bank_slug: "capital_one", merchant_name: "Example" }]; },
  }));

  assert.equal((await background.message({ type: "lookup-offers", domain: "example.com" })).offers.length, 1);
  const shownAt = background.store["noticeShownAt:example.com"];
  background.advance(30 * 60 * 1000);
  assert.equal((await background.message({ type: "lookup-offers", domain: "example.com" })).suppressed, true);
  assert.equal((await background.message({ type: "lookup-offers-manual", domain: "example.com" })).offers.length, 1);
  assert.equal(background.store["noticeShownAt:example.com"], shownAt);
  assert.equal(background.requests.length, 2);
});
