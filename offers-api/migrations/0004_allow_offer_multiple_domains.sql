-- An AmEx offer can qualify at several merchant domains. Preserve existing
-- source keys and rows while widening the raw-ID uniqueness constraint.
ALTER TABLE offers RENAME TO offers_previous;

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
    UNIQUE (bank_slug, raw_id, domain)
);

INSERT INTO offers (id, source_key, bank_slug, raw_id, domain, merchant_name, reward_rate, channel, logo_url, last_seen_at)
SELECT id, source_key, bank_slug, raw_id, domain, merchant_name, reward_rate, channel, logo_url, last_seen_at
FROM offers_previous;

DROP TABLE offers_previous;
CREATE INDEX idx_offers_domain ON offers(domain);
