"""Read-only live ENTSO-E smoke check; no production files are modified."""
import json
import os
import tempfile
from pathlib import Path

from collect_market_events import collect


def main():
    if not os.environ.get("ENTSOE_API_TOKEN", "").strip():
        print("LIVE_CHECK=NOT_RUN: token not available in this workflow")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        result = collect(output=Path(tmp) / "market_events.json")
        snapshot = json.loads((Path(tmp) / "market_events.json").read_text(encoding="utf-8"))
        print("LIVE_STATUS=" + result["status"])
        print("LIVE_QUERIES=" + str(result["queries_succeeded"]) +
              "/" + str(result["queries_total"]))
        print("LIVE_EVENTS=" + str(result["events"]))
        print("LIVE_FAILED_SCOPES=" + ",".join(snapshot["failed_scopes"]))
        return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
