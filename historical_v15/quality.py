from __future__ import annotations
import pandas as pd
from .common import coverage_report

TARGET_OR_POST_REALIZATION = {
    "price_eur_mwh",
    "consumption_actual_mw",
    "production_actual_mw",
    "wind_actual_mw",
    "consumption_forecast_error_mw",
    "production_forecast_error_mw",
    "wind_forecast_error_mw",
}

def leakage_columns():
    return sorted(TARGET_OR_POST_REALIZATION)

def write_quality_reports(df: pd.DataFrame, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    cov = coverage_report(df)
    cov.to_csv(report_dir / "coverage.csv", index=False)

    ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    expected = pd.date_range(ts.min(), ts.max(), freq="1h", tz="UTC") if len(ts) else []
    observed = pd.DatetimeIndex(ts.dropna().unique())
    missing = pd.DatetimeIndex(expected).difference(observed) if len(expected) else []
    pd.DataFrame({"missing_timestamp_utc": missing}).to_csv(
        report_dir / "missing_hours.csv", index=False
    )

    with open(report_dir / "leakage_guard.txt", "w", encoding="utf-8") as f:
        f.write("Do NOT use these current-timestamp columns as model inputs:\n")
        for c in leakage_columns():
            f.write(f"- {c}\n")
        f.write("\nUse only lagged versions when appropriate.\n")
    return cov
