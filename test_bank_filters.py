import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "offers-api/src"))
from bank_filters import bank_where_clause, parse_bank_filter  # noqa: E402


class BankFilterTests(unittest.TestCase):
    def test_optional_multiple_and_unknown_banks(self):
        self.assertIsNone(parse_bank_filter(None))
        self.assertEqual(
            parse_bank_filter(["capital_one,american_express,capital_one"]),
            ["capital_one", "american_express"],
        )
        self.assertEqual(parse_bank_filter(["unknown_bank"]), ["unknown_bank"])

    def test_empty_and_malformed_banks(self):
        for value in ([""], ["capital_one,"], ["Capital One"], ["capital_one", "chase"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_bank_filter(value)

    def test_parameterized_clause_filters_rows(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE offers (domain TEXT, bank_slug TEXT)")
        connection.executemany(
            "INSERT INTO offers VALUES (?, ?)",
            [("example.com", "capital_one"), ("example.com", "chase"), ("other.com", "chase")],
        )
        for values, expected in [
            (None, ["capital_one", "chase"]),
            (["chase"], ["chase"]),
            (["unknown_bank"], []),
        ]:
            with self.subTest(values=values):
                rows = connection.execute(
                    "SELECT bank_slug FROM offers WHERE domain = ?" + bank_where_clause(values),
                    ("example.com", *(values or [])),
                ).fetchall()
                self.assertEqual([row[0] for row in rows], expected)
        connection.close()


class BankMigrationTests(unittest.TestCase):
    def test_urls_are_seeded_and_loader_preserves_them(self):
        connection = sqlite3.connect(":memory:")
        migrations = ROOT / "offers-api/migrations"
        for name in (
            "0001_create_offers.sql", "0002_create_banks.sql",
            "0003_remove_unused_offer_indexes.sql", "0004_allow_offer_multiple_domains.sql",
        ):
            connection.executescript((migrations / name).read_text())
        for slug, name in (("capital_one", "Capital One"), ("american_express", "American Express"), ("chase", "Chase")):
            connection.execute("INSERT INTO banks (slug, name) VALUES (?, ?)", (slug, name))
        connection.executescript((migrations / "0005_add_bank_offers_urls.sql").read_text())
        spec = importlib.util.spec_from_file_location("load_offers", ROOT / "offers-api/scripts/load_offers.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection.execute(module.bank_statement("chase", "Chase Bank"))
        rows = dict(connection.execute("SELECT slug, offers_url FROM banks"))
        self.assertEqual(rows, {
            "capital_one": "https://capitaloneoffers.com",
            "american_express": "https://global.americanexpress.com/offers/eligible",
            "chase": "https://secure.chase.com/web/auth/dashboard#/dashboard/merchantOffers/offer-hub",
        })
        connection.close()


if __name__ == "__main__":
    unittest.main()
