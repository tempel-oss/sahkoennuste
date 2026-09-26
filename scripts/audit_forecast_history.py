"""Audit recent forecast issue-slot coverage from the SQLite history.

The audit is intentionally warning-only by default: a missing historical slot must
not prevent the current production forecast from being published. Use --strict to
return a non-zero exit code when gaps are found.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo("Europe/Helsinki")
UTC = ZoneInfo("UTC")
EXPECTED = {"morning": (6, 15), "afternoon": (16, 15)}


def _candidate_tables(conn: sqlite3.Connection):
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        time_col = next((c for c in ("forecast_issue_time", "issue_time", "issue_time_utc", "created_at") if c in cols), None)
        slot_col = next((c for c in ("issue_slot", "slot") if c in cols), None)
        if time_col:
            yield table, time_col, slot_col


def _parse_time(value):
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(HELSINKI)


def collect_slots(db: Path, days: int):
    cutoff = datetime.now(HELSINKI) - timedelta(days=days + 1)
    found = set()
    inspected = []
    with sqlite3.connect(db) as conn:
        for table, time_col, slot_col in _candidate_tables(conn):
            inspected.append(table)
            select = f'SELECT "{time_col}"' + (f', "{slot_col}"' if slot_col else '') + f' FROM "{table}"'
            try:
                rows = conn.execute(select)
            except sqlite3.DatabaseError:
                continue
            for row in rows:
                dt = _parse_time(row[0])
                if not dt or dt < cutoff:
                    continue
                slot = str(row[1]).lower() if slot_col and row[1] is not None else None
                if slot not in EXPECTED:
                    if dt.hour < 12:
                        slot = "morning"
                    elif dt.hour >= 12:
                        slot = "afternoon"
                found.add((dt.date(), slot))
    return found, inspected


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    db = root / "data/electricity_forecaster.sqlite3"
    if not db.exists():
        print(f"::warning::Forecast history audit skipped: SQLite database not found: {db}")
        return 0

    found, tables = collect_slots(db, args.days)
    today = datetime.now(HELSINKI).date()
    # Audit complete prior days only; today's afternoon slot may not yet be due.
    dates = [today - timedelta(days=i) for i in range(1, args.days + 1)]
    missing = [(d, slot) for d in sorted(dates) for slot in EXPECTED if (d, slot) not in found]

    print(f"[AUDIT] inspected_tables={','.join(tables) or 'none'} days={args.days} found_slots={len(found)} expected={len(dates)*2}")
    if missing:
        text = ", ".join(f"{d.isoformat()} {slot}" for d, slot in missing)
        print(f"::warning::Forecast history gaps detected ({len(missing)}): {text}")
        return 1 if args.strict else 0
    print(f"[OK] Forecast history complete for previous {args.days} days (morning + afternoon).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
