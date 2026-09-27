"""Convert Chase Offers Hub responses into domain-matchable offer records."""

from dataclasses import dataclass
import html
import re
from urllib.parse import urlsplit

from amex_offers import (
    DOMAIN_PATTERN,
    NEGATIVE_CLAUSE,
    SENTENCE_BOUNDARY,
    Paragraphs,
    normalize_domain,
    qualifying_domains,
)


USABLE_STATUSES = {"NEW", "SERVED", "ACTIVATED"}
ONLINE_TERMS = re.compile(r"\b(?:valid|available)\s+(?:in.store\s+(?:or|and)\s+)?online\b", re.I)
ONLINE_EXCLUDED = re.compile(r"\b(?:not\s+valid|excluded|ineligible)\s+(?:for\s+)?online\b", re.I)
# These merchant links represent one service on a much broader registrable domain.
BROAD_PLATFORM_HOSTS = {"play.google.com"}
UNRELATED_DOMAINS = {"chase.com", "chasecdn.com", "cardlytics.com"}
BROAD_PLATFORM_DOMAINS = {"google.com"}


@dataclass
class AccountOffers:
    records: list[dict[str, str]]
    captured: int
    skipped: list[tuple[str, str]]
    available_count: int | None
    returned_count: int


def readable_terms(value: str) -> str:
    parser = Paragraphs()
    parser.feed(value)
    parser.flush()
    return ". ".join(parser.paragraphs)


def online_channel(offer: dict) -> str | None:
    display = offer.get("offerDisplayDetails") or {}
    locations = display.get("locationRestrictions") or []
    kinds = {
        item.get("locationName")
        for item in locations
        if isinstance(item, dict) and isinstance(item.get("locationName"), str)
    }
    terms = readable_terms(str(display.get("rewardDescriptionText") or ""))
    if "INSTORE" in kinds and "ONLINE" not in kinds and "NONE" not in kinds:
        return None
    if ONLINE_EXCLUDED.search(terms):
        return None
    if "ONLINE" in kinds:
        return "Online"
    if "NONE" in kinds and ONLINE_TERMS.search(terms):
        return "In Store & Online" if re.search(r"\bin.store\b", terms, re.I) else "Online"
    return None


def candidate_domains(offer: dict) -> set[str]:
    display = offer.get("offerDisplayDetails") or {}
    terms = readable_terms(str(display.get("rewardDescriptionText") or ""))
    domains = qualifying_domains({"longDescription": terms})
    link = (display.get("links") or {}).get("callToActionLink") or {}
    url = link.get("linkUrlText")
    if isinstance(url, str):
        parsed = urlsplit(html.unescape(url))
        host = (parsed.hostname or "").lower()
        if parsed.scheme in {"http", "https"} and host not in BROAD_PLATFORM_HOSTS:
            domain = normalize_domain(host)
            if domain:
                domains.add(domain)
    # A call-to-action link is not proof that an explicitly excluded site qualifies.
    excluded = set()
    for sentence in SENTENCE_BOUNDARY.split(terms):
        if NEGATIVE_CLAUSE.search(sentence):
            for match in DOMAIN_PATTERN.finditer(sentence):
                domain = normalize_domain(match.group())
                if domain:
                    excluded.add(domain)
    return domains - UNRELATED_DOMAINS - BROAD_PLATFORM_DOMAINS - excluded


def offer_records(offer: dict) -> tuple[list[dict[str, str]], str | None]:
    if offer.get("offerStatusName") not in USABLE_STATUSES:
        return [], "offer status is not usable"
    channel = online_channel(offer)
    if not channel:
        return [], "no qualifying online purchase channel"
    display = offer.get("offerDisplayDetails") or {}
    merchant = offer.get("merchantDetails") or {}
    logo = (display.get("images") or {}).get("logo") or {}
    fields = {
        "raw_id": offer.get("offerIdentifier"),
        "merchant_name": merchant.get("merchantName"),
        "reward_rate": display.get("offerHeaderText"),
        "logo_url": logo.get("imageLinkUrlText"),
    }
    for field, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            return [], f"missing {field}"
    domains = candidate_domains(offer)
    if not domains:
        return [], "no safely qualifying merchant domain"
    return [
        {
            "domain": domain,
            "merchant_name": fields["merchant_name"].strip(),
            "reward_rate": fields["reward_rate"].strip(),
            "channel": channel,
            "bank": "Chase",
            "bank_slug": "chase",
            "raw_id": fields["raw_id"].strip(),
            "logo_url": fields["logo_url"].strip(),
        }
        for domain in sorted(domains)
    ], None


def offers_from_payload(payload: dict) -> list[AccountOffers]:
    accounts = payload.get("customerOffers") if isinstance(payload, dict) else None
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("Missing customerOffers account list")
    results = []
    for account in accounts:
        if not isinstance(account, dict) or not isinstance(account.get("offers"), list):
            raise ValueError("A customerOffers account has no offers list")
        offers = account["offers"]
        expected = account.get("totalAvailableOfferCount")
        if expected is not None and (not isinstance(expected, int) or expected < 0):
            raise ValueError("Invalid totalAvailableOfferCount")
        records = {}
        skipped = []
        captured = 0
        for offer in offers:
            if not isinstance(offer, dict):
                raise ValueError("An offer is not an object")
            if offer.get("offerStatusName") not in USABLE_STATUSES:
                continue
            captured += 1
            mapped, reason = offer_records(offer)
            if reason:
                skipped.append((str(offer.get("offerIdentifier") or "unknown"), reason))
            for record in mapped:
                records[(record["raw_id"], record["domain"])] = record
        results.append(AccountOffers(list(records.values()), captured, skipped, expected, len(offers)))
    return results
