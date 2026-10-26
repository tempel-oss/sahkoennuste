"""Shared, as-of-safe data preparation and fixed Challenger v0.2 candidates.

No production forecast is replaced by this module. Training and evaluation
use complete duration-weighted hours and the first complete price snapshot.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

BASE_FEATURES = [
    'p50_eur_mwh', 'p10_eur_mwh', 'p90_eur_mwh', 'baseline_eur_mwh',
    'load_est_mw', 'wind_est_mw', 'solar_est_mw', 'net_load_est_mw',
    'horizon_days', 'forecast_spread_eur_mwh', 'p50_vs_simple_baseline_eur_mwh',
    'wind_share_of_load', 'solar_share_of_load', 'net_load_share_of_load',
    'target_hour_sin', 'target_hour_cos', 'target_dow_sin', 'target_dow_cos',
    'target_doy_sin', 'target_doy_cos', 'target_is_weekend',
    'issue_slot_afternoon', 'issue_slot_unknown', 'lead_hours',
]
CANDIDATES = {
    'median_bias': {'kind': 'median', 'weight': 1.0, 'clip': True},
    'hgb_full_reference': {'kind': 'squared', 'weight': 1.0, 'clip': False},
    'hgb_robust_025': {'kind': 'absolute', 'weight': 0.25, 'clip': True},
    'hgb_robust_050': {'kind': 'absolute', 'weight': 0.50, 'clip': True},
}


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError('An aware UTC timestamp is required')
    return stamp.tz_convert('UTC')


def hourly_actuals(prices):
    p = prices.copy()
    for key in ['valid_time', 'end_time', 'issue_time']:
        p[key] = pd.to_datetime(p[key], utc=True, errors='coerce', format='mixed')
    p['price_eur_mwh'] = pd.to_numeric(p.price_eur_mwh, errors='coerce')
    p = p.dropna(subset=['valid_time', 'end_time', 'issue_time', 'price_eur_mwh'])
    p = p[np.isfinite(p.price_eur_mwh)].copy()
    p['hour'] = p.valid_time.dt.floor('h')
    rows = []
    for (_, hour), group in p.groupby(['run_id', 'hour']):
        g = group.sort_values('valid_time')
        end = hour + pd.Timedelta(hours=1)
        if g.valid_time.iloc[0] != hour or g.end_time.iloc[-1] != end:
            continue
        if not (g.valid_time.iloc[1:].reset_index(drop=True) ==
                g.end_time.iloc[:-1].reset_index(drop=True)).all():
            continue
        seconds = (g.end_time - g.valid_time).dt.total_seconds()
        if (seconds <= 0).any() or seconds.sum() != 3600:
            continue
        published = g.issue_time.max()
        rows.append({'target_time': hour,
                     'actual_eur_mwh': float(np.average(g.price_eur_mwh, weights=seconds)),
                     'first_published_at': published,
                     'actual_available_at': max(end, published)})
    if not rows:
        return pd.DataFrame(columns=['target_time', 'actual_eur_mwh',
                                     'first_published_at', 'actual_available_at'])
    return (pd.DataFrame(rows).sort_values(['actual_available_at', 'first_published_at'])
            .drop_duplicates('target_time').reset_index(drop=True))


def read_prices(conn):
    return pd.read_sql_query('''SELECT mp.run_id,mp.valid_time,mp.end_time,
        mp.price_eur_mwh,pr.issue_time FROM market_prices mp JOIN price_runs pr
        ON pr.run_id=mp.run_id WHERE mp.area='FI' ''', conn)


def features(frame):
    df = frame.copy()
    for key in ['target_time', 'issue_time']:
        df[key] = pd.to_datetime(df[key], utc=True, errors='coerce', format='mixed')
    for key in BASE_FEATURES[:9] + ['actual_eur_mwh']:
        if key in df:
            df[key] = pd.to_numeric(df[key], errors='coerce')
    target = df.target_time.dt.tz_convert('Europe/Helsinki')
    for name, value, period in [('hour', target.dt.hour, 24),
                                ('dow', target.dt.dayofweek, 7),
                                ('doy', target.dt.dayofyear, 365.25)]:
        df['target_' + name + '_sin'] = np.sin(2 * np.pi * value / period)
        df['target_' + name + '_cos'] = np.cos(2 * np.pi * value / period)
    df['target_is_weekend'] = (target.dt.dayofweek >= 5).astype(int)
    if 'issue_slot' not in df:
        df['issue_slot'] = 'unknown'
    df['issue_slot'] = df.issue_slot.where(df.issue_slot.isin(['morning', 'afternoon']), 'unknown')
    if 'issue_slot_source' not in df:
        df['issue_slot_source'] = 'unknown'
    df['issue_slot_afternoon'] = (df.issue_slot == 'afternoon').astype(int)
    df['issue_slot_unknown'] = (df.issue_slot == 'unknown').astype(int)
    df['lead_hours'] = (df.target_time - df.issue_time).dt.total_seconds() / 3600
    for key in ['p10_eur_mwh', 'p90_eur_mwh', 'baseline_eur_mwh',
                'load_est_mw', 'wind_est_mw', 'solar_est_mw', 'net_load_est_mw']:
        if key not in df:
            df[key] = np.nan
    df['forecast_spread_eur_mwh'] = df.p90_eur_mwh - df.p10_eur_mwh
    df['p50_vs_simple_baseline_eur_mwh'] = df.p50_eur_mwh - df.baseline_eur_mwh
    load = df.load_est_mw.where(df.load_est_mw.abs() > 1e-9)
    for kind in ['wind', 'solar', 'net_load']:
        df[kind + '_share_of_load'] = df[kind + '_est_mw'] / load
    df[BASE_FEATURES] = df[BASE_FEATURES].replace([np.inf, -np.inf], np.nan)
    if 'actual_eur_mwh' in df:
        df['residual_target_eur_mwh'] = df.actual_eur_mwh - df.p50_eur_mwh
    return df.sort_values(['issue_time', 'target_time']).reset_index(drop=True)


def load_training_data(conn, as_of):
    as_of = utc(as_of)
    forecast = pd.read_sql_query('''SELECT f.*,r.issue_time,r.issue_slot,r.issue_slot_source
        FROM price_forecasts_hourly f JOIN price_forecast_runs r
        ON r.forecast_run_id=f.forecast_run_id
        WHERE r.model_name='fundamental_baseline' AND r.model_version='0.7.1'
        AND r.status='ok' ''', conn)
    if forecast.duplicated(['forecast_run_id', 'target_time']).any():
        raise ValueError('Duplicate Champion forecast keys')
    actual = hourly_actuals(read_prices(conn))
    if actual.empty or forecast.empty:
        raise ValueError('Insufficient complete hourly prices or Champion forecasts')
    actual = actual[actual.actual_available_at < as_of]
    forecast['target_time'] = pd.to_datetime(forecast.target_time, utc=True, format='mixed')
    df = features(forecast.merge(actual, on='target_time', validate='many_to_one'))
    df = df[(df.target_time > df.issue_time) & (df.issue_time < as_of)
            & (df.target_time < as_of)].copy()
    df = df.dropna(subset=['p50_eur_mwh', 'actual_eur_mwh', 'horizon_days'])
    df = df[np.isfinite(df.p50_eur_mwh) & np.isfinite(df.actual_eur_mwh)]
    return df.reset_index(drop=True)


def training_before(df, cutoff):
    cutoff = utc(cutoff)
    return df[(df.issue_time < cutoff) & (df.target_time < cutoff)
              & (df.actual_available_at < cutoff)].copy()


def fit_candidate(train, candidate):
    if candidate not in CANDIDATES:
        raise ValueError('Unknown fixed candidate: ' + candidate)
    if len(train) < 200 or train.forecast_run_id.nunique() < 5:
        raise ValueError('At least 200 rows and 5 earlier origins required')
    spec = dict(CANDIDATES[candidate])
    cap = max(5.0, min(30.0, float(train.residual_target_eur_mwh.abs().quantile(0.90))))
    if spec['kind'] == 'median':
        estimator = float(train.residual_target_eur_mwh.median())
    else:
        robust = spec['kind'] == 'absolute'
        estimator = Pipeline([
            ('imputer', SimpleImputer(strategy='median', keep_empty_features=True)),
            ('model', HistGradientBoostingRegressor(
                loss='absolute_error' if robust else 'squared_error',
                learning_rate=0.05, max_iter=150 if robust else 250,
                max_leaf_nodes=7 if robust else 15,
                min_samples_leaf=60 if robust else 30,
                l2_regularization=5.0 if robust else 1.0, random_state=42)),
        ])
        estimator.fit(train[BASE_FEATURES], train.residual_target_eur_mwh)
    return {'candidate': candidate, 'spec': spec, 'cap_eur_mwh': cap,
            'estimator': estimator, 'features': list(BASE_FEATURES)}


def predict_candidate(model, frame):
    spec = model['spec']
    if spec['kind'] == 'median':
        raw = np.full(len(frame), model['estimator'], dtype=float)
    else:
        raw = model['estimator'].predict(frame[model['features']])
    if spec['clip']:
        raw = np.clip(raw, -model['cap_eur_mwh'], model['cap_eur_mwh'])
    correction = spec['weight'] * raw
    prediction = frame.p50_eur_mwh.to_numpy(dtype=float) + correction
    if not np.isfinite(prediction).all():
        raise ValueError('Non-finite shadow forecast')
    return prediction, correction


def metrics(actual, prediction):
    a, p = np.asarray(actual, dtype=float), np.asarray(prediction, dtype=float)
    if not len(a):
        return {'n': 0, 'mae_eur_mwh': None, 'rmse_eur_mwh': None,
                'bias_eur_mwh': None, 'median_ae_eur_mwh': None}
    error = p - a
    return {'n': len(a), 'mae_eur_mwh': round(float(np.mean(abs(error))), 4),
            'rmse_eur_mwh': round(float(np.sqrt(np.mean(error ** 2))), 4),
            'bias_eur_mwh': round(float(np.mean(error)), 4),
            'median_ae_eur_mwh': round(float(np.median(abs(error))), 4)}


def comparison(frame, prediction):
    champion = metrics(frame.actual_eur_mwh, frame.p50_eur_mwh)
    challenger = metrics(frame.actual_eur_mwh, prediction)
    c = champion['mae_eur_mwh']
    return {'champion': champion, 'challenger': challenger,
            'mae_skill_pct': round(100 * (c - challenger['mae_eur_mwh']) / c, 3) if c else None,
            'unique_target_hours': int(frame.target_time.nunique()),
            'forecast_runs': int(frame.forecast_run_id.nunique())}


def data_fingerprint(train):
    columns = ['forecast_run_id', 'issue_time', 'target_time', 'actual_eur_mwh',
               'actual_available_at', 'issue_slot', 'issue_slot_source'] + BASE_FEATURES
    raw = train[list(dict.fromkeys(columns))].sort_values(['forecast_run_id', 'target_time']).to_csv(index=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def input_audit(df):
    return {'rows': len(df), 'forecast_runs': int(df.forecast_run_id.nunique()),
            'unique_target_hours': int(df.target_time.nunique()),
            'first_issue': df.issue_time.min().isoformat(),
            'last_issue': df.issue_time.max().isoformat(),
            'slot_provenance_rows': df.issue_slot_source.fillna('unknown').value_counts().to_dict(),
            'slot_rows': df.issue_slot.value_counts().to_dict(),
            'missing_feature_fraction': {c: round(float(df[c].isna().mean()), 4) for c in BASE_FEATURES}}
