from __future__ import annotations
import time
import requests
import pandas as pd
from .common import safe_numeric

HOTFIX_VERSION = "v1.5.5-rate-limit"

def _as_utc_timestamp(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")

class FingridClient:
    """
    Fingrid Open Data historical client.

    v1.5.5 changes:
    - slower normal request interval (2.5 s)
    - automatic retry/backoff for HTTP 429 and transient 5xx errors
    - larger default chunks (120 days) to reduce API-call count
    - wide-format /api/data response support retained
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://data.fingrid.fi/api",
        timeout: int = 90,
        min_interval_s: float = 2.5,
        page_size: int = 20000,
        max_retries: int = 7,
    ):
        if not api_key:
            raise ValueError("FINGRID_API_KEY is missing.")
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval_s = min_interval_s
        self.page_size = page_size
        self.max_retries = max_retries
        self._last = 0.0

    def _wait_for_slot(self):
        wait = self.min_interval_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)

    def _get(self, url, params):
        last_error = None

        for attempt in range(self.max_retries + 1):
            self._wait_for_slot()

            try:
                r = requests.get(
                    url,
                    params=params,
                    headers={
                        "x-api-key": self.api_key,
                        "Accept": "application/json",
                    },
                    timeout=self.timeout,
                )
                self._last = time.time()

                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    try:
                        retry_after_s = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        retry_after_s = 0.0

                    # Fingrid's documented default is one call per 2 seconds.
                    # Give extra margin and increase wait on repeated collisions.
                    backoff = max(
                        retry_after_s,
                        3.0 + attempt * 2.0,
                    )
                    last_error = RuntimeError(
                        f"HTTP 429 rate limit; retry in {backoff:.1f}s"
                    )
                    print(
                        f"    Fingrid 429: waiting {backoff:.1f}s "
                        f"(retry {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(backoff)
                    continue

                if 500 <= r.status_code <= 599:
                    backoff = min(30.0, 3.0 * (attempt + 1))
                    last_error = RuntimeError(
                        f"HTTP {r.status_code}; retry in {backoff:.1f}s"
                    )
                    print(
                        f"    Fingrid {r.status_code}: waiting {backoff:.1f}s "
                        f"(retry {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(backoff)
                    continue

                r.raise_for_status()
                return r.json()

            except (requests.Timeout, requests.ConnectionError) as e:
                self._last = time.time()
                backoff = min(30.0, 3.0 * (attempt + 1))
                last_error = e
                print(
                    f"    Fingrid connection retry: waiting {backoff:.1f}s "
                    f"(retry {attempt + 1}/{self.max_retries})"
                )
                time.sleep(backoff)

        raise RuntimeError(
            f"Fingrid request failed after retries: {last_error}"
        )

    @staticmethod
    def _normalize(payload):
        if isinstance(payload, dict):
            for key in ("data", "items", "results"):
                if key in payload and isinstance(payload[key], list):
                    payload = payload[key]
                    break

        if not isinstance(payload, list):
            raise ValueError(
                f"Unexpected Fingrid response type: {type(payload)}"
            )

        df = pd.DataFrame(payload)
        if df.empty:
            return pd.DataFrame(columns=["timestamp_utc", "value"])

        start_candidates = [
            "startTime", "start_time", "timestamp", "time"
        ]
        st = next(
            (c for c in start_candidates if c in df.columns),
            None,
        )
        if not st:
            raise ValueError(
                f"Unknown Fingrid timestamp columns: {list(df.columns)}"
            )

        if "value" in df.columns:
            vc = "value"
        elif "Value" in df.columns:
            vc = "Value"
        else:
            meta = {
                "startTime", "endTime",
                "start_time", "end_time",
                "timestamp", "time",
                "datasetId", "dataset_id",
            }
            value_candidates = [
                c for c in df.columns if c not in meta
            ]
            if len(value_candidates) != 1:
                raise ValueError(
                    "Could not identify Fingrid value column. "
                    f"Columns={list(df.columns)}, "
                    f"candidates={value_candidates}"
                )
            vc = value_candidates[0]

        out = pd.DataFrame({
            "timestamp_utc": pd.to_datetime(
                df[st], utc=True, errors="coerce"
            ),
            "value": safe_numeric(df[vc]),
        })
        return (
            out.dropna(subset=["timestamp_utc"])
               .sort_values("timestamp_utc")
        )

    def _fetch_window(self, dataset_id: int, start, end):
        s = _as_utc_timestamp(start)
        e = _as_utc_timestamp(end)

        params = {
            "datasets": str(dataset_id),
            "startTime": s.isoformat().replace("+00:00", "Z"),
            "endTime": e.isoformat().replace("+00:00", "Z"),
            "format": "json",
            "oneRowPerTimePeriod": "true",
            "locale": "en",
            "pageSize": self.page_size,
            "sortBy": "startTime",
            "sortOrder": "asc",
        }

        payload = self._get(f"{self.base}/data", params)
        out = self._normalize(payload)

        if not out.empty:
            out = out[
                (out["timestamp_utc"] >= s) &
                (out["timestamp_utc"] < e)
            ]

        if len(out) >= self.page_size:
            raise RuntimeError(
                f"Fingrid response reached pageSize={self.page_size}; "
                "reduce chunk_days to avoid possible truncation."
            )

        return out

    def fetch_dataset(
        self,
        dataset_id: int,
        start: str,
        end: str,
        chunk_days: int = 120,
    ) -> pd.DataFrame:
        start_ts = _as_utc_timestamp(start)
        end_ts = _as_utc_timestamp(end)

        pieces = []
        cur = start_ts
        chunk_no = 0

        while cur < end_ts:
            nxt = min(
                cur + pd.Timedelta(days=chunk_days),
                end_ts,
            )
            chunk_no += 1
            print(
                f"    chunk {chunk_no}: "
                f"{cur.date()} -> {nxt.date()}"
            )
            pieces.append(
                self._fetch_window(dataset_id, cur, nxt)
            )
            cur = nxt

        if not pieces:
            return pd.DataFrame(
                columns=["timestamp_utc", "value"]
            )

        out = pd.concat(pieces, ignore_index=True)
        out = (
            out.drop_duplicates("timestamp_utc", keep="last")
               .sort_values("timestamp_utc")
        )

        return out[
            (out["timestamp_utc"] >= start_ts) &
            (out["timestamp_utc"] < end_ts)
        ]
