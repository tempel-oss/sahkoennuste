"""Fetch source-backed Finnish generation unavailability notices from ENTSO-E.

This runs as a noncritical production step before HTML publication.
No API token or API error means no confirmed events, never a claim of no outages.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "market_events.json"
API = "https://web-api.tp.entsoe.eu/api"
FI_ZONE = "10YFI-1--------U"
TRANSPARENCY_LINK = "https://transparency.entsoe.eu/"
MAX_RESPONSE = 8_000_000


def _name(tag):
    return tag.rsplit("}", 1)[-1]


def _child(node, key):
    return next((x for x in node if _name(x.tag) == key), None)


def _value(node, key, default=""):
    item = _child(node, key)
    return (item.text or "").strip() if item is not None else default


def _time(value):
    if not value:
        raise ValueError("Missing time")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc)


def _interval(node):
    if node is None:
        return None
    candidate = next((x for x in node.iter()
                      if _name(x.tag) in ("timeInterval", "outage_Period.timeInterval",
                                          "unavailability_Time_Period.timeInterval")), None)
    if candidate is None:
        return None
    start = _value(candidate, "start")
    end = _value(candidate, "end")
    if start and end:
        return _time(start), _time(end)
    return None


def parse_notices(xml_bytes, collected_at, document_type):
    """Parse ENTSO-E outage XML, without claiming a quantified price impact."""
    if len(xml_bytes) > MAX_RESPONSE:
        raise ValueError("Response too large")
    root = ET.fromstring(xml_bytes)
    docs = ([root] if _name(root.tag) == "Unavailability_MarketDocument"
            else [n for n in root.iter() if _name(n.tag) == "Unavailability_MarketDocument"])
    if not docs and _name(root.tag) not in ("Acknowledgement_MarketDocument", "Acknowledgement_MarketDocument"):
        raise ValueError("Unexpected outage response")
    events = []
    for doc in docs:
        if _value(doc, "type") not in ("A80", "A77"):
            continue
        status = _child(doc, "docStatus")
        if status is not None and _value(status, "value") in ("A13", "A09"):
            continue  # withdrawn / cancelled
        reference = _value(doc, "mRID")
        created = _value(doc, "createdDateTime")
        series = [n for n in doc if _name(n.tag) == "TimeSeries"]
        for item in series:
            business = _value(item, "businessType")
            unit = next((n for n in item.iter()
                         if _name(n.tag) in ("registeredResource.name", "name")), None)
            unit_name = (unit.text or "").strip() if unit is not None else ""
            resource = next((n for n in item.iter()
                             if _name(n.tag) in ("registeredResource.mRID",)), None)
            unit_name = unit_name or (resource.text or "").strip() if resource is not None else unit_name
            period = _interval(item) or _interval(doc)
            if not period:
                continue
            start, end = period
            if end <= start:
                continue
            # Do not confuse remaining available power with outage magnitude.
            kind = "suunniteltu huolto" if business == "A53" else (
                "suunnittelematon käytettävyysmuutos" if business == "A54"
                else "käytettävyysilmoitus")
            title = ("Tuotantoyksikön " + kind + (": " + unit_name if unit_name else ""))
            note = next((n.text.strip() for n in item.iter()
                         if _name(n.tag) == "text" and n.text and n.text.strip()), "")
            events.append({
                "event_id": f"entsoe-{document_type}-{reference}-{_value(item, 'mRID')}-{start.isoformat()}",
                "title": title,
                "description": (note or "ENTSO-E:n julkaisema tuotantoyksikön käytettävyystieto.")[:350],
                "source_url": TRANSPARENCY_LINK,
                "source_name": "ENTSO-E Transparency Platform",
                "source_published_at_utc": created,
                "observed_at_utc": collected_at.isoformat(),
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "verification": "confirmed",
                "price_direction": "unknown",
                "category": "generation_unavailability",
                "business_type": business,
            })
    return events


def collect(now=None, token=None, opener=urlopen, output=OUTPUT):
    now = now or datetime.now(timezone.utc)
    token = token if token is not None else os.getenv("ENTSOE_API_TOKEN", "")
    if not token.strip():
        print("[MARKET_EVENTS] ENTSOE_API_TOKEN missing: no source-backed events")
        return {"status": "unavailable", "reason": "missing_token", "events": 0}

    start = now - timedelta(days=1)
    end = now + timedelta(days=12)
    results = []
    errors = []
    for document_type in ("A80", "A77"):
        params = {
            "securityToken": token.strip(),
            "documentType": document_type,
            "biddingZone_Domain": FI_ZONE,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        url = API + "?" + urlencode(params)
        try:
            req = Request(url, headers={"User-Agent": "Sahkoennuste-MarketEvents/1.0"})
            with opener(req, timeout=25) as response:
                raw = response.read(MAX_RESPONSE + 1)
            results.extend(parse_notices(raw, now, document_type))
        except (HTTPError, URLError, TimeoutError, ValueError, ET.ParseError, OSError) as exc:
            # Never print the request URL because it includes the security token.
            errors.append(document_type + ": " + type(exc).__name__)

    if errors:
        # No partial feed is published as if its coverage were complete.
        print("[MARKET_EVENTS] Source query degraded: " + ", ".join(errors))
        return {"status": "unavailable", "reason": "source_error", "events": 0}

    unique = {}
    for event in results:
        unique[event["event_id"]] = event
    items = sorted(unique.values(), key=lambda e: e["start_utc"])
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "schema_version": "1.0",
        "collector": "entsoe_generation_unavailability",
        "collected_at_utc": now.isoformat(),
        "scope": ["FI_generation_A80", "FI_production_A77"],
        "events": items,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(output)
    print(f"[MARKET_EVENTS] Confirmed notices: {len(items)}")
    return {"status": "ok", "events": len(items)}


if __name__ == "__main__":
    print(collect())
