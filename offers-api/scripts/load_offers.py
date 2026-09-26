"""Load the scraper's offers.json into the remote D1 database."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
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


def normalize_domain(value: str) -> str:
    domain = value.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/", maxsplit=1)[0]


def sql_value(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


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

    # The source ID is stable when provided. Only the known missing-ID case needs
    # a deterministic fallback identity.
    identity = "\x00".join(
        (bank_slug, raw_id)
        if raw_id
        else (bank_slug, values["domain"], values["merchant_name"], values["channel"])
    )
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
    changed_fields = " OR\n    ".join(
        f"offers.{column} IS NOT excluded.{column}"
        for column in columns[1:-1]
    )
    return (
        f"INSERT INTO offers ({', '.join(columns)})\n"
        f"VALUES ({', '.join(sql_value(value) for value in values[:-1])})\n"
        "ON CONFLICT(source_key) DO UPDATE SET\n"
        f"    {updates}\n"
        f"WHERE {changed_fields};"
    )


def bank_statement(slug: str, name: str) -> str:
    return (
        f"INSERT INTO banks (slug, name) VALUES ({sql_value(slug)}, {sql_value(name)}) "
        "ON CONFLICT(slug) DO UPDATE SET name = excluded.name "
        "WHERE banks.name IS NOT excluded.name;"
    )


def run_batch(database: str, statements: list[str]) -> None:
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
                "--remote",
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
    parser.add_argument("--apply", action="store_true", help="write offers to remote D1")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    try:
        offers = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(offers, list):
            raise ValueError("Input JSON must be an array of offers")
        last_seen_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        values = [
            offer_values(offer, last_seen_at, index)
            for index, offer in enumerate(offers, start=1)
        ]
        bank_names: dict[str, str] = {}
        for value in values:
            slug, name = value[1], value[-1]
            if slug in bank_names and bank_names[slug] != name:
                raise ValueError(f"Conflicting names for bank slug {slug!r}")
            bank_names[slug] = name
        statements = [
            upsert_statement(value) for value in values
        ]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to prepare offers: {error}", file=sys.stderr)
        return 1
    print(f"Prepared {len(statements)} offers with last_seen_at={last_seen_at}.")
    if not args.apply:
        print("Dry run complete. Re-run with --apply to write to remote D1.")
        return 0

    if bank_names:
        run_batch(args.database, [bank_statement(slug, name) for slug, name in bank_names.items()])

    for start in range(0, len(statements), args.batch_size):
        batch_number = start // args.batch_size + 1
        batch = statements[start : start + args.batch_size]
        print(f"Uploading batch {batch_number} ({len(batch)} offers)...")
        run_batch(args.database, batch)

    print(f"Loaded {len(statements)} offers into remote D1 database {args.database!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
