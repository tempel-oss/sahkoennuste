"""Append-only prospective evidence. No hindsight backfill or auto-promotion.

Only the capture function imports ML dependencies; summary/publication works
without them. New forecasts cannot overwrite an existing recorded origin.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import statistics

SCHEMA = '''
CREATE TABLE IF NOT EXISTS shadow_runs (
 forecast_run_id TEXT PRIMARY KEY, issue_time TEXT, issue_slot TEXT,
 issue_slot_source TEXT, recorded_at_utc TEXT NOT NULL, status TEXT NOT NULL,
 candidate TEXT, model_id TEXT, spec_sha256 TEXT, forecast_count INTEGER NOT NULL DEFAULT 0,
 skipped_known_price INTEGER NOT NULL DEFAULT 0, message TEXT
);
CREATE TABLE IF NOT EXISTS shadow_models (
 model_id TEXT PRIMARY KEY, candidate TEXT NOT NULL, fitted_at_utc TEXT NOT NULL,
 training_cutoff_utc TEXT NOT NULL, training_rows INTEGER NOT NULL, training_runs INTEGER NOT NULL,
 train_max_actual_available_at TEXT NOT NULL, training_sha256 TEXT NOT NULL,
 spec_json TEXT NOT NULL, sklearn_version TEXT NOT NULL, artifact BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_forecasts (
 forecast_run_id TEXT NOT NULL, target_time TEXT NOT NULL, horizon_days INTEGER NOT NULL,
 model_id TEXT NOT NULL, champion_p50_eur_mwh REAL NOT NULL,
 challenger_p50_eur_mwh REAL NOT NULL, correction_eur_mwh REAL NOT NULL,
 recorded_at_utc TEXT NOT NULL,
 PRIMARY KEY(forecast_run_id,target_time)
);
CREATE TABLE IF NOT EXISTS shadow_scores (
 forecast_run_id TEXT NOT NULL, target_time TEXT NOT NULL, actual_eur_mwh REAL NOT NULL,
 first_published_at TEXT NOT NULL, actual_available_at TEXT NOT NULL,
 champion_error_eur_mwh REAL NOT NULL, challenger_error_eur_mwh REAL NOT NULL,
 scored_at_utc TEXT NOT NULL, PRIMARY KEY(forecast_run_id,target_time)
);
CREATE INDEX IF NOT EXISTS shadow_target ON shadow_forecasts(target_time);
'''


def ensure_shadow_schema(conn):
    conn.executescript(SCHEMA)


def _now(now=None):
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return dt.astimezone(timezone.utc)


def _run_row(conn, run_id):
    row = conn.execute('SELECT * FROM price_forecast_runs WHERE forecast_run_id=?', (run_id,)).fetchone()
    if row is None:
        raise ValueError('Champion origin not found')
    keys = [r[1] for r in conn.execute('PRAGMA table_info(price_forecast_runs)')]
    return dict(zip(keys, row))


def capture(conn, run_id, spec, now=None):
    """Injectable connection/time for tests; runtime always uses the actual clock."""
    from . import challenger_v2 as ml
    import joblib
    import pandas as pd
    import sklearn
    ensure_shadow_schema(conn)
    existing = conn.execute('SELECT status,forecast_count FROM shadow_runs WHERE forecast_run_id=?', (run_id,)).fetchone()
    if existing:
        return {'status': existing[0], 'forecast_count': existing[1], 'duplicate': True}
    meta = _run_row(conn, run_id)
    initial = _now(now)
    cutoff = ml.utc(meta['issue_time'])
    spec_json = json.dumps(spec, sort_keys=True, separators=(',', ':'))
    spec_hash = hashlib.sha256(spec_json.encode()).hexdigest()
    count, skipped, model_id, status, message = 0, 0, None, 'not_collected', ''
    candidate = spec.get('candidate')
    conn.execute('SAVEPOINT shadow_capture')
    try:
        if not spec.get('enabled', True):
            raise ValueError('Shadow collection is disabled')
        if (spec.get('algorithm_version') != 'v02-1' or candidate not in ml.CANDIDATES
                or spec.get('candidate_spec') != ml.CANDIDATES[candidate]
                or spec.get('features') != ml.BASE_FEATURES
                or spec.get('shadow_only') is not True or spec.get('automatic_promotion') is not False):
            raise ValueError('Unrecognised or non-shadow frozen selection')
        if meta.get('issue_slot_source') not in {'explicit', 'clock_fallback'}:
            raise ValueError('Live origin must have recorded slot metadata')
        if meta.get('model_name') != 'fundamental_baseline' or meta.get('model_version') != '0.7.1':
            raise ValueError('Shadow specification expects Champion 0.7.1')
        age = (pd.Timestamp(initial) - cutoff).total_seconds()
        if not 0 <= age <= 1800:
            raise ValueError('Refusing hindsight capture of an old or future Champion run')
        train = ml.load_training_data(conn, cutoff)
        train = train[train.first_published_at > train.issue_time].copy()
        train = ml.training_before(train, cutoff)
        fitted = ml.fit_candidate(train, candidate)
        frame = pd.read_sql_query('''SELECT f.*,r.issue_time,r.issue_slot,r.issue_slot_source
            FROM price_forecasts_hourly f JOIN price_forecast_runs r
            ON r.forecast_run_id=f.forecast_run_id WHERE f.forecast_run_id=?''', conn, params=(run_id,))
        frame = ml.features(frame)
        prediction, correction = ml.predict_candidate(fitted, frame)
        # Stamp AFTER fitting/predicting, then exclude all targets already
        # complete or published by that actual capture time.
        recorded = _now(now)
        stamp = recorded.isoformat()
        actual = ml.hourly_actuals(ml.read_prices(conn))
        known = set(actual.loc[actual.first_published_at <= pd.Timestamp(recorded), 'target_time']) if not actual.empty else set()
        eligible = (frame.target_time > pd.Timestamp(recorded)) & ~frame.target_time.isin(known)
        skipped = int((~eligible).sum())
        payload = io.BytesIO()
        joblib.dump(fitted, payload)
        blob = payload.getvalue()
        model_id = hashlib.sha256(blob + spec_json.encode() + ml.data_fingerprint(train).encode()).hexdigest()
        conn.execute('''INSERT OR IGNORE INTO shadow_models VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                     (model_id, candidate, stamp, cutoff.isoformat(), len(train),
                      int(train.forecast_run_id.nunique()), train.actual_available_at.max().isoformat(),
                      ml.data_fingerprint(train), spec_json, sklearn.__version__, sqlite3.Binary(blob)))
        rows = [(run_id, row.target_time.isoformat(), int(row.horizon_days), model_id,
                 float(row.p50_eur_mwh), float(prediction[i]), float(correction[i]), stamp)
                for i, row in frame.iterrows() if bool(eligible.iloc[i])]
        conn.executemany('INSERT INTO shadow_forecasts VALUES(?,?,?,?,?,?,?,?)', rows)
        count = len(rows)
        status = 'recorded' if count else 'no_eligible_targets'
        message = 'Frozen candidate; all training actuals available before origin; first capture only'
        conn.execute('RELEASE shadow_capture')
    except Exception as exc:
        conn.execute('ROLLBACK TO shadow_capture')
        conn.execute('RELEASE shadow_capture')
        stamp = _now(now).isoformat()
        message = f'{type(exc).__name__}: {exc}'
    conn.execute('''INSERT INTO shadow_runs
        (forecast_run_id,issue_time,issue_slot,issue_slot_source,recorded_at_utc,status,
         candidate,model_id,spec_sha256,forecast_count,skipped_known_price,message)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (run_id, meta['issue_time'], meta.get('issue_slot'), meta.get('issue_slot_source'),
         stamp, status, candidate, model_id, spec_hash, count, skipped, message))
    return {'status': status, 'forecast_count': count, 'skipped_known_price': skipped,
            'candidate': candidate, 'model_id': model_id, 'message': message}


def score(conn, now=None):
    from . import challenger_v2 as ml
    import pandas as pd
    ensure_shadow_schema(conn)
    stamp = _now(now)
    actual = ml.hourly_actuals(ml.read_prices(conn))
    if actual.empty:
        return 0
    actual = actual[actual.actual_available_at < pd.Timestamp(stamp)]
    lookup = {row.target_time: row for row in actual.itertuples()}
    rows = conn.execute('''SELECT f.forecast_run_id,f.target_time,f.champion_p50_eur_mwh,
        f.challenger_p50_eur_mwh,f.recorded_at_utc FROM shadow_forecasts f
        LEFT JOIN shadow_scores s ON s.forecast_run_id=f.forecast_run_id
        AND s.target_time=f.target_time WHERE s.forecast_run_id IS NULL''').fetchall()
    count = 0
    for rid, target, champion, challenger, recorded in rows:
        a = lookup.get(ml.utc(target))
        if a is None or a.first_published_at <= ml.utc(recorded):
            continue
        conn.execute('INSERT OR IGNORE INTO shadow_scores VALUES(?,?,?,?,?,?,?,?)',
                     (rid, target, a.actual_eur_mwh, a.first_published_at.isoformat(),
                      a.actual_available_at.isoformat(), champion - a.actual_eur_mwh,
                      challenger - a.actual_eur_mwh, stamp.isoformat()))
        count += conn.execute('SELECT changes()').fetchone()[0]
    return count


def _comparison(rows):
    if not rows:
        return {'n': 0, 'unique_target_hours': 0, 'forecast_runs': 0,
                'champion_mae_eur_mwh': None, 'challenger_mae_eur_mwh': None,
                'champion_rmse_eur_mwh': None, 'challenger_rmse_eur_mwh': None,
                'champion_bias_eur_mwh': None, 'challenger_bias_eur_mwh': None,
                'mae_skill_pct': None}
    c = [r['champion_error_eur_mwh'] for r in rows]
    h = [r['challenger_error_eur_mwh'] for r in rows]
    cm, hm = statistics.mean(map(abs, c)), statistics.mean(map(abs, h))
    return {'n': len(rows), 'unique_target_hours': len({r['target_time'] for r in rows}),
            'forecast_runs': len({r['forecast_run_id'] for r in rows}),
            'champion_mae_eur_mwh': round(cm, 4), 'challenger_mae_eur_mwh': round(hm, 4),
            'champion_rmse_eur_mwh': round(math.sqrt(statistics.mean(x*x for x in c)), 4),
            'challenger_rmse_eur_mwh': round(math.sqrt(statistics.mean(x*x for x in h)), 4),
            'champion_bias_eur_mwh': round(statistics.mean(c), 4),
            'challenger_bias_eur_mwh': round(statistics.mean(h), 4),
            'mae_skill_pct': round(100*(cm-hm)/cm, 3) if cm else None}


def summary(conn, now=None):
    ensure_shadow_schema(conn)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute('''SELECT s.*, f.horizon_days,
        r.issue_slot,r.issue_slot_source,r.spec_sha256 FROM shadow_scores s
        JOIN shadow_forecasts f USING(forecast_run_id,target_time)
        JOIN shadow_runs r USING(forecast_run_id)''')]
    result = {'schema_version': '1.0', 'status': 'collecting',
              'generated_at_utc': _now(now).isoformat(), 'automatic_promotion': False,
              'overall': _comparison(rows), 'by_horizon': {}, 'by_slot': {}, 'by_spec': {},
              'collection_status': dict(conn.execute('SELECT status,COUNT(*) FROM shadow_runs GROUP BY status').fetchall())}
    for field, key in [('horizon_days', 'by_horizon'), ('issue_slot', 'by_slot'), ('spec_sha256', 'by_spec')]:
        for value in sorted({str(r[field]) for r in rows}):
            result[key][value] = _comparison([r for r in rows if str(r[field]) == value])
    last = conn.execute('SELECT forecast_run_id,status,message,recorded_at_utc FROM shadow_runs ORDER BY recorded_at_utc DESC LIMIT 1').fetchone()
    result['latest_collection'] = dict(last) if last else None
    if last is None:
        result['status'] = 'not_started'
    elif last['status'] != 'recorded':
        result['status'] = 'degraded'
    first = conn.execute("SELECT MIN(recorded_at_utc) FROM shadow_runs WHERE status='recorded'").fetchone()[0]
    result['first_recorded_at_utc'] = first
    days = (_now(now) - datetime.fromisoformat(first)).total_seconds()/86400 if first else 0
    result['observed_days'] = round(days, 2)
    result['assessment_ready'] = bool(days >= 28 and result['overall']['forecast_runs'] >= 40
                                      and result['overall']['unique_target_hours'] >= 500
                                      and len(result['by_spec']) == 1)
    result['assessment_gate'] = '28 days, 40 scored origins, 500 unique target hours and one frozen specification; manual review only'
    return result


def collect_current(run_id):
    from .config import ROOT
    from .db import connect, init_db
    init_db()
    with connect() as conn:
        try:
            spec = json.loads((ROOT / 'config/challenger_v2.json').read_text(encoding='utf-8'))
            result = capture(conn, run_id, spec)
        except Exception as exc:
            # Also record failures before capture starts (missing ML packages,
            # unreadable configuration). Publication can still show the gap.
            ensure_shadow_schema(conn)
            meta = _run_row(conn, run_id)
            message = f'{type(exc).__name__}: {exc}'
            conn.execute('''INSERT OR IGNORE INTO shadow_runs
                (forecast_run_id,issue_time,issue_slot,issue_slot_source,recorded_at_utc,status,message)
                VALUES(?,?,?,?,?,'not_collected',?)''',
                (run_id, meta['issue_time'], meta.get('issue_slot'), meta.get('issue_slot_source'),
                 _now().isoformat(), message))
            result = {'status': 'not_collected', 'message': message}
    if result['status'] != 'recorded':
        raise RuntimeError('Shadow not collected: ' + result.get('message', result['status']))
    return result


def score_and_report():
    from .config import ROOT
    from .db import connect, init_db
    init_db()
    with connect() as conn:
        n = score(conn)
        report = summary(conn)
    path = ROOT / 'output/shadow_comparison.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'new_scores': n, 'summary': report}


def current_summary():
    from .db import connect, init_db
    init_db()
    with connect() as conn:
        return summary(conn)


def safe_current_summary():
    try:
        return current_summary()
    except Exception as exc:
        return {'status': 'unavailable', 'automatic_promotion': False,
                'message': f'{type(exc).__name__}: {exc}'}
