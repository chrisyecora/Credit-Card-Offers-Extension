CREATE TABLE offers (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    merchant_name TEXT NOT NULL,
    reward_rate TEXT NOT NULL,
    channel TEXT NOT NULL,
    bank TEXT NOT NULL,
    raw_id TEXT UNIQUE,
    logo_url TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX idx_offers_domain ON offers(domain);
CREATE INDEX idx_offers_last_seen_at ON offers(last_seen_at);
