import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amex_offers import normalize_domain, offer_records, offers_from_payload, qualifying_domains


def merchant(**changes):
    offer = {
        "offerId": "PX3fW9.ED6",
        "offerType": "MERCHANT",
        "image": "https://images.example/logo.png",
        "title": "Dollar General",
        "shortDescription": "Earn 10% back on a single purchase, up to a total of $5",
        "longDescription": (
            "Earn 10% back after a purchase in-store at Dollar General or online "
            "at dollargeneral.com by 9/30/2026. See terms."
        ),
        "terms": {
            "details": (
                "<p>Read <a href='https://www.americanexpress.com/terms'>program terms</a>.</p>"
                "<p><strong>Qualifying Purchases</strong></p>"
                "<p>Offer valid online at US website dollargeneral.com only. "
                "Excludes purchases at excluded.com. "
                "Not valid through resellers at reseller.com.</p>"
                "<p><strong>Privacy</strong></p><p>Visit privacy.example.com.</p>"
            )
        },
        "applicableFilters": [{"text": "In Store"}, {"text": "Online"}],
    }
    offer.update(changes)
    return offer


class AmexOfferTests(unittest.TestCase):
    def test_default_chrome_command_reuses_profile_window(self):
        from scrape_amex import open_manual_chrome

        with tempfile.TemporaryDirectory() as directory, patch(
            "scrape_amex.CHROME_PROFILE_DIR", Path(directory)
        ), patch(
            "scrape_amex.active_chrome_endpoint", return_value="http://127.0.0.1:9222"
        ), patch("scrape_amex.subprocess.Popen") as launch:
            self.assertEqual(open_manual_chrome(), "http://127.0.0.1:9222")
            launch.assert_not_called()

    def test_default_chrome_command_starts_isolated_profile(self):
        from scrape_amex import open_manual_chrome

        with tempfile.TemporaryDirectory() as directory, patch(
            "scrape_amex.CHROME_PROFILE_DIR", Path(directory)
        ), patch(
            "scrape_amex.active_chrome_endpoint",
            side_effect=[None, "http://127.0.0.1:49214"],
        ), patch("scrape_amex.chrome_executable", return_value="/chrome"):
            with patch("scrape_amex.subprocess.Popen") as launch:
                self.assertEqual(open_manual_chrome(), "http://127.0.0.1:49214")
                arguments = launch.call_args.args[0]
                self.assertIn("--remote-debugging-address=127.0.0.1", arguments)
                self.assertIn("--remote-debugging-port=0", arguments)
                self.assertIn(f"--user-data-dir={Path(directory).resolve()}", arguments)

    def test_supplied_dollar_general_shape(self):
        records, reason = offer_records(merchant())
        self.assertIsNone(reason)
        self.assertEqual([record["domain"] for record in records], ["dollargeneral.com"])
        self.assertEqual(records[0]["bank_slug"], "american_express")
        self.assertEqual(records[0]["channel"], "In Store & Online")

    def test_multiple_qualifying_domains_and_exclusions(self):
        offer = merchant(
            longDescription="Offer valid online at shop.alpha.co.uk and online at beta.com.",
            terms={"details": "<p><strong>Qualifying Purchases</strong></p>"
                              "<p>Purchases at www.gamma.com qualify. Excludes excluded.com.</p>"
                              "<p><strong>Statement Credit</strong></p><p>See unrelated.com.</p>"},
        )
        self.assertEqual(qualifying_domains(offer), {"alpha.co.uk", "beta.com", "gamma.com"})

    def test_no_domain_and_card_offer(self):
        records, reason = offer_records(merchant(longDescription="Valid in store only.", terms={"details": ""}))
        self.assertEqual(records, [])
        self.assertEqual(reason, "no explicitly qualifying merchant domain")
        payload = {"recommendedOffers": {"offersList": {"page1": [merchant(offerType="CARD"), merchant()]}}}
        records, merchant_count, skipped = offers_from_payload(payload)
        self.assertEqual((len(records), merchant_count, skipped), (1, 1, []))

    def test_negative_clause_does_not_create_a_match(self):
        offer = merchant(
            longDescription="Purchases at excluded.com are not valid.",
            terms={"details": "<p><strong>Qualifying Purchases</strong></p>"
                              "<p>Offer valid online at good.com, excluding excluded.com.</p>"},
        )
        self.assertEqual(qualifying_domains(offer), set())

    def test_qualifying_link_is_used_but_program_links_are_not(self):
        offer = merchant(
            longDescription="See terms.",
            terms={"details": "<p><a href='https://americanexpress.com/terms'>Program terms</a></p>"
                              "<p><strong>Qualifying Purchases</strong></p>"
                              "<p>Offer valid online at <a href='https://shop.merchant.com/deal'>the merchant website</a>.</p>"},
        )
        self.assertEqual(qualifying_domains(offer), {"merchant.com"})

    def test_normalizes_supported_registrable_domains(self):
        self.assertEqual(normalize_domain("https://shop.dollargeneral.com/path"), "dollargeneral.com")
        self.assertEqual(normalize_domain("www.alpha.co.uk"), "alpha.co.uk")
        self.assertIsNone(normalize_domain("shop.example.co.zz"))

    def test_loader_identity_and_migration_preserve_capital_one_rows(self):
        root = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location("load_offers", root / "offers-api/scripts/load_offers.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        amex = offer_records(merchant())[0][0]
        another_domain = {**amex, "domain": "another.com"}
        first = module.offer_values(amex, "2026-09-26T00:00:00Z", 1)
        second = module.offer_values(another_domain, "2026-09-26T00:00:00Z", 2)
        self.assertNotEqual(first[0], second[0])

        import base64
        capital_id = base64.urlsafe_b64encode(json.dumps({
            "inventory": {"source": "PX3fW9.ED6", "merchantTLD": amex["domain"]},
            "viewContext": "page-1", "offers": ["offer"], "v": 1,
        }).encode()).decode().rstrip("=")
        capital_one = {**amex, "bank": "Capital One", "bank_slug": "capital_one", "raw_id": capital_id}
        old_key = hashlib.sha256("capital_one\x00PX3fW9.ED6".encode()).hexdigest()
        self.assertNotEqual(module.offer_values(capital_one, "2026-09-26T00:00:00Z", 3)[0], old_key)

        migration_dir = root / "offers-api/migrations"
        with sqlite3.connect(":memory:") as connection:
            for name in ("0001_create_offers.sql", "0002_create_banks.sql", "0003_remove_unused_offer_indexes.sql"):
                connection.executescript((migration_dir / name).read_text())
            connection.execute("INSERT INTO banks (slug, name) VALUES ('capital_one', 'Capital One')")
            connection.execute("INSERT INTO banks (slug, name) VALUES ('american_express', 'American Express')")
            connection.execute(
                "INSERT INTO offers (source_key, bank_slug, raw_id, domain, merchant_name, reward_rate, channel, logo_url, last_seen_at) "
                "VALUES (?, 'capital_one', 'old-id', 'old.com', 'Old', '5%', 'Online', 'https://example.com/logo', '2026-09-25')",
                (old_key,),
            )
            connection.executescript((migration_dir / "0004_allow_offer_multiple_domains.sql").read_text())
            self.assertEqual(connection.execute("SELECT source_key FROM offers WHERE domain = 'old.com'").fetchone()[0], old_key)
            for values in (first, second):
                connection.execute(module.bank_statement("american_express", "American Express"))
                connection.execute(module.upsert_statement(values))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM offers WHERE bank_slug = 'american_express'").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
