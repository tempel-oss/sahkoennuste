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
BORDERS = {
    "SE1": "10Y1001A1001A44P",
    "SE3": "10Y1001A1001A46L",
    "EE": "10Y1001A1001A39I",
}


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


def parse_notices(xml_bytes, collected_at, document_type, border=None, flow=None):
    """Extract explicit dated outage notices; never infer capacity or price."""
    if len(xml_bytes) > MAX_RESPONSE:
        raise ValueError("Response too large")
    root = ET.fromstring(xml_bytes)
    docs = ([root] if _name(root.tag) == "Unavailability_MarketDocument"
            else [n for n in root.iter() if _name(n.tag) == "Unavailability_MarketDocument"])
    if not docs:
        if _name(root.tag) == "Acknowledgement_MarketDocument":
            reasons = [(_value(n, "code"), _value(n, "text"))
                       for n in root.iter() if _name(n.tag) == "Reason"]
            if any(code == "999" and "no matching data" in msg.lower()
                   for code, msg in reasons):
                return []
        raise ValueError("Unexpected outage response or source acknowledgement")
    events = []
    for doc in docs:
        if _value(doc, "type") != document_type:
            raise ValueError("Outage document type mismatch")
        status = _child(doc, "docStatus")
        if status is not None and _value(status, "value") in ("A13", "A09"):
            continue
        reference = _value(doc, "mRID")
        created = _value(doc, "createdDateTime")
        if not reference or not created:
            continue
        series = [n for n in doc if _name(n.tag) == "TimeSeries"] or [doc]
        for item in series:
            period = _interval(item) or _interval(doc)
            if not period:
                continue
            start, end = period
            if end <= start:
                continue
            business = _value(item, "businessType") or _value(doc, "businessType")
            kind = ("suunniteltu huolto" if business == "A53"
                    else "suunnittelematon käytettävyysmuutos" if business == "A54"
                    else "käytettävyysilmoitus")
            note = next((n.text.strip() for n in item.iter()
                         if _name(n.tag) == "text" and n.text and n.text.strip()), "")
            if document_type == "A78":
                category = "transmission_unavailability"
                label = border or "tuntematon"
                title = "Siirtoyhteyden " + kind + ": FI–" + label
                description = note or ("ENTSO-E:n julkaisema siirtoinfrastruktuurin "
                                       "käytettävyysilmoitus; kapasiteetin muutos "
                                       "ei ole vahvistettu.")
            else:
                category = "generation_unavailability"
                unit = next((n for n in item.iter()
                             if _name(n.tag) in ("registeredResource.name", "name")), None)
                unit_name = (unit.text or "").strip() if unit is not None else ""
                resource = next((n for n in item.iter()
                                 if _name(n.tag) == "registeredResource.mRID"), None)
                if not unit_name and resource is not None:
                    unit_name = (resource.text or "").strip()
                title = "Tuotantoyksikön " + kind + (": " + unit_name if unit_name else "")
                description = note or "ENTSO-E:n julkaisema tuotantoyksikön käytettävyystieto."
            series_id = _value(item, "mRID") if item is not doc else "document"
            events.append({
                "event_id": f"entsoe-{document_type}-{border or ''}-{flow or ''}-{reference}-{series_id}-{start.isoformat()}",
                "title": title[:160], "description": description[:350],
                "source_url": TRANSPARENCY_LINK,
                "source_name": "ENTSO-E Transparency Platform",
                "source_published_at_utc": created,
                "observed_at_utc": collected_at.isoformat(),
                "start_utc": start.isoformat(), "end_utc": end.isoformat(),
                "verification": "confirmed", "price_direction": "unknown",
                "category": category, "business_type": business,
                "border": border if document_type == "A78" else None,
            })
    return events


def collect(now=None, token=None, opener=urlopen, output=OUTPUT):
    now = now or datetime.now(timezone.utc)
    token = token if token is not None else os.getenv("ENTSOE_API_TOKEN", "")
    start, end = now - timedelta(days=1), now + timedelta(days=12)
    queries = [
        ("A80", {"biddingZone_Domain": FI_ZONE}, None),
        ("A77", {"biddingZone_Domain": FI_ZONE}, None),
    ]
    for label, neighbor in BORDERS.items():
        for outgoing, incoming in ((FI_ZONE, neighbor), (neighbor, FI_ZONE)):
            queries.append(("A78", {"out_Domain": outgoing, "in_Domain": incoming}, label))
    results, errors = [], []
    if token.strip():
        for doc_type, domains, border in queries:
            params = {"securityToken": token.strip(), "documentType": doc_type,
                      "periodStart": start.strftime("%Y%m%d%H%M"),
                      "periodEnd": end.strftime("%Y%m%d%H%M"), **domains}
            try:
                req = Request(API + "?" + urlencode(params),
                              headers={"User-Agent": "Sahkoennuste-MarketEvents/1.1"})
                with opener(req, timeout=25) as response:
                    raw = response.read(MAX_RESPONSE + 1)
                results.extend(parse_notices(raw, now, doc_type, border=border,
                                                    flow=domains.get("out_Domain", "")+"-"+domains.get("in_Domain", "")))
            except (HTTPError, URLError, TimeoutError, ValueError, ET.ParseError, OSError):
                # Do not log the request URL: it contains the API secret.
                errors.append(doc_type + ("_" + border if border else ""))
    else:
        errors.append("missing_token")
    unique = {event["event_id"]: event for event in results}
    items = sorted(unique.values(), key=lambda e: (e["start_utc"], e["event_id"]))
    status = "ok" if not errors else "partial" if results else "unavailable"
    snapshot = {
        "schema_version": "1.1", "collector": "entsoe_market_unavailability",
        "collected_at_utc": now.isoformat(), "status": status,
        "queries_total": len(queries),
        "queries_succeeded": len(queries)-len(errors) if token.strip() else 0,
        "failed_scopes": errors,
        "scope": ["FI_generation_A80", "FI_production_A77",
                  "FI_SE1_A78", "FI_SE3_A78", "FI_EE_A78"],
        "events": items,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(output)
    print(f"[MARKET_EVENTS] status={status} events={len(items)} "
          f"queries={snapshot['queries_succeeded']}/{len(queries)}")
    return {"status": status, "events": len(items),
            "queries_succeeded": snapshot["queries_succeeded"],
            "queries_total": len(queries)}


if __name__ == "__main__":
    print(collect())
