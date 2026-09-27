from __future__ import annotations
import sqlite3

# price_forecast_scoring.score_price_forecasts() historically re-inserted a
# fresh row (with a new score_run_id) for every (forecast_run_id, target_time)
# pair on every single production run, for as long as that pair's actual price
# was known - because the primary key includes score_run_id (always unique per
# call), INSERT OR IGNORE never actually blocked the re-insert. This let
# price_forecast_scores balloon with many identical-value duplicate rows per
# pair (confirmed: the cloud DB had 243,970 raw rows for only 9,654 unique
# pairs after about 25 days of twice-daily runs). score_price_forecasts()
# itself was fixed to stop creating new duplicates going forward (it now
# skips pairs that are already scored); this module cleans up rows that
# already accumulated before that fix, and is also reused to de-duplicate an
# imported cloud export before merging it locally.

_LATEST_ROWID_SQL = """
    SELECT rowid FROM (
        SELECT rowid,
               ROW_NUMBER() OVER (
                   PARTITION BY forecast_run_id, target_time
                   ORDER BY created_at DESC, rowid DESC
               ) AS rn
        FROM price_forecast_scores
    ) WHERE rn = 1
"""


def dedupe_price_forecast_scores(conn: sqlite3.Connection) -> dict:
    """Keep exactly one price_forecast_scores row per (forecast_run_id,
    target_time) pair - the one with the newest created_at (ties broken by
    rowid) - and delete the rest. Safe to call repeatedly; a no-op once the
    table has no duplicates left."""
    before = conn.execute("SELECT COUNT(*) FROM price_forecast_scores").fetchone()[0]
    conn.execute(
        f"DELETE FROM price_forecast_scores WHERE rowid NOT IN ({_LATEST_ROWID_SQL})"
    )
    after = conn.execute("SELECT COUNT(*) FROM price_forecast_scores").fetchone()[0]
    conn.commit()
    return {"before": before, "after": after, "removed": before - after}


def latest_price_forecast_scores_rows(conn: sqlite3.Connection):
    """Yield one de-duplicated row (as a tuple, columns in table order) per
    (forecast_run_id, target_time) pair, without modifying the source
    database - used to export a clean copy from a read-only connection."""
    cur = conn.execute(
        f"""
        SELECT score_run_id, forecast_run_id, target_time, horizon_days,
               p50_eur_mwh, actual_eur_mwh, error_eur_mwh, abs_error_eur_mwh,
               baseline_eur_mwh, baseline_abs_error_eur_mwh, inside_p10_p90,
               created_at
        FROM price_forecast_scores
        WHERE rowid IN ({_LATEST_ROWID_SQL})
        """
    )
    yield from cur
