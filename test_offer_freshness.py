"""Capture validation and D1 publication behavior."""

import importlib.util
import base64
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from capture_artifact import metadata_path, write_capture, write_unverified_capture


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "offers-api/src"))
from offer_freshness import cutoff_timestamp, offer_query  # noqa: E402

spec = importlib.util.spec_from_file_location("load_offers", ROOT / "offers-api/scripts/load_offers.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


def capital_id(source: str, domain: str = "example.com", view: str = "page-1") -> str:
    return base64.urlsafe_b64encode(json.dumps({
        "inventory": {"source": source, "merchantTLD": domain},
        "viewContext": view, "offers": ["offer"], "v": 1,
    }).encode()).decode().rstrip("=")


def offer(raw_id: str, bank_slug: str = "chase") -> dict[str, str]:
    if bank_slug == "capital_one":
        raw_id = capital_id(raw_id)
    return {
        "domain": "example.com", "merchant_name": "Example", "reward_rate": "10%",
        "channel": "Online", "bank": "Chase" if bank_slug == "chase" else "Capital One",
        "bank_slug": bank_slug, "raw_id": raw_id, "logo_url": "https://example.com/logo.png",
    }


def timestamp(instant: datetime) -> str:
    return instant.isoformat(timespec="seconds").replace("+00:00", "Z")


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        for migration in sorted((ROOT / "offers-api/migrations").glob("*.sql")):
            self.db.executescript(migration.read_text())

    def tearDown(self):
        self.db.close()

    def add_run(self, run_id: str, instant: datetime, offers: list[dict], publish: bool = True):
        seen_at = timestamp(instant)
        self.db.execute(loader.run_statement(run_id, offers[0]["bank_slug"], seen_at, len(offers), "digest"))
        for index, item in enumerate(offers, 1):
            values = loader.offer_values(item, seen_at, index)
            self.db.execute(loader.observation_statement(run_id, values))
        if publish:
            self.db.execute(loader.publish_statement(run_id, seen_at))

    def results(self, instant: datetime = NOW, banks: list[str] | None = None):
        cutoff = cutoff_timestamp(instant)
        return self.db.execute(
            offer_query(banks), ("example.com", cutoff, cutoff, "example.com", *(banks or []))
        ).fetchall()

    def test_missing_offer_keeps_its_date_until_14_day_boundary(self):
        self.add_run("old", NOW - timedelta(days=13), [offer("old")])
        self.add_run("new", NOW, [offer("new")])
        self.assertEqual({row[2] for row in self.results()}, {"10%"})
        self.assertEqual({row[-1] for row in self.results()},
                         {timestamp(NOW - timedelta(days=13)), timestamp(NOW)})
        self.assertEqual(len(self.results(NOW + timedelta(days=1))), 2)
        self.assertEqual(len(self.results(NOW + timedelta(days=1, seconds=1))), 1)
        self.assertEqual(self.results(NOW + timedelta(days=14, seconds=1)), [])

    def test_unchanged_offer_gets_new_last_seen_time(self):
        self.add_run("old", NOW - timedelta(days=3), [offer("same")])
        self.add_run("new", NOW, [offer("same")])
        rows = self.results()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][-1], timestamp(NOW))

    def test_fractional_second_cutoff_does_not_extend_freshness(self):
        self.assertEqual(
            cutoff_timestamp(NOW + timedelta(days=14, microseconds=1)),
            timestamp(NOW + timedelta(seconds=1)),
        )

    def test_latest_observation_uses_current_offer_fields(self):
        self.add_run("old", NOW - timedelta(days=1), [offer("same", "capital_one")])
        changed = {**offer("same", "capital_one"), "reward_rate": "12%"}
        self.add_run("new", NOW, [changed])
        self.assertEqual(len(self.results()), 1)
        self.assertEqual(self.results()[0][2], "12%")

    def test_capital_one_view_context_does_not_change_identity(self):
        first = offer("same", "capital_one")
        second = {**first, "raw_id": capital_id("same", view="page-2")}
        self.assertEqual(loader.offer_values(first, timestamp(NOW), 1)[0],
                         loader.offer_values(second, timestamp(NOW), 2)[0])
        self.add_run("old", NOW - timedelta(days=1), [first])
        self.add_run("new", NOW, [second])
        self.assertEqual(len(self.results()), 1)
        self.assertEqual(self.results()[0][-1], timestamp(NOW))

    def test_capital_one_inventory_source_distinguishes_same_merchant(self):
        first = offer("source-a", "capital_one")
        second = offer("source-b", "capital_one")
        self.assertNotEqual(loader.offer_values(first, timestamp(NOW), 1)[0],
                            loader.offer_values(second, timestamp(NOW), 2)[0])

    def test_unrecognized_capital_one_id_is_rejected(self):
        invalid = {**offer("same", "capital_one"), "raw_id": "unexpected-id"}
        with self.assertRaisesRegex(ValueError, "unrecognized Capital One ID"):
            loader.offer_values(invalid, timestamp(NOW), 1)

    def test_unpublished_or_incomplete_run_cannot_refresh_feed(self):
        self.add_run("old", NOW - timedelta(days=15), [offer("old")])
        self.add_run("pending", NOW, [offer("pending")], publish=False)
        self.assertEqual(self.results(), [])
        self.db.execute(loader.run_statement("incomplete", "chase", timestamp(NOW), 2, "digest"))
        self.db.execute(loader.observation_statement(
            "incomplete", loader.offer_values(offer("one"), timestamp(NOW), 1)
        ))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(loader.publish_statement("incomplete", timestamp(NOW)))
        self.assertEqual(self.results(), [])
        self.db.execute(loader.publish_statement("pending", timestamp(NOW)))
        self.assertEqual(len(self.results()), 1)

    def test_bank_filter_and_repeat_import(self):
        self.add_run("chase", NOW, [offer("one")])
        self.add_run("capital", NOW, [offer("two", "capital_one")])
        self.add_run("chase", NOW, [offer("one")])
        self.assertEqual(len(self.results()), 2)
        self.assertEqual(len(self.results(banks=["chase"])), 1)
        self.assertEqual(self.results(banks=["unknown"]), [])

    def test_prune_only_removes_runs_outside_retention(self):
        self.add_run("expired", NOW - timedelta(days=31), [offer("old")])
        self.add_run("older", NOW - timedelta(days=32), [offer("older")])
        self.add_run("kept", NOW - timedelta(days=29), [offer("new")])
        for statement in loader.prune_statements("chase", timestamp(NOW - timedelta(days=30))):
            self.db.execute(statement)
        self.assertEqual(
            self.db.execute("SELECT run_id FROM scrape_runs ORDER BY run_id").fetchall(),
            [("expired",), ("kept",)],
        )
        self.assertEqual(
            self.db.execute("SELECT run_id FROM offer_observations ORDER BY run_id").fetchall(),
            [("expired",), ("kept",)],
        )


class CaptureValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name) / "offers.json"
        write_capture(self.output, [offer("one")], "chase")
        self.metadata = metadata_path(self.output)

    def tearDown(self):
        self.directory.cleanup()

    def prepare(self):
        metadata = json.loads(self.metadata.read_text())
        observed = datetime.strptime(metadata["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return loader.prepare_capture(self.output, observed + timedelta(minutes=1))

    def test_fresh_capture_and_missing_metadata(self):
        self.assertEqual(len(self.prepare()[-1]), 1)
        self.metadata.unlink()
        with self.assertRaises(OSError):
            self.prepare()

    def test_saved_response_invalidates_previous_capture_metadata(self):
        write_unverified_capture(self.output, [offer("one")])
        self.assertFalse(self.metadata.exists())
        with self.assertRaises(OSError):
            self.prepare()

    def test_tampered_old_empty_mixed_and_duplicate_inputs(self):
        original = self.output.read_bytes()
        self.output.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.prepare()
        self.output.write_bytes(original)

        metadata = json.loads(self.metadata.read_text())
        metadata["captured_at"] = timestamp(NOW - timedelta(days=2))
        self.metadata.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "last 24 hours"):
            loader.prepare_capture(self.output, NOW)

        for records, expected in [([], "at least one"),
                                  ([offer("one"), offer("two", "capital_one")], "declared bank"),
                                  ([offer("one"), offer("one")], "duplicate")]:
            write_capture(self.output, records or [offer("one")], "chase")
            if not records:
                self.output.write_text("[]\n")
                meta = json.loads(self.metadata.read_text())
                meta["offer_count"] = 0
                import hashlib
                meta["sha256"] = hashlib.sha256(self.output.read_bytes()).hexdigest()
                self.metadata.write_text(json.dumps(meta))
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                self.prepare()


class CapitalOneCaptureTests(unittest.TestCase):
    def test_unrelated_initial_feed_responses_are_ignored(self):
        from scrape_capital_one import offer_feed_items

        self.assertIsNone(offer_feed_items([{"name": "Shopping"}]))
        self.assertIsNone(offer_feed_items({"data": [{"name": "Shopping"}]}))
        self.assertIsNone(offer_feed_items({"data": []}))
        self.assertEqual(
            offer_feed_items({"data": [{"id": "one", "merchantTLD": "example.com"}]}),
            [{"id": "one", "merchantTLD": "example.com"}],
        )

    def test_feed_error_preserves_unverified_rows_and_old_output(self):
        from scrape_capital_one import finish_capture

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "offers.json"
            partial = Path(directory) / "offers_partial.json"
            output.write_text("old output")
            with patch("scrape_capital_one.OUTPUT_FILE", output), patch(
                "scrape_capital_one.PARTIAL_OUTPUT_FILE", partial
            ):
                with self.assertRaisesRegex(RuntimeError, "HTTP 500 at /feed/offers"):
                    finish_capture({"one": offer("one", "capital_one")}, 47,
                                   ["HTTP 500 at /feed/offers"])
                self.assertEqual(output.read_text(), "old output")
                self.assertEqual(len(json.loads(partial.read_text())), 1)
                self.assertFalse(metadata_path(partial).exists())

                finish_capture({"one": offer("one", "capital_one")}, 48, [])
                self.assertFalse(partial.exists())
                self.assertTrue(metadata_path(output).exists())


if __name__ == "__main__":
    unittest.main()
