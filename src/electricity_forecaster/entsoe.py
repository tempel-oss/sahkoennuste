from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import html
import re
import socket
import time
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

from .config import ENTSOE_API_BASES, get_secret

@dataclass(frozen=True)
class EntsoePoint:
    start_time: str
    end_time: str
    value: float
    unit: str | None
    psr_type: str | None = None

class EntsoeApiError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "unknown", status: int | None = None,
                 endpoint: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.endpoint = endpoint
        self.retryable = retryable

class EntsoeClient:
    def __init__(self, token: str | None = None, endpoints: tuple[str, ...] | None = None,
                 retry_delays: tuple[int, ...] = (3, 10, 20)):
        self.token = (token or get_secret("ENTSOE_API_TOKEN")).strip()
        self.endpoints = endpoints or ENTSOE_API_BASES
        self.retry_delays = retry_delays
        if not self.token:
            raise EntsoeApiError("ENTSOE_API_TOKEN puuttuu .env-tiedostosta.", kind="token_missing")

    def query(self, params: dict[str, Any]) -> bytes:
        last_error: EntsoeApiError | None = None
        for endpoint in self.endpoints:
            try:
                return self._query_endpoint(endpoint, params)
            except EntsoeApiError as exc:
                last_error = exc
                # Authentication/request errors should not be hidden by trying another host.
                if not exc.retryable:
                    raise
                # Transient service/gateway errors may be endpoint-specific; try fallback host.
                continue
        if last_error:
            raise last_error
        raise EntsoeApiError("ENTSO-E API -kysely epaonnistui tuntemattomasta syysta.")

    def _query_endpoint(self, endpoint: str, params: dict[str, Any]) -> bytes:
        q = {"securityToken": self.token, **params}
        url = endpoint + "?" + urlencode(q)
        attempts = 1 + len(self.retry_delays)
        for attempt in range(attempts):
            try:
                req = Request(url, headers={
                    "Accept": "application/xml,text/xml,*/*",
                    "User-Agent": "electricity-forecaster/0.4.2-windows-native",
                    "Cache-Control": "no-cache",
                })
                with urlopen(req, timeout=60) as resp:
                    raw = resp.read()
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if "text/html" in ctype or _looks_like_html(raw):
                        raise EntsoeApiError(
                            "ENTSO-E palautti HTML-sivun API-datan sijasta. Palvelu tai reititys voi olla tilapaisesti hairiintynyt.",
                            kind="service_html", endpoint=endpoint, retryable=True)
                    return raw
            except HTTPError as exc:
                raw = exc.read()
                body = _short_body(raw)
                if exc.code in (401, 403):
                    raise EntsoeApiError(
                        f"ENTSO-E hylkasi kayttooikeuden (HTTP {exc.code}). Tarkista, etta token on Web API Security Token ja Restful API access on aktivoitu.",
                        kind="auth", status=exc.code, endpoint=endpoint, retryable=False) from exc
                if exc.code == 429:
                    retry_after = _retry_after_seconds(exc)
                    if attempt < attempts - 1:
                        time.sleep(retry_after if retry_after is not None else self.retry_delays[attempt])
                        continue
                    raise EntsoeApiError(
                        "ENTSO-E rajoitti kyselynopeutta (HTTP 429). Yrita myohemmin uudelleen.",
                        kind="rate_limit", status=429, endpoint=endpoint, retryable=True) from exc
                if exc.code in (500, 502, 503, 504):
                    if attempt < attempts - 1:
                        time.sleep(self.retry_delays[attempt])
                        continue
                    raise EntsoeApiError(
                        f"ENTSO-E-palvelu ei ole juuri nyt kaytettavissa (HTTP {exc.code}) endpointissa {endpoint}. "
                        "Tama ei itsessaan tarkoita, etta token olisi vaarin.",
                        kind="service_unavailable", status=exc.code, endpoint=endpoint, retryable=True) from exc
                # 400 is often an API acknowledgement explaining bad parameters/no data.
                reason = _extract_reason(raw)
                msg = reason or body or f"HTTP {exc.code}"
                raise EntsoeApiError(
                    f"ENTSO-E API hylkasi kyselyn (HTTP {exc.code}): {msg}",
                    kind="request", status=exc.code, endpoint=endpoint, retryable=False) from exc
            except EntsoeApiError as exc:
                if exc.retryable and attempt < attempts - 1:
                    time.sleep(self.retry_delays[attempt])
                    continue
                raise
            except URLError as exc:
                if attempt < attempts - 1:
                    time.sleep(self.retry_delays[attempt])
                    continue
                raise EntsoeApiError(
                    f"ENTSO-E-verkkoyhteys epaonnistui endpointissa {endpoint}: {exc.reason}",
                    kind="network", endpoint=endpoint, retryable=True) from exc
            except TimeoutError as exc:
                if attempt < attempts - 1:
                    time.sleep(self.retry_delays[attempt])
                    continue
                raise EntsoeApiError(
                    f"ENTSO-E-yhteys aikakatkaistiin endpointissa {endpoint}.",
                    kind="timeout", endpoint=endpoint, retryable=True) from exc
        raise EntsoeApiError("ENTSO-E-kyselyn uudelleenyritykset loppuivat.", kind="unknown", endpoint=endpoint)

    def endpoint_diagnostics(self) -> list[dict[str, str]]:
        result = []
        for endpoint in self.endpoints:
            host = urlparse(endpoint).hostname or ""
            item = {"endpoint": endpoint, "host": host, "dns": "?"}
            try:
                addresses = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
                item["dns"] = ", ".join(addresses[:4]) if addresses else "ei osoitetta"
            except OSError as exc:
                item["dns"] = f"VIRHE: {exc}"
            result.append(item)
        return result

    def day_ahead_prices(self, area_eic: str, start: datetime, end: datetime) -> tuple[bytes, list[EntsoePoint]]:
        raw = self.query({
            "documentType": "A44",
            "in_Domain": area_eic,
            "out_Domain": area_eic,
            "periodStart": _period(start),
            "periodEnd": _period(end),
        })
        return raw, parse_points(raw, value_tags=("price.amount",))

    def total_load(self, area_eic: str, start: datetime, end: datetime, process_type: str) -> tuple[bytes, list[EntsoePoint]]:
        raw = self.query({
            "documentType": "A65",
            "processType": process_type,
            "outBiddingZone_Domain": area_eic,
            "periodStart": _period(start),
            "periodEnd": _period(end),
        })
        return raw, parse_points(raw, value_tags=("quantity",))

    def wind_solar_forecast(self, area_eic: str, start: datetime, end: datetime, psr_type: str) -> tuple[bytes, list[EntsoePoint]]:
        raw = self.query({
            "documentType": "A69",
            "processType": "A01",
            "in_Domain": area_eic,
            "psrType": psr_type,
            "periodStart": _period(start),
            "periodEnd": _period(end),
        })
        return raw, parse_points(raw, value_tags=("quantity",), forced_psr=psr_type)


