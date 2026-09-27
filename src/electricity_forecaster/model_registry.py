
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from .db import connect, init_db
from .config import ROOT

# The residual Challenger (see README_residual_challenger_v1.md) is trained
# locally with `train_residual_challenger_v1.py`. Its trained model file and
# the two small JSON reports below are the only Challenger artifacts tracked
# in git (see .gitignore) - everything else under data/ stays local-only.
# Committing them means the *same* files are present whether this code runs
# on the local Windows machine or inside the cloud GitHub Actions pipeline,
# so register_challenger_from_artifact() below can register a real,
# consistent Challenger evaluation into whichever SQLite database is live in
# that environment (the local DB and the cloud pipeline's cached DB are
# otherwise entirely separate - see loydokset_ja_korjaukset.md).
CHALLENGER_ARTIFACT_DIR = ROOT / "data" / "ml" / "challenger_residual_hgb_v1"

# Below this many walk-forward-evaluated hours, a skill-percentage number is
# treated as too thin to be statistically meaningful and is flagged as such
# in model_status() / the diagnostics page, rather than presented as a firm
# verdict either way.
CHALLENGER_THIN_SAMPLE_HOURS = 200

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

def register_challenger_from_artifact(artifact_dir=None):
    """Registers the residual Challenger's offline walk-forward evaluation
    (data/ml/challenger_residual_hgb_v1/{metadata,report}.json) into
    model_registry, so model_status() can report real Challenger numbers
    instead of only a training-readiness pill.

    This never changes which model produces the published forecast and
    never loads model.joblib or runs any inference - it only reads two
    small, git-tracked JSON files and records what they already say. Safe
    to call on every run, in both the local and cloud pipelines: if the
    artifact is missing (e.g. an older checkout, or before it has ever been
    trained), it does nothing and returns a short status string instead of
    raising, since this step must never be allowed to break a forecast run.
    """
    d = Path(artifact_dir) if artifact_dir is not None else CHALLENGER_ARTIFACT_DIR
    meta_path = d / "metadata.json"
    report_path = d / "report.json"
    if not meta_path.is_file() or not report_path.is_file():
        return f"ei artefaktia ({d})"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return f"artefaktin luku epäonnistui: {type(e).__name__}: {e}"

    overall = ((report.get("walk_forward") or {}).get("overall")) or {}
    data_range = report.get("data") or {}
    notes = json.dumps({
        "trained_at_utc": meta.get("trained_at_utc"),
        "algorithm": (report.get("challenger") or {}).get("algorithm"),
        "walk_forward_n": overall.get("n"),
        "walk_forward_champion_mae_eur_mwh": (overall.get("champion") or {}).get("mae_eur_mwh"),
        "walk_forward_challenger_mae_eur_mwh": (overall.get("challenger") or {}).get("mae_eur_mwh"),
        "walk_forward_mae_skill_pct": overall.get("mae_skill_pct"),
        "walk_forward_issue_start": data_range.get("issue_start"),
        "walk_forward_issue_end": data_range.get("issue_end"),
    }, ensure_ascii=False)

    model_name = meta.get("model_name", "residual_hgb")
    model_version = meta.get("model_version", "0")
    status = meta.get("status", "shadow_only")

    init_db()
    with connect() as c:
        c.executescript(REGISTRY_SCHEMA)
        c.execute('''INSERT OR REPLACE INTO model_registry
          (model_name,model_version,role,status,promoted_at,notes)
          VALUES(?,?,?,?,?,?)''',
          (model_name, model_version, "challenger", status,
           meta.get("trained_at_utc"), notes))
    return f"{model_name} {model_version} ({status}) rekisteröity"

def model_status():
    ensure_registry()
    with connect() as c:
        c.row_factory=sqlite3.Row
        champ=c.execute('''SELECT model_name,model_version,role,status,promoted_at,notes
                           FROM model_registry
                           WHERE role='champion' AND status='active'
                           ORDER BY promoted_at DESC LIMIT 1''').fetchone()
        chall=c.execute('''SELECT model_name,model_version,role,status,promoted_at,notes
                           FROM model_registry
                           WHERE role='challenger'
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

        challenger_info=None
        if chall:
            try:
                chall_notes=json.loads(chall["notes"] or "{}")
            except json.JSONDecodeError:
                chall_notes={}
            n=chall_notes.get("walk_forward_n")
            skill=chall_notes.get("walk_forward_mae_skill_pct")
            thin=bool(n is None or n < CHALLENGER_THIN_SAMPLE_HOURS)
            challenger_info={
                "name":chall["model_name"],
                "version":chall["model_version"],
                "status":chall["status"],
                "trained_at_utc":chall["promoted_at"],
                "walk_forward_n":n,
                "walk_forward_champion_mae_eur_mwh":chall_notes.get("walk_forward_champion_mae_eur_mwh"),
                "walk_forward_challenger_mae_eur_mwh":chall_notes.get("walk_forward_challenger_mae_eur_mwh"),
                "walk_forward_mae_skill_pct":skill,
                "walk_forward_issue_start":chall_notes.get("walk_forward_issue_start"),
                "walk_forward_issue_end":chall_notes.get("walk_forward_issue_end"),
                "sample_is_thin":thin,
                "outperforms_champion":bool(skill is not None and skill > 0),
            }

        return {
            "champion":{
                "name":champ["model_name"] if champ else None,
                "version":champ["model_version"] if champ else None,
                "trained_ml":False if champ and champ["model_name"]=="fundamental_baseline" else None,
                "notes":champ["notes"] if champ else ""
            },
            "challenger":challenger_info,
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
