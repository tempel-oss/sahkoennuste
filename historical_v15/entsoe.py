from __future__ import annotations

import requests
import pandas as pd
import xml.etree.ElementTree as ET

from .config import FINLAND_ENTSOE_DOMAIN

HOTFIX_VERSION = "v1.5.4-A03"


def _as_utc_timestamp(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _resolution_to_timedelta(resolution: str) -> pd.Timedelta:
    mapping = {
        "PT15M": pd.Timedelta(minutes=15),
        "PT30M": pd.Timedelta(minutes=30),
        "PT60M": pd.Timedelta(hours=1),
        "PT1H": pd.Timedelta(hours=1),
    }
    if resolution in mapping:
        return mapping[resolution]
    try:
        return pd.Timedelta(resolution)
    except Exception as e:
        raise ValueError(f"Unsupported ENTSO-E resolution: {resolution}") from e


class EntsoeClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://web-api.tp.entsoe.eu/api",
        timeout: int = 90,
    ):
        if not token:
            raise ValueError("ENTSO-E token is missing.")
        self.token = token
        self.base = base_url
        self.timeout = timeout

    @staticmethod
    def _fmt(ts):
        return _as_utc_timestamp(ts).strftime("%Y%m%d%H%M")

    def fetch_day_ahead_prices(self, start: str, end: str) -> pd.DataFrame:
        s = _as_utc_timestamp(start)
        e = _as_utc_timestamp(end)
        pieces = []
        cur = s

        while cur < e:
            naive = cur.tz_localize(None)
            next_month = (naive + pd.offsets.MonthBegin(1)).tz_localize("UTC")
            nxt = min(next_month, e)
            if nxt <= cur:
                nxt = min(cur + pd.Timedelta(days=31), e)

            params = {
                "securityToken": self.token,
                "documentType": "A44",
                "in_Domain": FINLAND_ENTSOE_DOMAIN,
                "out_Domain": FINLAND_ENTSOE_DOMAIN,
                "periodStart": self._fmt(cur),
                "periodEnd": self._fmt(nxt),
            }

            r = requests.get(self.base, params=params, timeout=self.timeout)
            r.raise_for_status()
            pieces.append(self._parse_price_xml(r.text))
            cur = nxt

        if not pieces:
            return pd.DataFrame(columns=["timestamp_utc", "price_eur_mwh"])

        out = pd.concat(pieces, ignore_index=True)
        if out.empty:
            return out

        out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True)
        out = (
            out.drop_duplicates("timestamp_utc", keep="last")
               .sort_values("timestamp_utc")
        )

        return out[
            (out["timestamp_utc"] >= s) &
            (out["timestamp_utc"] < e)
        ].reset_index(drop=True)

    @staticmethod
    def _parse_price_xml(xml_text: str) -> pd.DataFrame:
        """
        Parse ENTSO-E A44 day-ahead prices.

        CurveType A03 is a variable-sized block curve. Only positions where
        the value changes may be published; the previous value continues until
        the next published position. Expand A03 to a complete timeline before
        hourly resampling.
        """
        root = ET.fromstring(xml_text)

        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        rows = []

        for ts in root.iter(f"{ns}TimeSeries"):
            curve_type = (ts.findtext(f"{ns}curveType") or "A01").strip()

            for period in ts.findall(f"{ns}Period"):
                interval = period.find(f"{ns}timeInterval")
                if interval is None:
                    continue

                start_text = interval.findtext(f"{ns}start")
                end_text = interval.findtext(f"{ns}end")
                if not start_text or not end_text:
                    continue

                start = pd.to_datetime(start_text, utc=True)
                end = pd.to_datetime(end_text, utc=True)

                resolution = (period.findtext(f"{ns}resolution") or "PT60M").strip()
                step = _resolution_to_timedelta(resolution)

                duration = end - start
                expected_positions = int(duration / step)

                point_values = {}
                for point in period.findall(f"{ns}Point"):
                    pos_text = point.findtext(f"{ns}position")
                    price_text = point.findtext(f"{ns}price.amount")
                    if pos_text is None or price_text is None:
                        continue
                    point_values[int(pos_text)] = float(price_text)

                if not point_values:
                    continue

                if curve_type == "A03":
                    current_value = None
                    for pos in range(1, expected_positions + 1):
                        if pos in point_values:
                            current_value = point_values[pos]
                        if current_value is None:
                            continue
                        rows.append((start + (pos - 1) * step, current_value))
                else:
                    for pos, price in sorted(point_values.items()):
                        rows.append((start + (pos - 1) * step, price))

        return pd.DataFrame(rows, columns=["timestamp_utc", "price_eur_mwh"])
