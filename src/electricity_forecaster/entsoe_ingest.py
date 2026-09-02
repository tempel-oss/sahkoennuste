from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json, uuid

from .config import AREA_CONFIG, ENTSOE_RAW_DIR
from .db import connect, init_db
from .entsoe import EntsoeClient


def load_areas() -> dict[str, str]:
    return json.loads(AREA_CONFIG.read_text(encoding="utf-8"))


def ingest() -> dict[str, int]:
    init_db()
    areas = load_areas()
    client = EntsoeClient()
    now = datetime.now(timezone.utc)
    issue_time = now.replace(microsecond=0).isoformat()
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-entsoe-" + uuid.uuid4().hex[:8]
    start_prices = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_prices = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    result: dict[str, int] = {}

    with connect() as conn:
        conn.execute("INSERT INTO entsoe_runs(run_id, issue_time, created_at) VALUES (?,?,?)", (run_id, issue_time, issue_time))
        # Day-ahead prices for Finland and surrounding price areas.
        for area, eic in areas.items():
            key = f"price_{area}"
            _run_one(conn, client, run_id, issue_time, key, area,
                     lambda eic=eic: client.day_ahead_prices(eic, start_prices, end_prices),
                     metric="day_ahead_price_eur_mwh", document_type="A44", process_type=None, result=result)

        # Finland load actual and day-ahead load forecast.
        fi = areas["FI"]
        load_start = now - timedelta(days=2)
        load_end = now + timedelta(days=3)
        _run_one(conn, client, run_id, issue_time, "fi_load_actual", "FI",
                 lambda: client.total_load(fi, load_start, now, "A16"),
                 metric="total_load_actual_mw", document_type="A65", process_type="A16", result=result)
        _run_one(conn, client, run_id, issue_time, "fi_load_day_ahead", "FI",
                 lambda: client.total_load(fi, now, load_end, "A01"),
                 metric="total_load_day_ahead_forecast_mw", document_type="A65", process_type="A01", result=result)

        # Finland day-ahead wind and solar forecasts. B19=wind onshore, B18=wind offshore, B16=solar.
        for psr, label, metric in [
            ("B19", "fi_wind_onshore_da", "wind_onshore_day_ahead_forecast_mw"),
            ("B18", "fi_wind_offshore_da", "wind_offshore_day_ahead_forecast_mw"),
            ("B16", "fi_solar_da", "solar_day_ahead_forecast_mw"),
        ]:
            _run_one(conn, client, run_id, issue_time, label, "FI",
                     lambda psr=psr: client.wind_solar_forecast(fi, now, load_end, psr),
                     metric=metric, document_type="A69", process_type="A01", result=result, psr_type=psr,
                     allow_no_data=True)
        conn.commit()
    return result


def _run_one(conn, client, run_id, issue_time, series_name, area, fetch_fn, *, metric, document_type, process_type, result, psr_type="", allow_no_data=False):
    status="ok"; message=None; count=0
    try:
        raw, points = fetch_fn()
        _archive_raw(run_id, series_name, raw)
        rows=[]
        for p in points:
            rows.append((run_id, series_name, area, document_type, process_type, p.psr_type or psr_type or "", p.start_time, p.end_time, metric, p.value, p.unit or "", "entsoe"))
        conn.executemany(
            "INSERT OR REPLACE INTO entsoe_series(run_id,series_name,area,document_type,process_type,psr_type,valid_time,end_time,metric,value,unit,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
        count=len(rows)
    except Exception as exc:
        text=str(exc)
        if allow_no_data and ("ei palauttanut dataa" in text or "no matching data" in text.lower()):
            status="no_data"; message=text; count=0
        else:
            status="error"; message=text; count=-1
    conn.execute("INSERT INTO entsoe_ingestion_log(run_id,series_name,area,fetched_rows,status,message,created_at) VALUES (?,?,?,?,?,?,?)",
                 (run_id, series_name, area, max(count,0), status, message, issue_time))
    conn.commit()
    result[series_name]=count
    if status == "ok": print(f"[OK] {series_name}: {count} rivia")
    elif status == "no_data": print(f"[EI DATAA] {series_name}: {message}")
    else: print(f"[VIRHE] {series_name}: {message}")


def _archive_raw(run_id: str, name: str, raw: bytes) -> None:
    folder = ENTSOE_RAW_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.xml").write_bytes(raw)
