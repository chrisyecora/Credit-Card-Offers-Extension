"""Validate and build the optional bank filter for offer lookups."""

import re


BANK_SLUG = re.compile(r"[a-z0-9_]+\Z")


def parse_bank_filter(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    if len(values) != 1:
        raise ValueError("banks must be a comma-separated list of bank slugs")

    slugs = values[0].split(",")
    if not slugs or len(slugs) > 50 or any(not BANK_SLUG.fullmatch(slug) for slug in slugs):
        raise ValueError("banks must be a comma-separated list of bank slugs")
    return list(dict.fromkeys(slugs))


def bank_where_clause(slugs: list[str] | None) -> str:
    if slugs is None:
        return ""
    placeholders = ", ".join("?" for _ in slugs)
    return f" AND offers.bank_slug IN ({placeholders})"
