"""Issue origins are metadata, not a classification of the wall clock."""
from __future__ import annotations

SLOTS = {"morning", "afternoon"}


def migrate_issue_slots(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(price_forecast_runs)")}
    new = "issue_slot" not in columns
    if new:
        conn.execute("ALTER TABLE price_forecast_runs ADD COLUMN issue_slot TEXT")
    if "issue_slot_source" not in columns:
        conn.execute("ALTER TABLE price_forecast_runs ADD COLUMN issue_slot_source TEXT")
    # Old databases have no recorded origin. Infer only an intact, unambiguous
    # horizon signature, mark its provenance, and never use the execution hour.
    if new:
        for rid, lo, hi, count in conn.execute("""
            SELECT forecast_run_id, MIN(horizon_days), MAX(horizon_days),
                   COUNT(DISTINCT horizon_days)
            FROM price_forecasts_hourly GROUP BY forecast_run_id
        """).fetchall():
            slot = {(1, 11, 11): "morning", (2, 12, 11): "afternoon"}.get((lo, hi, count))
            conn.execute("""UPDATE price_forecast_runs SET issue_slot=?, issue_slot_source=?
                            WHERE forecast_run_id=? AND issue_slot IS NULL""",
                         (slot, "inferred_horizon" if slot else "unknown", rid))
    conn.execute("CREATE INDEX IF NOT EXISTS price_runs_slot ON price_forecast_runs(issue_slot,issue_time)")


def slot_metadata(row):
    """Do not turn missing legacy metadata into a seemingly observed origin."""
    slot = row.get("issue_slot")
    return (slot if slot in SLOTS else "unknown",
            row.get("issue_slot_source") or "unknown")
