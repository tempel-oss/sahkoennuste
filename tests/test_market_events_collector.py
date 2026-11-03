"""Offline regression tests for ENTSO-E market-event collection."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "collect_market_events.py"
spec = importlib.util.spec_from_file_location("collect_market_events", MODULE)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<Unavailability_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:unavailabilitydocument:3:0">
  <mRID>notice-123</mRID>
  <type>A80</type>
  <createdDateTime>2026-11-03T04:00Z</createdDateTime>
  <TimeSeries>
    <mRID>series-1</mRID>
    <businessType>A54</businessType>
    <registeredResource.name>Testivoimala</registeredResource.name>
    <available_Period>
      <timeInterval>
        <start>2026-11-03T04:00Z</start>
        <end>2026-11-03T16:00Z</end>
      </timeInterval>
    </available_Period>
  </TimeSeries>
</Unavailability_MarketDocument>'''


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.content[:size]


class MarketEventsCollectorTest(unittest.TestCase):
    def test_parse_generation_notice(self):
        events = collector.parse_notices(
            XML, datetime(2026, 11, 3, 5, tzinfo=timezone.utc), "A80")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["verification"], "confirmed")
        self.assertIn("Testivoimala", events[0]["title"])
        self.assertEqual(events[0]["price_direction"], "unknown")

    def test_missing_token_does_not_replace_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "events.json"
            path.write_text("original", encoding="utf-8")
            result = collector.collect(token="", output=path)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(path.read_text(encoding="utf-8"), "original")

    def test_partial_source_error_does_not_publish(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 2:
                raise URLError("offline")
            return FakeResponse(XML)

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "events.json"
            result = collector.collect(
                now=datetime(2026, 11, 3, 5, tzinfo=timezone.utc),
                token="test-secret", opener=opener, output=path)
            self.assertEqual(result["status"], "unavailable")
            self.assertFalse(path.exists())
            self.assertNotIn("test-secret", json.dumps(result))

    def test_successful_collection(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "events.json"
            result = collector.collect(
                now=datetime(2026, 11, 3, 5, tzinfo=timezone.utc),
                token="test-secret",
                opener=lambda request, timeout: FakeResponse(XML),
                output=path)
            self.assertEqual(result["status"], "ok")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["events"]), 2)


if __name__ == "__main__":
    unittest.main()
