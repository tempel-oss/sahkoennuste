"""Read-only live ENTSO-E smoke check; no production files are modified."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from collect_market_events import collect


def main():
    if not os.environ.get("ENTSOE_API_TOKEN", "").strip():
        print("LIVE_CHECK=NOT_RUN: token not available in this workflow")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        result = collect(output=Path(tmp) / "market_events.json")
        snapshot = json.loads((Path(tmp) / "market_events.json").read_text(encoding="utf-8"))
        # Verify real source records before considering the live test successful.
        events = snapshot.get("events", [])
        ids = [event["event_id"] for event in events]
        if len(ids) != len(set(ids)):
            raise AssertionError("Duplicate event identifiers")
        now = datetime.now(timezone.utc)
        for event in events:
            observed = datetime.fromisoformat(event["observed_at_utc"].replace("Z", "+00:00"))
            published = datetime.fromisoformat(event["source_published_at_utc"].replace("Z", "+00:00"))
            start = datetime.fromisoformat(event["start_utc"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(event["end_utc"].replace("Z", "+00:00"))
            if not (start < end and observed <= now and published <= now):
                raise AssertionError("Invalid event timestamps")
            if event.get("verification") != "confirmed" or event.get("price_direction") != "unknown":
                raise AssertionError("Unexpected event verification or price claim")
            if event.get("category") not in ("generation_unavailability", "transmission_unavailability"):
                raise AssertionError("Unexpected event category")
            if not event.get("title") or not event.get("source_url", "").startswith("https://"):
                raise AssertionError("Missing source or title")
        print("LIVE_VALIDATED_EVENTS=" + str(len(events)))
        print("LIVE_STATUS=" + result["status"])
        print("LIVE_QUERIES=" + str(result["queries_succeeded"]) +
              "/" + str(result["queries_total"]))
        print("LIVE_EVENTS=" + str(result["events"]))
        print("LIVE_FAILED_SCOPES=" + ",".join(snapshot["failed_scopes"]))
        return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
