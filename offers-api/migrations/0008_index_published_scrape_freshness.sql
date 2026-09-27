-- The API checks published runs by bank and capture time. Keep unpublished
-- staging runs out of this index.
DROP INDEX IF EXISTS idx_scrape_runs_bank_published;

CREATE INDEX idx_scrape_runs_fresh
    ON scrape_runs(bank_slug, captured_at)
    WHERE published_at IS NOT NULL;
