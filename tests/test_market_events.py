"""Tests for sourced market-event display without live API calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electricity_forecaster import production_output as po


class MarketEventsTest(unittest.TestCase):
    def test_missing_feed_is_not_claimed_as_no_outages(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(po, "ROOT", Path(directory)):
                self.assertEqual(po._verified_market_events("2026-11-02T14:00:00Z"), [])
                html = po._market_events_html([])
                self.assertIn("ei ole vahvistettu", html)
                self.assertIn("ei tarkoita", html)

    def test_only_confirmed_sourced_events_are_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            items = [
                {"title": "Example outage", "source_url": "https://example.org/notice",
                 "source_name": "Example", "verification": "confirmed",
                 "observed_at_utc": "2026-11-02T13:00:00Z",
                 "start_utc": "2026-11-02T12:00:00Z",
                 "price_direction": "up", "description": "450 MW unavailable"},
                {"title": "Unsourced", "source_url": "http://example.org/a",
                 "verification": "confirmed", "observed_at_utc": "2026-11-02T13:00:00Z",
                 "start_utc": "2026-11-02T12:00:00Z"},
                {"title": "Unconfirmed", "source_url": "https://example.org/b",
                 "verification": "unverified", "observed_at_utc": "2026-11-02T13:00:00Z",
                 "start_utc": "2026-11-02T12:00:00Z"},
                {"title": "Stale", "source_url": "https://example.org/c",
                 "verification": "confirmed", "observed_at_utc": "2026-10-01T13:00:00Z",
                 "start_utc": "2026-10-01T12:00:00Z"},
            ]
            (root / "data" / "market_events.json").write_text(
                json.dumps({"events": items}), encoding="utf-8")
            with patch.object(po, "ROOT", root):
                found = po._verified_market_events("2026-11-02T14:00:00Z")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["title"], "Example outage")
            self.assertIn("Lähde: Example", po._market_events_html(found))

    def test_outage_intersects_helsinki_forecast_days(self):
        event = {
            "start_utc": "2026-11-05T21:30:00Z",
            "end_utc": "2026-11-06T22:30:00Z",
        }
        days = [
            {"date": "2026-11-05", "d_plus": 2},
            {"date": "2026-11-06", "d_plus": 3},
            {"date": "2026-11-07", "d_plus": 4},
        ]
        matched = po._event_days(event, days)
        self.assertEqual([x["d_plus"] for x in matched], [2, 3, 4])

    def test_event_text_is_escaped(self):
        event = {"title": "<script>alert(1)</script>",
                 "description": "<b>unsafe</b>", "start_utc": "2026-11-02T12:00:00+00:00",
                 "source_url": "https://example.org/", "source_name": "Example",
                 "price_direction": "unknown"}
        html = po._market_events_html([event])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
