DROP TABLE offers;

CREATE TABLE banks (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE offers (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    bank_slug TEXT NOT NULL REFERENCES banks(slug),
    raw_id TEXT,
    domain TEXT NOT NULL,
    merchant_name TEXT NOT NULL,
    reward_rate TEXT NOT NULL,
    channel TEXT NOT NULL,
    logo_url TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (bank_slug, raw_id)
);

CREATE INDEX idx_offers_domain ON offers(domain);
CREATE INDEX idx_offers_bank_domain ON offers(bank_slug, domain);
CREATE INDEX idx_offers_last_seen_at ON offers(last_seen_at);
