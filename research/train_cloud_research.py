"""Isolated research: read-only source, no raw-data or model uploads."""
from pathlib import Path
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import numpy as np
import pandas as pd
import residual_reference as model


def hourly_actuals(prices):
    p = prices.copy()
    for c in ['valid_time', 'end_time', 'issue_time']:
        p[c] = pd.to_datetime(p[c], utc=True, errors='coerce')
    p['price_eur_mwh'] = pd.to_numeric(p.price_eur_mwh, errors='coerce')
    p = p.dropna(subset=['valid_time', 'end_time', 'issue_time', 'price_eur_mwh'])
    p['hour'] = p.valid_time.dt.floor('h')
    rows = []
    for (_, hour), g in p.groupby(['run_id', 'hour']):
        g = g.sort_values('valid_time')
        end = hour + pd.Timedelta(hours=1)
        if g.valid_time.iloc[0] != hour or g.end_time.iloc[-1] != end:
            continue
        if not (g.valid_time.iloc[1:].reset_index(drop=True) == g.end_time.iloc[:-1].reset_index(drop=True)).all():
            continue
        seconds = (g.end_time - g.valid_time).dt.total_seconds()
        if (seconds <= 0).any() or seconds.sum() != 3600:
            continue
        rows.append(dict(target_time=hour, actual_eur_mwh=float(np.average(g.price_eur_mwh, weights=seconds)),
                         actual_available_at=max(end, g.issue_time.max())))
    if not rows:
        raise RuntimeError('No complete hourly actual prices')
    # First complete published snapshot; no later revisions leak into earlier fits.
    return pd.DataFrame(rows).sort_values('actual_available_at').drop_duplicates('target_time')


def research(db_path, work):
    with contextlib.closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        forecasts = pd.read_sql_query('''SELECT f.*, r.issue_time
            FROM price_forecasts_hourly f JOIN price_forecast_runs r
            ON r.forecast_run_id=f.forecast_run_id
            WHERE r.model_name='fundamental_baseline' AND r.model_version='0.7.1' ''', con)
        prices = pd.read_sql_query('''SELECT mp.run_id, mp.valid_time, mp.end_time,
            mp.price_eur_mwh, pr.issue_time FROM market_prices mp
            JOIN price_runs pr ON pr.run_id=mp.run_id WHERE mp.area='FI' ''', con)
        score_count = con.execute('SELECT count(*) FROM price_forecast_scores').fetchone()[0]
        unique_scores = con.execute('SELECT count(*) FROM (SELECT DISTINCT forecast_run_id,target_time FROM price_forecast_scores)').fetchone()[0]
    for c in ['target_time', 'issue_time']:
        forecasts[c] = pd.to_datetime(forecasts[c], utc=True, errors='coerce')
    assert not forecasts.duplicated(['forecast_run_id', 'target_time']).any()
    hours = hourly_actuals(prices)
    hours = hours[hours.actual_available_at <= pd.Timestamp.now(tz='UTC')]
    merged = forecasts.merge(hours, on='target_time', validate='many_to_one')
    merged = merged[merged.target_time > merged.issue_time].copy()
    # Only numeric model features plus required identifiers remain in the temporary matrix.
    cols = list(dict.fromkeys(model.REQUIRED + [c for c in model.BASE_FEATURES if c in merged]))
    matrix = work / 'matrix.csv'
    merged[cols].to_csv(matrix, index=False)
    df = model._load_matrix(matrix)
    df = df.merge(hours[['target_time', 'actual_available_at']], on='target_time', validate='many_to_one')
    runs = df[['forecast_run_id', 'issue_time']].drop_duplicates()
    blocks = model._fold_blocks(runs, 5, 8)
    parts, reports = [], []
    for i, block in enumerate(blocks, 1):
        test = df[df.forecast_run_id.isin(block.forecast_run_id)].copy()
        start = test.issue_time.min()
        train = df[(df.issue_time < start) & (df.target_time < start) & (df.actual_available_at < start)]
        report = dict(fold=i, train_rows=len(train), train_runs=int(train.forecast_run_id.nunique()),
                      test_rows=len(test), test_runs=int(test.forecast_run_id.nunique()),
                      unique_test_hours=int(test.target_time.nunique()),
                      issue_start=start.isoformat(), issue_end=test.issue_time.max().isoformat())
        if len(train) < 200 or train.forecast_run_id.nunique() < 5:
            report['status'] = 'insufficient_training_data'
        else:
            pipe = model._make_pipeline()
            pipe.fit(train[model.BASE_FEATURES], train.residual_target_eur_mwh)
            test['challenger_p50_eur_mwh'] = test.p50_eur_mwh + pipe.predict(test[model.BASE_FEATURES])
            assert np.isfinite(test.challenger_p50_eur_mwh).all()
            report['status'] = 'evaluated'
            report['metrics'] = model._comparison(test.actual_eur_mwh, test.p50_eur_mwh, test.challenger_p50_eur_mwh)
            parts.append(test)
        reports.append(report)
    result = dict(status='research_only', source_score_rows=int(score_count),
                  source_unique_scored_pairs=int(unique_scores), training_rows=len(df),
                  training_runs=int(df.forecast_run_id.nunique()), unique_target_hours=int(df.target_time.nunique()),
                  first_issue=df.issue_time.min().isoformat(), last_issue=df.issue_time.max().isoformat(),
                  hourly_target_policy='duration-weighted complete hour; first complete snapshot',
                  purge='earlier issue and target; complete actual available before test issue', folds=reports)
    if parts:
        oof = pd.concat(parts, ignore_index=True)
        assert not oof.duplicated(['forecast_run_id', 'target_time']).any()
        overall, horizon, slot = model._group_reports(oof)
        result.update(overall=overall, by_horizon=horizon, by_slot=slot,
                      evaluated_unique_hours=int(oof.target_time.nunique()))
        model._fit_final(df, work)
        result['final_fit'] = 'completed; temporary model only, not published'
    else:
        result['status'] = 'insufficient_evaluation_data'
    return result


if __name__ == '__main__':
    source = Path('data/electricity_forecaster.sqlite3').resolve()
    if not os.environ.get('MATCHED_CACHE', '').startswith('forecast-db-'):
        raise SystemExit('Forecast cache not restored')
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        copy = work / 'research.sqlite3'
        with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with contextlib.closing(sqlite3.connect(copy)) as dst:
                src.backup(dst)
        with contextlib.redirect_stdout(io.StringIO()):
            result = research(copy, work)
        print('BEGIN_RESEARCH_SUMMARY')
        print(json.dumps(result, indent=2, allow_nan=False))
        print('END_RESEARCH_SUMMARY')
