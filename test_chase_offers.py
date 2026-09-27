"""Focused tests for Chase offer extraction and loader identity."""

import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chase_offers import offer_records, offers_from_payload


def merchant(**changes):
    offer = {
        "offerIdentifier": "chase-offer-1",
        "offerStatusName": "NEW",
        "merchantDetails": {"merchantName": "Example Merchant"},
        "offerDisplayDetails": {
            "offerHeaderText": "10% cash back",
            "rewardDescriptionText": "Offer valid online only. Offer only valid on purchases made directly with the merchant.",
            "locationRestrictions": [{"locationName": "ONLINE"}],
            "images": {"logo": {"imageLinkUrlText": "https://images.example/logo.png"}},
            "links": {"callToActionLink": {"linkUrlText": "https://www.example.com/shop"}},
        },
    }
    for key, value in changes.items():
        offer[key] = value
    return offer


def display(**changes):
    value = merchant()["offerDisplayDetails"]
    value.update(changes)
    return value


class ChaseOfferTests(unittest.TestCase):
    def test_online_merchant_uses_link_and_maps_fields(self):
        records, reason = offer_records(merchant())
        self.assertIsNone(reason)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["domain"], "example.com")
        self.assertEqual(records[0]["reward_rate"], "10% cash back")
        self.assertEqual(records[0]["bank_slug"], "chase")

    def test_explicit_additional_sites_and_exclusions(self):
        terms = (
            "Offer valid online at shop.alpha.co.uk and online at beta.com. "
            "Excludes purchases at excluded.com. Visit chase.com for program terms."
        )
        records, _ = offer_records(merchant(offerDisplayDetails=display(rewardDescriptionText=terms)))
        self.assertEqual({item["domain"] for item in records}, {"example.com", "alpha.co.uk", "beta.com"})
        records, reason = offer_records(merchant(offerDisplayDetails=display(
            rewardDescriptionText="Offer valid online. Purchases at example.com are not valid."
        )))
        self.assertEqual((records, reason), ([], "no safely qualifying merchant domain"))

    def test_in_store_only_and_ambiguous_channel_are_skipped(self):
        in_store = merchant(offerDisplayDetails=display(
            locationRestrictions=[{"locationName": "INSTORE"}],
            rewardDescriptionText="Offer valid in-store only.",
        ))
        self.assertEqual(offer_records(in_store)[1], "no qualifying online purchase channel")
        ambiguous = merchant(offerDisplayDetails=display(
            locationRestrictions=[{"locationName": "NONE"}],
            rewardDescriptionText="Offer valid at participating locations.",
        ))
        self.assertEqual(offer_records(ambiguous)[1], "no qualifying online purchase channel")
        both = merchant(offerDisplayDetails=display(
            locationRestrictions=[{"locationName": "NONE"}],
            rewardDescriptionText="Offer valid in-store or online.",
        ))
        self.assertEqual(offer_records(both)[0][0]["channel"], "In Store & Online")

    def test_broad_google_play_domain_and_missing_link_are_skipped(self):
        google = merchant(offerDisplayDetails=display(
            links={"callToActionLink": {"linkUrlText": "https://play.google.com/store"}}
        ))
        self.assertEqual(offer_records(google)[1], "no safely qualifying merchant domain")
        missing = merchant(offerDisplayDetails=display(links={}))
        self.assertEqual(offer_records(missing)[1], "no safely qualifying merchant domain")

    def test_status_and_account_payloads(self):
        offers = [merchant(), merchant(offerIdentifier="second", offerStatusName="SERVED"),
                  merchant(offerIdentifier="third", offerStatusName="ACTIVATED"),
                  merchant(offerIdentifier="expired", offerStatusName="EXPIRED")]
        result = offers_from_payload({"customerOffers": [{"offers": offers, "totalAvailableOfferCount": 4}]})[0]
        self.assertEqual((result.captured, result.returned_count, len(result.records)), (3, 4, 3))
        with self.assertRaises(ValueError):
            offers_from_payload({"customerOffers": [{"offers": None}]})

    def test_card_merge_and_conflict(self):
        from scrape_chase import save_offers

        first = offers_from_payload({"customerOffers": [{"offers": [merchant()]}]})
        same = offers_from_payload({"customerOffers": [{"offers": [merchant()]}]})
        changed = offers_from_payload({"customerOffers": [{"offers": [merchant(
            offerDisplayDetails=display(offerHeaderText="15% cash back")
        )]}]})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "offers_chase.json"
            with patch("scrape_chase.OUTPUT_FILE", output):
                save_offers([("Card A", first), ("Card B", same)])
                self.assertEqual(len(json.loads(output.read_text())), 1)
                with self.assertRaises(RuntimeError):
                    save_offers([("Card A", first), ("Card B", changed)])
                self.assertEqual(len(json.loads(output.read_text())), 1)

    def test_loader_source_keys_and_existing_rows(self):
        root = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location("load_offers", root / "offers-api/scripts/load_offers.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        chase = offer_records(merchant())[0][0]
        second = {**chase, "domain": "other.com"}
        first_values = module.offer_values(chase, "2026-09-26T00:00:00Z", 1)
        second_values = module.offer_values(second, "2026-09-26T00:00:00Z", 2)
        self.assertNotEqual(first_values[0], second_values[0])
        old_key = hashlib.sha256("capital_one\x00old-id".encode()).hexdigest()
        migration_dir = root / "offers-api/migrations"
        with sqlite3.connect(":memory:") as connection:
            for migration in sorted(migration_dir.glob("*.sql")):
                connection.executescript(migration.read_text())
            connection.execute(module.bank_statement("capital_one", "Capital One"))
            connection.execute(module.bank_statement("american_express", "American Express"))
            connection.execute(module.bank_statement("chase", "Chase"))
            capital_one = {**chase, "bank": "Capital One", "bank_slug": "capital_one", "raw_id": "old-id"}
            capital_one_values = module.offer_values(capital_one, "2026-09-26T00:00:00Z", 3)
            self.assertEqual(capital_one_values[0], old_key)
            amex = {**chase, "bank": "American Express", "bank_slug": "american_express"}
            for values in (capital_one_values, module.offer_values(amex, "2026-09-26T00:00:00Z", 4),
                           first_values, second_values):
                connection.execute(module.upsert_statement(values))
            counts = dict(connection.execute("SELECT bank_slug, COUNT(*) FROM offers GROUP BY bank_slug"))
            self.assertEqual(counts, {"capital_one": 1, "american_express": 1, "chase": 2})


if __name__ == "__main__":
    unittest.main()
