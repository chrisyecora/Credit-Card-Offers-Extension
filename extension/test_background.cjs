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
  const context = vm.createContext({
    importScripts() {},
    tldts: { getDomain: (hostname) => hostname },
    chrome: {
      storage: { local: {
        async get(key) { return { [key]: store[key] }; },
        async set(value) { Object.assign(store, value); },
      } },
      runtime: { onMessage: { addListener() {} } },
    },
    async fetch(url) {
      requests.push(url);
      return fetcher(url);
    },
    URLSearchParams,
    Date,
    console,
  });
  vm.runInContext(source, context);
  return {
    store,
    requests,
    lookup: (domain) => vm.runInContext(`lookupOffers(${JSON.stringify(domain)})`, context),
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
