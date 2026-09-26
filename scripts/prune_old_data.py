"""Bound the unbounded growth of data/raw/**, logs/*.log, and a set of SQLite
tables that are provably only ever read for their *latest* run (never scanned
back through history by anything in this codebase).

Every production run (twice daily via GitHub Actions, plus any local runs) adds:
  - one timestamped run folder per Fingrid/ENTSO-E fetch under data/raw/fingrid/
    and data/raw/entsoe/ (see ingest.py, entsoe_ingest.py, weather.py's
    _archive()) and one timestamped *.json file per day under data/raw/nordpool/
    (see price_ingest.py) - all raw, write-once copies of API responses kept for
    audit/debugging and never read back by anything,
  - one logs/production_<timestamp>.log file (see scripts/production_runner.py),
  - one row per run in a couple of SQLite audit-log tables (ingestion_log,
    entsoe_ingestion_log),
  - one run's worth of rows in weather_series, features_hourly, entsoe_series,
    forecast_diagnostics, forecast_changes and uncertainty_components - all of
    which are queried elsewhere in this codebase ONLY by an explicit
    run_id/feature_run_id filter for the latest run, or via a plain
    COUNT(*)/MAX(...) in scripts/show_status.py. Grep the codebase yourself
    before extending this list: `grep -rn "FROM <table>"`.

None of this shrinks on its own. As of writing, data/raw/** already holds over a
thousand files (~78 MB) and the SQLite database is >250 MB. This script deletes
anything older than a retention window (default 60 days for files, 180 days for
the SQLite audit-log rows, 90 days for the SQLite series/diagnostics tables
above) and is deliberately conservative about what it touches:

  - It never deletes data/raw/*.parquet - those are the aggregated inputs the
    pipeline actually reads, one level above the per-run folders/files this
    script prunes.
  - actuals, forecasts (+forecast_runs), market_prices, price_forecasts_hourly,
    price_forecasts_daily, price_forecast_runs, price_forecast_scores and
    forecast_errors get a much longer, separately-configurable window
    (HISTORY_RETENTION/CASCADE_RETENTION below, default 730 days = ~2 years).
    These are NOT simple audit logs: error_scoring.py and price_forecast_scoring.py
    each re-scan the FULL history of one or more of these tables on every run (no
    WHERE clause bounding how far back they look) to score forecast accuracy, and
    forecast_quality.py/model_registry.py read the full history of
    price_forecast_scores for the ML-training-readiness gates ("1000 scored
    hours + 20 scored forecast runs" etc.) and the walk-forward baseline report.
    2 years is a deliberate choice (confirmed with the project owner, see
    loydokset_ja_korjaukset.md in the project) - it is far beyond what those
    gates or a realistic quality-trend lookback need (scoring only ever needs
    the last few days/weeks once an actual value lands), while still bounding
    growth long-term. Use --history-days to override.

Usage:
    python scripts/prune_old_data.py                  # apply with default windows
    python scripts/prune_old_data.py --dry-run         # print what would be removed
    python scripts/prune_old_data.py --raw-days 30 --log-days 30 --db-days 90 --series-days 90 --history-days 365
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from electricity_forecaster.config import ROOT, RAW_DIR, ENTSOE_RAW_DIR, DB_PATH  # noqa: E402

LOG_DIR = ROOT / "logs"
NORDPOOL_RAW_DIR = ROOT / "data" / "raw" / "nordpool"

# Fingrid/ENTSO-E archive one run per subfolder; Nord Pool archives one run per
# flat *.json file directly under its raw dir (see price_ingest.py).
RAW_DIR_ROOTS = [RAW_DIR, ENTSOE_RAW_DIR]
RAW_FILE_ROOTS = [NORDPOOL_RAW_DIR]

# Run folders/files are named "<YYYYMMDDTHHMMSSZ>-<suffix>[...]" or, for
# ENTSO-E, "<YYYYMMDDTHHMMSSZ>-entsoe-<suffix>".
_RUN_TS_RE = re.compile(r"^(\d{8}T\d{6}Z)(?:-|_)")

# Table -> (UTC-ISO date column, default retention in days). Only append-only
# audit-log tables belong here - see the docstring above.
DB_RETENTION: dict[str, tuple[str, int]] = {
    "ingestion_log": ("created_at", 180),
    "entsoe_ingestion_log": ("created_at", 180),
}

# Table -> (date column, default retention in days). Only tables verified (by
# grepping every "FROM <table>" in this codebase) to be read solely via a
# specific-run filter or a plain COUNT/MAX diagnostic belong here - see the
# module docstring for the reasoning and the explicit list of tables that were
# deliberately left OUT because something scans their full history.
SERIES_RETENTION: dict[str, tuple[str, int]] = {
    "weather_series": ("valid_time", 90),
    "features_hourly": ("valid_time", 90),
    "forecast_diagnostics": ("target_date", 90),
    "forecast_changes": ("target_date", 90),
    "uncertainty_components": ("target_date", 90),
}

# Parent table -> (date column, default retention in days). Deleting old rows
# from the PARENT table and relying on the schema's existing
# "ON DELETE CASCADE" to remove the matching child rows - this only lists
# parent/child pairs where db.py's schema actually declares that cascade.
# Split into the same two families/windows as the direct-column tables above
# and below: entsoe_runs follows --series-days (cascades to entsoe_series,
# which is itself only ever read for the latest run), forecast_runs follows
# --history-days (cascades to forecasts, part of the error-scoring history -
# see HISTORY_RETENTION below).
CASCADE_SERIES_RETENTION: dict[str, tuple[str, int]] = {
    "entsoe_runs": ("created_at", 90),  # cascades to entsoe_series
}
CASCADE_HISTORY_RETENTION: dict[str, tuple[str, int]] = {
    "forecast_runs": ("created_at", 730),  # cascades to forecasts
}

# Table -> (date column, default retention in days). The long-lived
# forecast-accuracy/model-quality history - see the module docstring for why
# this gets its own, much longer, separately-configurable window instead of
# SERIES_RETENTION's. None of these have a declared foreign key to another
# table in db.py's schema (checked directly against SCHEMA in db.py), so each
# is pruned by its own date column with a plain DELETE - no cascade involved.
HISTORY_RETENTION: dict[str, tuple[str, int]] = {
    "actuals": ("ingested_at", 730),
    "market_prices": ("valid_time", 730),
    "price_forecasts_hourly": ("target_time", 730),
    "price_forecasts_daily": ("target_date", 730),
    "price_forecast_runs": ("issue_time", 730),
    "price_forecast_scores": ("created_at", 730),
    "forecast_errors": ("created_at", 730),
}


def _parse_run_timestamp(name: str) -> datetime | None:
    m = _RUN_TS_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def find_old_raw_entries(raw_days: int, now: datetime) -> list[Path]:
    cutoff = now - timedelta(days=raw_days)
    old: list[Path] = []
    for root in RAW_DIR_ROOTS:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue  # never touch a flat file sitting directly in one of these roots
            ts = _parse_run_timestamp(child.name)
            if ts is not None and ts < cutoff:
                old.append(child)
    for root in RAW_FILE_ROOTS:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_file():
                continue
            ts = _parse_run_timestamp(child.name)
            if ts is not None and ts < cutoff:
                old.append(child)
    return old


def find_old_logs(log_days: int, now: datetime) -> list[Path]:
    cutoff = now - timedelta(days=log_days)
    if not LOG_DIR.exists():
        return []
    old = []
    for f in LOG_DIR.glob("production_*.log"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            old.append(f)
    return old


def _path_size(p: Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _prune_rows(conn: sqlite3.Connection, table: str, col: str, days: int, dry_run: bool) -> int:
    cutoff = _cutoff_iso(days)
    row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} < ?", (cutoff,)).fetchone()
    n = row[0] if row else 0
    if not dry_run and n:
        conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
    return n


def prune_db_tables(db_days: int | None, series_days: int | None, history_days: int | None,
                     dry_run: bool) -> dict[str, int]:
    """Apply DB_RETENTION (pure audit logs, --db-days), SERIES_RETENTION +
    CASCADE_SERIES_RETENTION (per-run tables verified to only be read for the
    latest run, --series-days), and HISTORY_RETENTION + CASCADE_HISTORY_RETENTION
    (the longer-lived forecast-accuracy/model-quality history, --history-days).
    A CASCADE_* entry deletes old rows from the parent table and relies on the
    schema's own ON DELETE CASCADE for the matching children. Returns
    table -> rows matched (deleted unless dry_run); for a CASCADE_* entry the
    count is against the parent table."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    try:
        # Cascades only fire with this pragma on - set it explicitly rather than
        # relying on any caller-side default.
        conn.execute("PRAGMA foreign_keys=ON")
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts: dict[str, int] = {}
        any_deleted = False
        for retention, days_arg in (
            (DB_RETENTION, db_days),
            (SERIES_RETENTION, series_days),
            (CASCADE_SERIES_RETENTION, series_days),
            (HISTORY_RETENTION, history_days),
            (CASCADE_HISTORY_RETENTION, history_days),
        ):
            for table, (col, default_days) in retention.items():
                if table not in existing:
                    continue
                days = days_arg if days_arg is not None else default_days
                n = _prune_rows(conn, table, col, days, dry_run)
                counts[table] = n
                if n and not dry_run:
                    any_deleted = True
        if any_deleted:
            conn.commit()
            conn.execute("VACUUM")
        return counts
    finally:
        conn.close()


