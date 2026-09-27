"""Build the query for recently observed offers in healthy bank feeds."""

from datetime import UTC, datetime, timedelta

from bank_filters import bank_where_clause


FRESHNESS_WINDOW = timedelta(days=14)
OFFER_FIELDS = """
    offers.domain,
    offers.merchant_name,
    offers.reward_rate,
    offers.channel,
    banks.name AS bank,
    banks.slug AS bank_slug,
    offers.logo_url,
    offers.last_seen_at
"""


def cutoff_timestamp(now: datetime | None = None) -> str:
    instant = now if now is not None else datetime.now(UTC)
    cutoff = instant.astimezone(UTC) - FRESHNESS_WINDOW
    if cutoff.microsecond:
        cutoff = cutoff.replace(microsecond=0) + timedelta(seconds=1)
    return cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")


def offer_query(bank_slugs: list[str] | None) -> str:
    return (
        "WITH ranked_offers AS ("
        " SELECT observations.*, "
        " ROW_NUMBER() OVER (PARTITION BY observations.source_key "
        " ORDER BY observations.last_seen_at DESC, runs.published_at DESC, observations.run_id DESC) AS row_number "
        " FROM offer_observations AS observations "
        " JOIN scrape_runs AS runs ON runs.run_id = observations.run_id "
        " WHERE observations.source_key IN ("
        " SELECT source_key FROM offer_observations WHERE domain = ?) "
        " AND runs.published_at IS NOT NULL AND observations.last_seen_at >= ? "
        " AND EXISTS (SELECT 1 FROM scrape_runs AS fresh_runs "
        " WHERE fresh_runs.bank_slug = observations.bank_slug "
        " AND fresh_runs.published_at IS NOT NULL AND fresh_runs.captured_at >= ?)"
        ") "
        f"SELECT {OFFER_FIELDS} FROM ranked_offers AS offers "
        "JOIN banks ON banks.slug = offers.bank_slug "
        f"WHERE offers.row_number = 1 AND offers.domain = ?{bank_where_clause(bank_slugs)}"
    )
