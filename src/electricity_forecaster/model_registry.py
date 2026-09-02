
from __future__ import annotations
from datetime import datetime, timezone
import sqlite3
from .db import connect, init_db

REGISTRY_SCHEMA = '''
CREATE TABLE IF NOT EXISTS model_registry (
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    promoted_at TEXT,
    notes TEXT,
    PRIMARY KEY(model_name,model_version)
);
'''

def ensure_registry():
    init_db()
    with connect() as c:
        c.executescript(REGISTRY_SCHEMA)
        row=c.execute("SELECT 1 FROM model_registry WHERE role='champion' AND status='active' LIMIT 1").fetchone()
        if not row:
            c.execute('''INSERT OR REPLACE INTO model_registry
              (model_name,model_version,role,status,promoted_at,notes)
              VALUES(?,?,?,?,?,?)''',
              ("fundamental_baseline","0.7.1","champion","active",
               datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
               "Production baseline. Not a trained ML model."))

def model_status():
    ensure_registry()
    with connect() as c:
        c.row_factory=sqlite3.Row
        champ=c.execute('''SELECT model_name,model_version,role,status,promoted_at,notes
                           FROM model_registry
                           WHERE role='champion' AND status='active'
                           ORDER BY promoted_at DESC LIMIT 1''').fetchone()
        score_count=c.execute("SELECT COUNT(*) FROM price_forecast_scores").fetchone()[0]
        run_count=c.execute("SELECT COUNT(DISTINCT forecast_run_id) FROM price_forecast_scores").fetchone()[0]
        avg=c.execute('''SELECT AVG(abs_error_eur_mwh),AVG(baseline_abs_error_eur_mwh),
                               AVG(inside_p10_p90)
                        FROM price_forecast_scores''').fetchone()
        mae=float(avg[0]) if avg and avg[0] is not None else None
        baseline_mae=float(avg[1]) if avg and avg[1] is not None else None
        coverage=float(avg[2]) if avg and avg[2] is not None else None
        ready = score_count >= 1000 and run_count >= 20
        return {
            "champion":{
                "name":champ["model_name"] if champ else None,
                "version":champ["model_version"] if champ else None,
                "trained_ml":False if champ and champ["model_name"]=="fundamental_baseline" else None,
                "notes":champ["notes"] if champ else ""
            },
            "evaluation":{
                "scored_hours":int(score_count),
                "scored_forecast_runs":int(run_count),
                "mae_eur_mwh":round(mae,2) if mae is not None else None,
                "baseline_mae_eur_mwh":round(baseline_mae,2) if baseline_mae is not None else None,
                "p10_p90_coverage":round(coverage,3) if coverage is not None else None
            },
            "challenger_training_ready":bool(ready),
            "training_gate":"1000 scored hours and 20 scored forecast runs",
            "promotion_policy":"Challenger is never promoted automatically without walk-forward validation."
        }
