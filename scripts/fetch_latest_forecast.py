from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PAGES_BASE = "https://tempel-oss.github.io/sahkoennuste"
RAW_BASE = "https://raw.githubusercontent.com/tempel-oss/sahkoennuste/main/output"


def _get_json(url: str, timeout: float = 10.0) -> dict:
    req = Request(url, headers={"User-Agent": "electricity-forecaster/1.0", "Cache-Control": "no-cache"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate(forecast: dict, status: dict | None, max_age_hours: float) -> None:
    generated = forecast.get("generated_at_utc")
    if not generated:
        raise ValueError("generated_at_utc missing")
    age_h = (datetime.now(timezone.utc) - _parse_utc(generated)).total_seconds() / 3600
    if age_h < -1:
        raise ValueError("forecast timestamp is in the future")
    if age_h > max_age_hours:
        raise ValueError(f"forecast is stale ({age_h:.1f} h > {max_age_hours:.1f} h)")
    if status:
        run_id = status.get("forecast_run_id")
        if run_id and run_id != forecast.get("forecast_run_id"):
            raise ValueError("status and forecast run IDs differ")


def fetch_latest(max_age_hours: float = 18.0) -> tuple[dict, str]:
    errors: list[str] = []
    sources = [("pages", PAGES_BASE), ("repository", RAW_BASE)]
    for name, base in sources:
        try:
            status = None
            try:
                status = _get_json(f"{base}/forecast_status.json")
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                pass
            forecast = _get_json(f"{base}/latest_forecast.json")
            _validate(forecast, status, max_age_hours)
            return forecast, name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("No fresh forecast available; " + "; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read latest forecast via Pages with repository fallback.")
    parser.add_argument("--max-age-hours", type=float, default=18.0)
    parser.add_argument("--output", help="Optional file to write the selected JSON to")
    args = parser.parse_args()
    forecast, source = fetch_latest(args.max_age_hours)
    payload = json.dumps(forecast, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
    print(json.dumps({
        "ok": True,
        "source": source,
        "forecast_run_id": forecast.get("forecast_run_id"),
        "generated_at_utc": forecast.get("generated_at_utc"),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