def prune_default() -> dict:
    """Convenience entry point for scripts/production_runner.py: prune with the
    default retention windows (see the module docstring) and return a short
    summary dict instead of printing to stdout."""
    now = datetime.now(timezone.utc)
    raw_days, log_days, db_days, series_days, history_days = 60, 60, 180, 90, 730

    old_raw = find_old_raw_entries(raw_days, now)
    raw_bytes = sum(_path_size(e) for e in old_raw)
    for e in old_raw:
        if e.is_dir():
            shutil.rmtree(e, ignore_errors=True)
        else:
            e.unlink(missing_ok=True)

    old_logs = find_old_logs(log_days, now)
    log_bytes = sum(_path_size(f) for f in old_logs)
    for f in old_logs:
        f.unlink(missing_ok=True)

    db_counts = prune_db_tables(db_days, series_days, history_days, dry_run=False)

    return {
        "raw_removed": len(old_raw), "raw_mb": round(raw_bytes / 1e6, 1),
        "logs_removed": len(old_logs), "logs_mb": round(log_bytes / 1e6, 1),
        "db_rows_removed": db_counts,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Poista vanhat data/raw-ajokohtaiset arkistot, tuotantolokit ja "
                     "SQLite-taulujen rivit (ks. moduulin docstring: mita TAULUJA "
                     "tama koskee ja miksi).")
    p.add_argument("--raw-days", type=int, default=60,
                    help="Sailyta data/raw-ajokansiot/tiedostot uudempina kuin nain monta vrk (oletus: 60)")
    p.add_argument("--log-days", type=int, default=60,
                    help="Sailyta logs/production_*.log-tiedostot uudempina kuin nain monta vrk (oletus: 60)")
    p.add_argument("--db-days", type=int, default=180,
                    help="Sailyta audit-lokitaulujen (ingestion_log, entsoe_ingestion_log) rivit "
                         "uudempina kuin nain monta vrk (oletus: 180)")
    p.add_argument("--series-days", type=int, default=90,
                    help="Sailyta vain-viimeisinta-ajoa-luettavien taulujen "
                         "(weather_series, features_hourly, entsoe_series/entsoe_runs, "
                         "forecast_diagnostics, forecast_changes, uncertainty_components) "
                         "rivit uudempina kuin nain monta vrk (oletus: 90)")
    p.add_argument("--history-days", type=int, default=730,
                    help="Sailyta ennustetarkkuus-/laatuhistorian taulujen "
                         "(actuals, forecasts/forecast_runs, market_prices, "
                         "price_forecasts_hourly/daily, price_forecast_runs, "
                         "price_forecast_scores, forecast_errors) rivit uudempina kuin "
                         "nain monta vrk (oletus: 730 = n. 2 vuotta - sovittu tuoteomistajan "
                         "kanssa, ks. loydokset_ja_korjaukset.md)")
    p.add_argument("--dry-run", action="store_true",
                    help="Tulosta mita poistettaisiin, mutta ala poista mitaan")
    args = p.parse_args()

    now = datetime.now(timezone.utc)

    old_raw = find_old_raw_entries(args.raw_days, now)
    raw_bytes = sum(_path_size(e) for e in old_raw)
    print(f"[RAW] {len(old_raw)} ajokohtaista arkistoa data/raw-hakemistoissa yli "
          f"{args.raw_days} vrk vanhoja ({raw_bytes/1e6:.1f} MB).")
    if not args.dry_run:
        for e in old_raw:
            if e.is_dir():
                shutil.rmtree(e, ignore_errors=True)
            else:
                e.unlink(missing_ok=True)
        if old_raw:
            print("[RAW] Poistettu.")

    old_logs = find_old_logs(args.log_days, now)
    log_bytes = sum(_path_size(f) for f in old_logs)
    print(f"[LOGS] {len(old_logs)} tuotantolokia yli {args.log_days} vrk vanhoja ({log_bytes/1e6:.1f} MB).")
    if not args.dry_run:
        for f in old_logs:
            f.unlink(missing_ok=True)
        if old_logs:
            print("[LOGS] Poistettu.")

    db_counts = prune_db_tables(args.db_days, args.series_days, args.history_days, args.dry_run)
    for table, n in db_counts.items():
        if table in DB_RETENTION:
            days = args.db_days
        elif table in HISTORY_RETENTION or table in CASCADE_HISTORY_RETENTION:
            days = args.history_days
        else:
            days = args.series_days
        suffix = " (--dry-run, ei poistettu)" if args.dry_run else " poistettu."
        note = " (kaskadi lapsitauluihin)" if table in CASCADE_SERIES_RETENTION or table in CASCADE_HISTORY_RETENTION else ""
        print(f"[DB] {table}{note}: {n} riv(ia) yli {days} vrk vanhoja{suffix}")

    if args.dry_run:
        print("\n--dry-run: mitaan ei poistettu oikeasti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
