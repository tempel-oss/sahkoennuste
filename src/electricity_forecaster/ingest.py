from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import uuid

from .config import DATASET_CONFIG, RAW_DIR
from .db import connect, init_db
from .fingrid import FingridClient


def load_specs():
    return json.loads(DATASET_CONFIG.read_text(encoding="utf-8"))["datasets"]


def ingest(selected: list[str] | None = None) -> dict[str, int]:
    init_db()
    specs = load_specs()
    if selected:
        unknown = [x for x in selected if x not in specs]
        if unknown:
            raise RuntimeError("Tuntematon dataset: " + ", ".join(unknown))
        specs = {k: specs[k] for k in selected}

    client = FingridClient()
    now = datetime.now(timezone.utc)
    issue_time = now.replace(microsecond=0).isoformat()
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    result = {}

    with connect() as conn:
        conn.execute("INSERT INTO forecast_runs(run_id, issue_time, source, created_at) VALUES (?,?,?,?)",
                     (run_id, issue_time, "fingrid", issue_time))
        for name, spec in specs.items():
            is_forecast = bool(spec["is_forecast"])
            start = now - timedelta(hours=2 if is_forecast else 48)
            end = now + timedelta(hours=96 if is_forecast else 1)
            status = "ok"
            message = None
            count = 0
            try:
                payload, rows = client.fetch(int(spec["id"]), start, end)
                _archive_raw(run_id, name, int(spec["id"]), payload)
                if is_forecast:
                    conn.executemany(
                        "INSERT OR REPLACE INTO forecasts(run_id,dataset_id,valid_time,end_time,metric,value,unit,source) VALUES (?,?,?,?,?,?,?,?)",
                        [(run_id, int(spec["id"]), r.start_time, r.end_time, spec["metric"], r.value, spec["unit"], f"fingrid:{spec['id']}") for r in rows]
                    )
                else:
                    conn.executemany(
                        "INSERT OR REPLACE INTO actuals(dataset_id,valid_time,end_time,metric,value,unit,source,ingested_at) VALUES (?,?,?,?,?,?,?,?)",
                        [(int(spec["id"]), r.start_time, r.end_time, spec["metric"], r.value, spec["unit"], f"fingrid:{spec['id']}", issue_time) for r in rows]
                    )
                count = len(rows)
            except Exception as exc:
                status = "error"
                message = str(exc)
            conn.execute(
                "INSERT INTO ingestion_log(run_id,dataset_id,dataset_name,fetched_rows,status,message,created_at) VALUES (?,?,?,?,?,?,?)",
                (run_id, int(spec["id"]), name, count, status, message, issue_time)
            )
            conn.commit()
            result[name] = count if status == "ok" else -1
            if status == "error":
                print(f"[VIRHE] {name}: {message}")
            else:
                print(f"[OK] {name}: {count} rivia")
    return result


def _archive_raw(run_id: str, name: str, dataset_id: int, payload) -> None:
    folder = RAW_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}_{dataset_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
