-- The API filters by domain and joins banks by the bank primary key.
-- These two indexes are not used by the current read path and add write
-- amplification for every inserted or changed offer row.
DROP INDEX IF EXISTS idx_offers_bank_domain;
DROP INDEX IF EXISTS idx_offers_last_seen_at;
