"""Stage and publish a verified scraper capture in D1."""

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PROJECT_DIR.parent
REQUIRED_FIELDS = (
    "domain",
    "merchant_name",
    "reward_rate",
    "channel",
    "bank",
    "logo_url",
)
LEGACY_BANK_SLUGS = {"Capital One": "capital_one"}
MAX_CAPTURE_AGE = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(minutes=5)
OBSERVATION_RETENTION = timedelta(days=30)


def normalize_domain(value: str) -> str:
    domain = value.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/", maxsplit=1)[0]


def sql_value(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def capital_one_identity(raw_id: str, domain: str, index: int) -> tuple[str, str]:
    """Exclude the per-page viewContext from Capital One's encoded offer ID."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw_id + "=" * (-len(raw_id) % 4)))
        inventory = decoded["inventory"]
        source = inventory["source"]
        merchant_tld = inventory["merchantTLD"]
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
        raise ValueError(f"Offer {index} has an unrecognized Capital One ID") from error
    if (not isinstance(source, str) or not source or
            not isinstance(merchant_tld, str) or normalize_domain(merchant_tld) != domain):
        raise ValueError(f"Offer {index} has an invalid Capital One inventory identity")
    return source, domain


def offer_values(offer: object, last_seen_at: str, index: int) -> tuple[str, ...]:
    if not isinstance(offer, dict):
        raise ValueError(f"Offer {index} must be an object")

    values: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        value = offer.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Offer {index} has an invalid {field!r}")
        values[field] = value.strip()

    values["domain"] = normalize_domain(values["domain"])
    if not values["domain"]:
        raise ValueError(f"Offer {index} has an empty domain")

    bank_slug = offer.get("bank_slug")
    if bank_slug is None:
        bank_slug = LEGACY_BANK_SLUGS.get(values["bank"])
    if not isinstance(bank_slug, str) or not bank_slug or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in bank_slug
    ):
        raise ValueError(f"Offer {index} needs a valid 'bank_slug'")

    raw_id = offer.get("raw_id")
    if raw_id is not None and not isinstance(raw_id, str):
        raise ValueError(f"Offer {index} has an invalid 'raw_id'")
    raw_id = raw_id.strip() if raw_id else None

    if raw_id and bank_slug == "capital_one":
        identity_parts = (bank_slug, *capital_one_identity(raw_id, values["domain"], index))
    elif raw_id and bank_slug in {"american_express", "chase"}:
        # One AmEx or Chase offer can apply to more than one website.
        identity_parts = (bank_slug, raw_id, values["domain"])
    elif raw_id:
        identity_parts = (bank_slug, raw_id)
    else:
        identity_parts = (bank_slug, values["domain"], values["merchant_name"], values["channel"])
    identity = "\x00".join(identity_parts)
    source_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    return (
        source_key,
        bank_slug,
        raw_id,
        values["domain"],
        values["merchant_name"],
        values["reward_rate"],
        values["channel"],
        values["logo_url"],
        last_seen_at,
        values["bank"],
    )


def upsert_statement(values: tuple[str, ...]) -> str:
    columns = (
        "source_key",
        "bank_slug",
        "raw_id",
        "domain",
        "merchant_name",
        "reward_rate",
        "channel",
        "logo_url",
        "last_seen_at",
    )
    updates = ",\n    ".join(f"{column} = excluded.{column}" for column in columns[1:])
    return (
        f"INSERT INTO offers ({', '.join(columns)})\n"
        f"VALUES ({', '.join(sql_value(value) for value in values[:-1])})\n"
        "ON CONFLICT(source_key) DO UPDATE SET\n"
        f"    {updates};"
    )


def bank_statement(slug: str, name: str) -> str:
    return (
        f"INSERT INTO banks (slug, name) VALUES ({sql_value(slug)}, {sql_value(name)}) "
        "ON CONFLICT(slug) DO UPDATE SET name = excluded.name "
        "WHERE banks.name IS NOT excluded.name;"
    )


def prepare_capture(input_path: Path, now: datetime) -> tuple[str, str, str, str, list[str], list[tuple[str, ...]]]:
    payload = input_path.read_bytes()
    metadata_path = input_path.with_name(input_path.name + ".meta.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("Missing supported scrape metadata; run a fresh browser scrape")
    bank_slug = metadata.get("bank_slug")
    captured_at = metadata.get("captured_at")
    digest = hashlib.sha256(payload).hexdigest()
    if not isinstance(bank_slug, str) or not bank_slug:
        raise ValueError("Scrape metadata has no bank slug")
    if metadata.get("sha256") != digest:
        raise ValueError("Scrape metadata does not match the offers file")
    warnings = metadata.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValueError("Scrape metadata has invalid warnings")
    if not isinstance(captured_at, str):
        raise ValueError("Scrape metadata has no capture time")
    try:
        captured = datetime.strptime(captured_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("Scrape capture time must be UTC with second precision") from error
    age = now.astimezone(UTC) - captured
    if age > MAX_CAPTURE_AGE or age < -MAX_CLOCK_SKEW:
        raise ValueError("Scrape capture must be from the last 24 hours and not in the future")
    offers = json.loads(payload)
    if not isinstance(offers, list) or not offers:
        raise ValueError("Input JSON must contain at least one offer")
    if (type(metadata.get("offer_count")) is not int or
            metadata["offer_count"] != len(offers)):
        raise ValueError("Scrape metadata offer count does not match the file")
    values = [offer_values(offer, captured_at, index) for index, offer in enumerate(offers, 1)]
    if any(value[1] != bank_slug for value in values):
        raise ValueError("A capture must contain only its declared bank")
    if len({value[0] for value in values}) != len(values):
        raise ValueError("Capture contains duplicate offer identities")
    bank_names = {value[-1] for value in values}
    if len(bank_names) != 1:
        raise ValueError("Capture contains conflicting bank names")
    run_id = hashlib.sha256(f"{bank_slug}\0{captured_at}\0{digest}".encode()).hexdigest()
    return run_id, bank_slug, bank_names.pop(), digest, warnings, values


def run_statement(run_id: str, bank_slug: str, captured_at: str, count: int, digest: str) -> str:
    return (
        "INSERT INTO scrape_runs (run_id, bank_slug, captured_at, offer_count, content_sha256) "
        f"VALUES ({sql_value(run_id)}, {sql_value(bank_slug)}, {sql_value(captured_at)}, "
        f"{count}, {sql_value(digest)}) ON CONFLICT(run_id) DO NOTHING;"
    )


def observation_statement(run_id: str, values: tuple[str, ...]) -> str:
    columns = (
        "run_id", "source_key", "bank_slug", "raw_id", "domain", "merchant_name",
        "reward_rate", "channel", "logo_url", "last_seen_at",
    )
    row = (run_id, *values[:-1])
    return (
        f"INSERT INTO offer_observations ({', '.join(columns)}) "
        f"VALUES ({', '.join(sql_value(value) for value in row)}) "
        "ON CONFLICT(run_id, source_key) DO NOTHING;"
    )


def publish_statement(run_id: str, published_at: str) -> str:
    return (
        "UPDATE scrape_runs SET published_at = COALESCE(published_at, "
        f"{sql_value(published_at)}) WHERE run_id = {sql_value(run_id)};"
    )


def prune_statements(bank_slug: str, cutoff: str) -> list[str]:
    # Prune one expired run for this bank per publication to avoid a burst of
    # billable index writes after a long gap between scrapes.
    old_run = (
        "SELECT run_id FROM scrape_runs "
        f"WHERE bank_slug = {sql_value(bank_slug)} AND captured_at < {sql_value(cutoff)} "
        "ORDER BY captured_at LIMIT 1"
    )
    return [
        f"DELETE FROM offer_observations WHERE run_id IN ({old_run});",
        f"DELETE FROM scrape_runs WHERE run_id IN ({old_run});",
    ]


def run_batch(database: str, statements: list[str], *, local: bool = False) -> None:
    # Wrangler manages execution of the SQL file; D1 rejects explicit BEGIN/COMMIT.
    sql = "\n".join(statements) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", encoding="utf-8", delete=False) as file:
        file.write(sql)
        sql_path = Path(file.name)

    try:
        subprocess.run(
            [
                "npm",
                "exec",
                "wrangler",
                "--",
                "d1",
                "execute",
                database,
                "--local" if local else "--remote",
                "--yes",
                f"--file={sql_path}",
            ],
            cwd=PROJECT_DIR,
            check=True,
        )
    finally:
        sql_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=REPOSITORY_DIR / "offers.json")
    parser.add_argument("--database", default="offers-db")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--apply", action="store_true", help="write the capture to D1")
    parser.add_argument("--confirm-complete", action="store_true", help="confirm this is a complete bank scrape")
    parser.add_argument("--local", action="store_true", help="use local D1 instead of remote D1")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.apply and not args.confirm_complete:
        parser.error("--apply requires --confirm-complete after reviewing the capture")

    try:
        run_id, bank_slug, bank_name, digest, warnings, values = prepare_capture(args.input, datetime.now(UTC))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to prepare offers: {error}", file=sys.stderr)
        return 1
    captured_at = values[0][-2]
    statements = [observation_statement(run_id, value) for value in values]
    print(f"Prepared {len(statements)} {bank_name} offers captured at {captured_at} (run {run_id[:12]}).")
    for warning in warnings:
        print(f"Scraper warning: {warning}")
    if not args.apply:
        print("Dry run complete. Review the scraper counts and warnings before --apply --confirm-complete.")
        return 0

    try:
        run_batch(args.database, [bank_statement(bank_slug, bank_name),
                                  run_statement(run_id, bank_slug, captured_at, len(values), digest)], local=args.local)
        for start in range(0, len(statements), args.batch_size):
            batch_number = start // args.batch_size + 1
            batch = statements[start : start + args.batch_size]
            print(f"Uploading batch {batch_number} ({len(batch)} offers)...")
            run_batch(args.database, batch, local=args.local)
        published_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        run_batch(args.database, [publish_statement(run_id, published_at)], local=args.local)
    except subprocess.CalledProcessError as error:
        print(f"Upload failed; run {run_id[:12]} remains unpublished: {error}", file=sys.stderr)
        return 1
    retention_cutoff = (datetime.now(UTC) - OBSERVATION_RETENTION).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    try:
        run_batch(args.database, prune_statements(bank_slug, retention_cutoff), local=args.local)
    except subprocess.CalledProcessError as error:
        print(f"Published run {run_id[:12]}, but old observation cleanup failed: {error}", file=sys.stderr)
    print(f"Published {len(statements)} offers for {bank_name} in {'local' if args.local else 'remote'} D1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
