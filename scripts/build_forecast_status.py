from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
FORECAST = OUTPUT / "latest_forecast.json"
STATUS = OUTPUT / "forecast_status.json"


def main() -> None:
    raw = FORECAST.read_bytes()
    forecast = json.loads(raw.decode("utf-8"))

    status = {
        "schema_version": "1.0",
        "status_generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "forecast_run_id": forecast.get("forecast_run_id"),
        "forecast_generated_at_utc": forecast.get("generated_at_utc"),
        "forecast_issue_time": forecast.get("forecast_issue_time"),
        "issue_slot": forecast.get("issue_slot"),
        "model": forecast.get("model", {}),
        "forecast_file": "latest_forecast.json",
        "forecast_sha256": hashlib.sha256(raw).hexdigest(),
        "forecast_size_bytes": len(raw),
        "validation_success": True,
        "publication": {
            "repository_target": "main/output/latest_forecast.json",
            "pages_target": "output/latest_forecast.json",
            "state": "ready_for_publish"
        }
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Status written: {STATUS}")


if __name__ == "__main__":
    main()
