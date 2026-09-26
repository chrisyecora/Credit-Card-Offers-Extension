"""Extract domain-matchable merchant offers from an AmEx Offers Hub response."""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


DOMAIN_PATTERN = re.compile(
    r"(?<![\w@])(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>]*)?",
    re.IGNORECASE,
)
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
NEGATIVE_CLAUSE = re.compile(
    r"\b(?:excludes?|excluding|except|not valid|ineligible|third.part(?:y|ies)|resellers?)\b",
    re.IGNORECASE,
)
QUALIFYING_CONTEXT = re.compile(
    r"\b(?:online\s+(?:at|through|on)|(?:us\s+)?website|valid\s+(?:at|on)|"
    r"purchases?\s+(?:made\s+)?(?:at|on|through)|shop\s+(?:at|on)|"
    r"orders?\s+(?:at|on|through))\b",
    re.IGNORECASE,
)
TWO_PART_SUFFIXES = {
    "ac.uk", "co.uk", "org.uk", "gov.uk", "com.au", "net.au", "org.au",
    "co.nz", "com.br", "com.mx", "co.jp", "co.kr", "com.sg", "com.hk",
    "co.in", "com.cn", "com.tw", "co.za", "com.ar",
}
UNRELATED_DOMAINS = {"americanexpress.com", "cardlytics.com"}


class Paragraphs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "br"}:
            self.flush()
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.parts.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "br"}:
            self.flush()

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def flush(self) -> None:
        value = " ".join(" ".join(self.parts).split())
        if value:
            self.paragraphs.append(value)
        self.parts.clear()


def normalize_domain(value: str) -> str | None:
    """Return the registrable domain for supported public suffixes."""
    candidate = value.strip().rstrip(".,;:!?)\"'")
    host = urlsplit(candidate if "://" in candidate else f"https://{candidate}").hostname
    if not host or not re.fullmatch(r"[a-z0-9.-]+", host, re.IGNORECASE):
        return None
    labels = host.lower().strip(".").split(".")
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    if len(labels) < 2:
        return None
    suffix = ".".join(labels[-2:])
    if suffix in TWO_PART_SUFFIXES:
        return ".".join(labels[-3:]) if len(labels) >= 3 else None
    # Unknown two-part country suffixes cannot be normalized safely without a PSL.
    if len(labels[-1]) == 2 and labels[-2] in {"co", "com", "net", "org", "gov", "ac"}:
        return None
    return ".".join(labels[-2:])


def qualifying_terms(details: str) -> list[str]:
    parser = Paragraphs()
    parser.feed(details)
    parser.flush()
    in_qualifying_section = False
    selected: list[str] = []
    for paragraph in parser.paragraphs:
        if "Qualifying Purchases" in paragraph:
            in_qualifying_section = True
            paragraph = paragraph.split("Qualifying Purchases", 1)[1]
        elif in_qualifying_section and re.match(
            r"^(?:Statement Credit|General|Privacy|Offer Expiration|Enrollment)\b",
            paragraph,
            re.IGNORECASE,
        ):
            break
        if in_qualifying_section and paragraph:
            selected.append(paragraph)
    return selected


def qualifying_domains(offer: dict) -> set[str]:
    """Accept only domains explicitly associated with qualifying purchases."""
    descriptions = [str(offer.get("longDescription") or "")]
    terms = offer.get("terms") or {}
    if isinstance(terms, dict):
        descriptions.extend(qualifying_terms(str(terms.get("details") or "")))
    domains: set[str] = set()
    for description in descriptions:
        for sentence in SENTENCE_BOUNDARY.split(html.unescape(description)):
            # Mixed positive and negative clauses are ambiguous; skip the sentence.
            if NEGATIVE_CLAUSE.search(sentence) or not QUALIFYING_CONTEXT.search(sentence):
                continue
            for match in DOMAIN_PATTERN.finditer(sentence):
                prefix = sentence[: match.start()]
                if not QUALIFYING_CONTEXT.search(prefix):
                    continue
                domain = normalize_domain(match.group())
                if domain and domain not in UNRELATED_DOMAINS:
                    domains.add(domain)
    return domains


def offer_records(offer: dict) -> tuple[list[dict[str, str]], str | None]:
    if offer.get("offerType") != "MERCHANT":
        return [], "not a merchant offer"
    required = {"offerId": "raw_id", "title": "merchant_name", "shortDescription": "reward_rate", "image": "logo_url"}
    values: dict[str, str] = {}
    for source, target in required.items():
        value = offer.get(source)
        if not isinstance(value, str) or not value.strip():
            return [], f"missing {source}"
        values[target] = value.strip()
    domains = qualifying_domains(offer)
    if not domains:
        return [], "no explicitly qualifying merchant domain"
    filters = offer.get("applicableFilters") or []
    channels = [item.get("text", "").strip() for item in filters if isinstance(item, dict)]
    channel = " & ".join(dict.fromkeys(value for value in channels if value)) or "See offer terms"
    records = [
        {
            "domain": domain,
            "merchant_name": values["merchant_name"],
            "reward_rate": values["reward_rate"],
            "channel": channel,
            "bank": "American Express",
            "bank_slug": "american_express",
            "raw_id": values["raw_id"],
            "logo_url": values["logo_url"],
        }
        for domain in sorted(domains)
    ]
    return records, None


def offers_from_payload(payload: dict) -> tuple[list[dict[str, str]], int, list[tuple[str, str]]]:
    try:
        page = payload["recommendedOffers"]["offersList"]["page1"]
    except (KeyError, TypeError) as error:
        raise ValueError("Missing recommendedOffers.offersList.page1") from error
    if not isinstance(page, list):
        raise ValueError("recommendedOffers.offersList.page1 must be a list")
    records: dict[tuple[str, str], dict[str, str]] = {}
    skipped: list[tuple[str, str]] = []
    merchant_count = 0
    for item in page:
        if not isinstance(item, dict) or item.get("offerType") != "MERCHANT":
            continue
        merchant_count += 1
        mapped, reason = offer_records(item)
        if reason:
            skipped.append((str(item.get("offerId") or item.get("title") or "unknown"), reason))
        for record in mapped:
            records[(record["raw_id"], record["domain"])] = record
    return list(records.values()), merchant_count, skipped
