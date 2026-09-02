from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import FINGRID_API_BASE, get_secret

@dataclass(frozen=True)
class Observation:
    dataset_id: int
    start_time: str
    end_time: str
    value: float

class FingridClient:
    def __init__(self, api_key: str | None = None, min_interval_seconds: float = 2.1):
        self.api_key = (api_key or get_secret("FINGRID_API_KEY")).strip()
        self.min_interval = min_interval_seconds
        self._last = 0.0

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def fetch_raw(self, dataset_id: int, start: datetime, end: datetime) -> Any:
        query = urlencode({
            "startTime": _iso(start),
            "endTime": _iso(end),
            "pageSize": 20000,
        })
        url = f"{FINGRID_API_BASE}/datasets/{dataset_id}/data?{query}"
        req = Request(url, headers={
            "x-api-key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "electricity-forecaster/1.0.2-windows-native",
        })

        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            self._throttle()
            try:
                with urlopen(req, timeout=45) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code in (401, 403):
                    raise RuntimeError(
                        "Fingrid hylkasi API-avaimen (HTTP %s). Tarkista .env-tiedosto." % exc.code
                    ) from exc

                # Fingrid may return 429 with e.g. "Try again in 1 seconds".
                # Respect Retry-After when available and otherwise use bounded backoff.
                if exc.code == 429 or 500 <= exc.code <= 599:
                    retry_after = None
                    try:
                        raw = exc.headers.get("Retry-After")
                        if raw:
                            retry_after = float(raw)
                    except Exception:
                        retry_after = None
                    if retry_after is None:
                        m = re.search(r"Try again in\s+([0-9.]+)\s+seconds?", body, re.I)
                        if m:
                            try:
                                retry_after = float(m.group(1))
                            except Exception:
                                retry_after = None
                    wait = max(1.25, retry_after or 0.0, min(12.0, 1.5 * attempt))
                    if attempt < max_attempts:
                        print(f"[ODOTA] Fingrid HTTP {exc.code}, uusi yritys {attempt+1}/{max_attempts} {wait:.1f} s kuluttua")
                        time.sleep(wait)
                        continue
                raise RuntimeError(f"Fingrid API HTTP {exc.code}: {body}") from exc
            except URLError as exc:
                if attempt < max_attempts:
                    wait = min(12.0, 1.5 * attempt)
                    print(f"[ODOTA] Fingrid-yhteysvirhe, uusi yritys {attempt+1}/{max_attempts} {wait:.1f} s kuluttua")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Fingrid-yhteys epaonnistui: {exc.reason}") from exc

        raise RuntimeError("Fingrid-haku epaonnistui kaikkien uusintayritysten jalkeen.")

    def fetch(self, dataset_id: int, start: datetime, end: datetime) -> tuple[Any, list[Observation]]:
        payload = self.fetch_raw(dataset_id, start, end)
        rows = _extract_rows(payload)
        result = []
        for row in rows:
            result.append(Observation(
                dataset_id=int(row.get("datasetId", dataset_id)),
                start_time=str(row["startTime"]),
                end_time=str(row.get("endTime") or row["startTime"]),
                value=float(row["value"]),
            ))
        return payload, result


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise RuntimeError(f"Fingrid-vastauksen muotoa ei tunnistettu: {type(payload).__name__}")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
