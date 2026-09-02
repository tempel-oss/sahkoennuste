from __future__ import annotations
import sqlite3
from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS actuals (
    dataset_id INTEGER NOT NULL,
    valid_time TEXT NOT NULL,
    end_time TEXT,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (dataset_id, valid_time)
);

CREATE TABLE IF NOT EXISTS forecast_runs (
    run_id TEXT PRIMARY KEY,
    issue_time TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forecasts (
    run_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    valid_time TEXT NOT NULL,
    end_time TEXT,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES forecast_runs(run_id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, dataset_id, valid_time)
);

CREATE INDEX IF NOT EXISTS idx_forecasts_metric_valid ON forecasts(metric, valid_time);
CREATE INDEX IF NOT EXISTS idx_actuals_metric_valid ON actuals(metric, valid_time);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    dataset_id INTEGER NOT NULL,
    dataset_name TEXT NOT NULL,
    fetched_rows INTEGER NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entsoe_runs (
    run_id TEXT PRIMARY KEY,
    issue_time TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entsoe_series (
    run_id TEXT NOT NULL,
    series_name TEXT NOT NULL,
    area TEXT NOT NULL,
    document_type TEXT,
    process_type TEXT,
    psr_type TEXT,
    valid_time TEXT NOT NULL,
    end_time TEXT,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    source TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES entsoe_runs(run_id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, series_name, area, valid_time, COALESCE(psr_type,''))
);

CREATE INDEX IF NOT EXISTS idx_entsoe_series_metric_valid ON entsoe_series(metric, valid_time);
CREATE INDEX IF NOT EXISTS idx_entsoe_series_area_valid ON entsoe_series(area, valid_time);

CREATE TABLE IF NOT EXISTS entsoe_ingestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    series_name TEXT NOT NULL,
    area TEXT NOT NULL,
    fetched_rows INTEGER NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    # SQLite does not allow expressions in PRIMARY KEY definitions. Migrate the v0.4
    # ENTSO-E table with a normalized psr_type key instead.
    fixed = SCHEMA.replace(
        "PRIMARY KEY (run_id, series_name, area, valid_time, COALESCE(psr_type,''))",
        "PRIMARY KEY (run_id, series_name, area, valid_time, psr_type)"
    )
    with connect() as conn:
        conn.executescript(fixed)

WEATHER_SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_runs (
    run_id TEXT PRIMARY KEY,
    issue_time TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weather_series (
    run_id TEXT NOT NULL,
    location TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (run_id, location, valid_time, metric)
);
CREATE INDEX IF NOT EXISTS idx_weather_metric_time ON weather_series(metric, valid_time);
CREATE TABLE IF NOT EXISTS feature_runs (
    feature_run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    fingrid_run_id TEXT,
    weather_run_id TEXT,
    entsoe_run_id TEXT,
    status TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS features_hourly (
    feature_run_id TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    source_detail TEXT,
    PRIMARY KEY(feature_run_id, valid_time, feature_name)
);
CREATE INDEX IF NOT EXISTS idx_features_time ON features_hourly(valid_time, feature_name);
CREATE TABLE IF NOT EXISTS service_health (
    service TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);
"""

_old_init_db = init_db
def init_db() -> None:
    _old_init_db()
    with connect() as conn:
        conn.executescript(WEATHER_SCHEMA)

V06_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_runs (
    run_id TEXT PRIMARY KEY,
    issue_time TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT
);
CREATE TABLE IF NOT EXISTS market_prices (
    run_id TEXT NOT NULL,
    area TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    end_time TEXT,
    price_eur_mwh REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(run_id,area,valid_time)
);
CREATE INDEX IF NOT EXISTS idx_market_prices_area_time ON market_prices(area,valid_time);
CREATE TABLE IF NOT EXISTS forecast_errors (
    error_run_id TEXT NOT NULL,
    forecast_run_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    forecast_value REAL NOT NULL,
    actual_value REAL NOT NULL,
    error REAL NOT NULL,
    abs_error REAL NOT NULL,
    horizon_hours REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(error_run_id,forecast_run_id,metric,valid_time)
);
CREATE INDEX IF NOT EXISTS idx_forecast_errors_metric ON forecast_errors(metric,horizon_hours);
"""

_prev_init_v05 = init_db
def init_db() -> None:
    _prev_init_v05()
    with connect() as conn:
        conn.executescript(V06_SCHEMA)

V07_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_forecast_runs (
    forecast_run_id TEXT PRIMARY KEY,
    issue_time TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    feature_run_id TEXT,
    status TEXT NOT NULL,
    data_quality TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS price_forecasts_hourly (
    forecast_run_id TEXT NOT NULL,
    target_time TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    p10_eur_mwh REAL NOT NULL,
    p50_eur_mwh REAL NOT NULL,
    p90_eur_mwh REAL NOT NULL,
    baseline_eur_mwh REAL NOT NULL,
    load_est_mw REAL,
    wind_est_mw REAL,
    solar_est_mw REAL,
    net_load_est_mw REAL,
    drivers_json TEXT,
    PRIMARY KEY(forecast_run_id,target_time)
);
CREATE INDEX IF NOT EXISTS idx_price_fc_hour_target ON price_forecasts_hourly(target_time,horizon_days);
CREATE TABLE IF NOT EXISTS price_forecasts_daily (
    forecast_run_id TEXT NOT NULL,
    target_date TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    p10_eur_mwh REAL NOT NULL,
    p50_eur_mwh REAL NOT NULL,
    p90_eur_mwh REAL NOT NULL,
    baseline_eur_mwh REAL NOT NULL,
    min_p50_eur_mwh REAL NOT NULL,
    max_p50_eur_mwh REAL NOT NULL,
    cheapest_3h TEXT,
    expensive_3h TEXT,
    risk_level TEXT,
    drivers_json TEXT,
    PRIMARY KEY(forecast_run_id,target_date)
);
CREATE INDEX IF NOT EXISTS idx_price_fc_day_target ON price_forecasts_daily(target_date,horizon_days);
CREATE TABLE IF NOT EXISTS price_forecast_scores (
    score_run_id TEXT NOT NULL,
    forecast_run_id TEXT NOT NULL,
    target_time TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    p50_eur_mwh REAL NOT NULL,
    actual_eur_mwh REAL NOT NULL,
    error_eur_mwh REAL NOT NULL,
    abs_error_eur_mwh REAL NOT NULL,
    baseline_eur_mwh REAL NOT NULL,
    baseline_abs_error_eur_mwh REAL NOT NULL,
    inside_p10_p90 INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(score_run_id,forecast_run_id,target_time)
);
CREATE INDEX IF NOT EXISTS idx_price_fc_scores_horizon ON price_forecast_scores(horizon_days,created_at);
"""

_prev_init_v061 = init_db
def init_db() -> None:
    _prev_init_v061()
    with connect() as conn:
        conn.executescript(V07_SCHEMA)


V08_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecast_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    target_date TEXT NOT NULL,
    horizon_day INTEGER,
    component TEXT NOT NULL,
    value REAL,
    unit TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_fd_run_date
ON forecast_diagnostics(run_id,target_date);

CREATE TABLE IF NOT EXISTS forecast_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    prev_run_id TEXT,
    target_date TEXT NOT NULL,
    metric TEXT NOT NULL,
    old_value REAL,
    new_value REAL,
    delta REAL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_fc_run_date
ON forecast_changes(run_id,target_date);

CREATE TABLE IF NOT EXISTS uncertainty_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    target_date TEXT NOT NULL,
    weather_component REAL,
    model_component REAL,
    total_component REAL,
    unit TEXT DEFAULT 'snt/kWh'
);
"""

_prev_init_v07 = init_db
def init_db() -> None:
    _prev_init_v07()
    with connect() as conn:
        conn.executescript(V08_SCHEMA)