def parse_points(xml_bytes: bytes, value_tags: tuple[str, ...], forced_psr: str | None = None) -> list[EntsoePoint]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        if _looks_like_html(xml_bytes):
            raise EntsoeApiError("ENTSO-E palautti HTML-sivun XML-datan sijasta.", kind="service_html", retryable=True) from exc
        raise RuntimeError("ENTSO-E-vastaus ei ollut kelvollista XML:aa.") from exc
    reason = _extract_reason(xml_bytes)
    timeseries = [el for el in root.iter() if _local(el.tag) == "TimeSeries"]
    if not timeseries:
        if reason:
            raise RuntimeError("ENTSO-E ei palauttanut dataa: " + reason)
        raise RuntimeError("ENTSO-E-vastauksessa ei ollut TimeSeries-dataa.")

    result: list[EntsoePoint] = []
    for ts in timeseries:
        psr = forced_psr or _find_text(ts, "MktPSRType/psrType") or _find_text(ts, "psrType")
        unit = _find_text(ts, "price_Measure_Unit.name") or _find_text(ts, "quantity_Measure_Unit.name") or _find_text(ts, "measurement_Unit.name")
        for period in [e for e in ts.iter() if _local(e.tag) == "Period"]:
            start_txt = _find_text(period, "timeInterval/start")
            resolution_txt = _find_text(period, "resolution")
            if not start_txt or not resolution_txt:
                continue
            base = _parse_dt(start_txt)
            step = _duration(resolution_txt)
            for point in [e for e in period if _local(e.tag) == "Point"]:
                pos_txt = _find_text(point, "position")
                val_txt = None
                for tag in value_tags:
                    val_txt = _find_text(point, tag)
                    if val_txt is not None:
                        break
                if not pos_txt or val_txt is None:
                    continue
                pos = int(pos_txt)
                st = base + step * (pos - 1)
                en = st + step
                result.append(EntsoePoint(_iso(st), _iso(en), float(val_txt), unit, psr))
    return result


def _retry_after_seconds(exc: HTTPError) -> int | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return max(1, min(120, int(value))) if value else None
    except ValueError:
        return None


def _looks_like_html(raw: bytes) -> bool:
    head = raw[:500].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head


def _short_body(raw: bytes) -> str:
    if not raw:
        return ""
    if _looks_like_html(raw):
        text = raw.decode("utf-8", errors="replace")
        title = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
        if title:
            return "HTML: " + html.unescape(re.sub(r"\s+", " ", title.group(1))).strip()
        return "HTML-vastaus"
    text = raw.decode("utf-8", errors="replace")
    return re.sub(r"\s+", " ", text).strip()[:500]


def _extract_reason(raw: bytes) -> str | None:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    texts = []
    for el in root.iter():
        if _local(el.tag) == "text" and el.text and el.text.strip():
            texts.append(el.text.strip())
    return " | ".join(texts[:3]) if texts else None


def _find_text(root: ET.Element, path: str) -> str | None:
    parts = path.split("/")
    current = [root]
    for part in parts:
        nxt=[]
        for node in current:
            for child in node:
                if _local(child.tag) == part:
                    nxt.append(child)
        current=nxt
        if not current:
            return None
    text=current[0].text
    return text.strip() if text else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _period(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _duration(value: str) -> timedelta:
    if value == "P1D":
        return timedelta(days=1)
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value)
    if not m:
        raise RuntimeError(f"Tuntematon ENTSO-E resolution: {value}")
    return timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))
