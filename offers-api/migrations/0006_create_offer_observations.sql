CREATE TABLE scrape_runs (
    run_id TEXT PRIMARY KEY,
    bank_slug TEXT NOT NULL REFERENCES banks(slug),
    captured_at TEXT NOT NULL,
    published_at TEXT,
    offer_count INTEGER NOT NULL CHECK (offer_count > 0),
    content_sha256 TEXT NOT NULL
);

CREATE INDEX idx_scrape_runs_bank_published
    ON scrape_runs(bank_slug, published_at, captured_at);

CREATE TABLE offer_observations (
    run_id TEXT NOT NULL REFERENCES scrape_runs(run_id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    bank_slug TEXT NOT NULL,
    raw_id TEXT,
    domain TEXT NOT NULL,
    merchant_name TEXT NOT NULL,
    reward_rate TEXT NOT NULL,
    channel TEXT NOT NULL,
    logo_url TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (run_id, source_key)
);

CREATE INDEX idx_offer_observations_source_seen
    ON offer_observations(source_key, last_seen_at);

CREATE TRIGGER validate_scrape_run_publication
BEFORE UPDATE OF published_at ON scrape_runs
WHEN NEW.published_at IS NOT NULL
BEGIN
    -- D1's remote migration parser can misread CASE ... END inside a trigger.
    SELECT RAISE(ABORT, 'scrape run is incomplete') WHERE (
        SELECT COUNT(*) FROM offer_observations WHERE run_id = NEW.run_id
    ) != NEW.offer_count;
    SELECT RAISE(ABORT, 'scrape run has inconsistent observations') WHERE EXISTS (
        SELECT 1 FROM offer_observations
        WHERE run_id = NEW.run_id
          AND (bank_slug != NEW.bank_slug OR last_seen_at != NEW.captured_at)
    );
END;
