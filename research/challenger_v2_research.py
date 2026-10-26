"""Select on earlier walk-forward folds, freeze the choice, then open holdout.

Run against a temporary copy of the cloud DB. No promotion or source writes.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import numpy as np
import pandas as pd
import sklearn
from electricity_forecaster.issue_slots import migrate_issue_slots
from electricity_forecaster import challenger_v2 as model


def development_folds(dev):
    runs = dev[['forecast_run_id', 'issue_time']].drop_duplicates().sort_values('issue_time')
    start = max(8, len(runs) // 2)
    if len(runs) < start + 3:
        raise ValueError('Too few development origins for three validation folds')
    return [runs.iloc[index] for index in np.array_split(np.arange(start, len(runs)), 3)]


def correction_audit(frame, prediction):
    applied = np.asarray(prediction) - frame.p50_eur_mwh.to_numpy()
    required = frame.actual_eur_mwh - frame.p50_eur_mwh
    return {'mean_required_correction_eur_mwh': round(float(required.mean()), 4),
            'mean_applied_correction_eur_mwh': round(float(np.mean(applied)), 4),
            'median_applied_correction_eur_mwh': round(float(np.median(applied)), 4),
            'p95_absolute_applied_correction_eur_mwh': round(float(np.quantile(abs(applied), .95)), 4),
            'mean_remaining_bias_eur_mwh': round(float(np.mean(applied - required)), 4)}


def research(conn, out, as_of=None):
    as_of = pd.Timestamp.now(tz='UTC') if as_of is None else model.utc(as_of)
    df = model.load_training_data(conn, as_of)
    # A price already published at issue is not a genuine forecast test target.
    known = int((df.first_published_at <= df.issue_time).sum())
    df = df[df.first_published_at > df.issue_time].copy()
    origins = df[['forecast_run_id', 'issue_time']].drop_duplicates().sort_values('issue_time')
    if len(origins) < 30:
        raise ValueError('At least 30 eligible forecast origins are required')
    boundary = origins.iloc[int(len(origins) * .8)].issue_time
    dev = model.training_before(df, boundary)
    holdout = df[df.issue_time >= boundary].copy()
    if dev.empty or holdout.empty:
        raise ValueError('Empty development or holdout set')
    folds = development_folds(dev)
    predictions = {name: [] for name in model.CANDIDATES}
    fold_reports = []
    for number, origins_block in enumerate(folds, 1):
        test = dev[dev.forecast_run_id.isin(origins_block.forecast_run_id)].copy()
        cutoff = test.issue_time.min()
        train = model.training_before(dev, cutoff)
        report = {'fold': number, 'train_rows': len(train), 'test_rows': len(test),
                  'train_max_actual_available_at': train.actual_available_at.max().isoformat(),
                  'test_issue_start': cutoff.isoformat(), 'candidates': {}}
        for name in model.CANDIDATES:
            fitted = model.fit_candidate(train, name)
            pred, _ = model.predict_candidate(fitted, test)
            report['candidates'][name] = model.comparison(test, pred)
            part = test.copy()
            part['prediction'] = pred
            predictions[name].append(part)
        fold_reports.append(report)
    development = {}
    for name, parts in predictions.items():
        joined = pd.concat(parts)
        development[name] = model.comparison(joined, joined.prediction)
        development[name]['bias_diagnostics'] = correction_audit(joined, joined.prediction)
    # Full unbounded squared-error HGB is diagnostic only, never a v0.2 choice.
    eligible = [name for name in model.CANDIDATES if name != 'hgb_full_reference']
    eligible.sort(key=lambda name: (development[name]['challenger']['mae_eur_mwh'], name))
    chosen = eligible[0]
    spec = {'schema_version': '1.0', 'model_name': 'residual_challenger',
            'model_version': '0.2', 'algorithm_version': 'v02-1',
            'candidate': chosen, 'candidate_spec': model.CANDIDATES[chosen],
            'features': model.BASE_FEATURES,
            'selection_cutoff_utc': boundary.isoformat(),
            'selection_policy': 'lowest development OOF MAE among median and capped damped robust HGB',
            'shadow_only': True, 'automatic_promotion': False,
            'refit_policy': 'same frozen candidate; fit only on completed prices available before each live origin'}
    # Freeze before any holdout predictions or metrics are computed.
    out.mkdir(parents=True, exist_ok=True)
    spec_text = json.dumps(spec, indent=2, sort_keys=True) + '\n'
    (out / 'selection.json').write_text(spec_text, encoding='utf-8')
    selection_hash = hashlib.sha256(spec_text.encode()).hexdigest()
    holdout_results = {}
    diagnostics = {}
    for name in model.CANDIDATES:
        fitted = model.fit_candidate(dev, name)
        pred, _ = model.predict_candidate(fitted, holdout)
        holdout_results[name] = model.comparison(holdout, pred)
        diagnostics[name] = correction_audit(holdout, pred)
        if name == chosen:
            selected_prediction = pred
    grouped = {}
    h = holdout.copy()
    h['prediction'] = selected_prediction
    for key in ['horizon_days', 'issue_slot', 'issue_slot_source']:
        grouped[key] = {str(value): model.comparison(g, g.prediction) for value, g in h.groupby(key)}
    result = {
        'status': 'shadow_only', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_commit': os.getenv('GITHUB_SHA'), 'source_cache': os.getenv('MATCHED_CACHE'),
        'versions': {'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__},
        'data': model.input_audit(df), 'excluded_known_price_at_issue_rows': known,
        'development_rows': len(dev), 'holdout_rows': len(holdout),
        'holdout_issue_start': holdout.issue_time.min().isoformat(),
        'holdout_issue_end': holdout.issue_time.max().isoformat(),
        'holdout_rule': 'last 20 percent of origins; no development target or actual availability at/after boundary; frozen fit at boundary',
        'holdout_caveat': 'Historical v1 aggregate results have already been observed; prospective shadow evidence is still required.',
        'development_folds': fold_reports, 'development': development,
        'selected_candidate': chosen, 'selection_sha256': selection_hash,
        'selection': spec, 'holdout': holdout_results,
        'holdout_bias_diagnostics': diagnostics, 'selected_by_group': grouped,
        'production_champion_changed': False, 'automatic_promotion': False,
    }
    (out / 'report.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# Challenger v0.2 — shadow only', '',
             'Selected before opening historical holdout: **' + chosen + '**.', '',
             '| Candidate | Development MAE | Holdout MAE | Holdout RMSE | Holdout skill % |',
             '|---|---:|---:|---:|---:|']
    for name in model.CANDIDATES:
        m = holdout_results[name]
        lines.append(f"| {name} | {development[name]['challenger']['mae_eur_mwh']:.3f} | {m['challenger']['mae_eur_mwh']:.3f} | {m['challenger']['rmse_eur_mwh']:.3f} | {m['mae_skill_pct']:.2f} |")
    lines += ['', f"Champion holdout MAE: {holdout_results[chosen]['champion']['mae_eur_mwh']:.3f} EUR/MWh.",
              '', result['holdout_caveat'], '', 'No automatic promotion. Live shadow monitoring starts prospectively.']
    (out / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', type=Path, default=ROOT / 'data/electricity_forecaster.sqlite3')
    ap.add_argument('--output', type=Path, default=ROOT / 'research_results/challenger_v2')
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        with contextlib.closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            conn = sqlite3.connect(str(Path(temp) / 'research.sqlite3'))
            try:
                source.backup(conn)
                migrate_issue_slots(conn)
                conn.commit()
                result = research(conn, args.output)
            finally:
                conn.close()
    print('BEGIN_CHALLENGER_V2_SUMMARY')
    print(json.dumps(result, indent=2, allow_nan=False))
    print('END_CHALLENGER_V2_SUMMARY')


if __name__ == '__main__':
    main()
