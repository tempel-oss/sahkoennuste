from __future__ import annotations
import numpy as np
import pandas as pd
from .common import to_hourly

def add_calendar_features(df):
    x = df.copy()
    t = pd.to_datetime(x["timestamp_utc"], utc=True).dt.tz_convert("Europe/Helsinki")
    x["hour_local"] = t.dt.hour
    x["weekday_local"] = t.dt.weekday
    x["month_local"] = t.dt.month
    x["is_weekend"] = (t.dt.weekday >= 5).astype(int)
    x["hour_sin"] = np.sin(2*np.pi*x["hour_local"]/24)
    x["hour_cos"] = np.cos(2*np.pi*x["hour_local"]/24)
    x["doy_sin"] = np.sin(2*np.pi*t.dt.dayofyear/365.25)
    x["doy_cos"] = np.cos(2*np.pi*t.dt.dayofyear/365.25)
    return x

def add_safe_price_lags(df):
    """
    Only historical prices that were known before target hour.
    These remain leakage-safe for ordinary hour-ahead/day-ahead training,
    provided the forecast cutoff is enforced in the final training split.
    """
    x = df.sort_values("timestamp_utc").copy()
    if "price_eur_mwh" not in x:
        return x
    x["price_lag_24h"] = x["price_eur_mwh"].shift(24)
    x["price_lag_48h"] = x["price_eur_mwh"].shift(48)
    x["price_lag_168h"] = x["price_eur_mwh"].shift(168)
    x["price_mean_prev_24h"] = x["price_eur_mwh"].shift(24).rolling(24, min_periods=12).mean()
    x["price_mean_prev_7d"] = x["price_eur_mwh"].shift(24).rolling(168, min_periods=72).mean()
    return x

def build_hourly_table(series: dict[str, pd.DataFrame], prices: pd.DataFrame | None = None):
    """
    Merge every source on UTC hourly timestamps.
    Forecast series should preferably be the once-a-day/day-ahead datasets,
    not revised intraday forecasts.
    """
    frames = []
    for name, df in series.items():
        x = df.rename(columns={"value": name})
        x = to_hourly(x[["timestamp_utc", name]], name, "last" if "capacity" in name else "mean")
        frames.append(x.set_index("timestamp_utc"))
    if prices is not None and not prices.empty:
        p = to_hourly(prices, "price_eur_mwh", "mean").set_index("timestamp_utc")
        frames.append(p)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1).sort_index().reset_index()
    out = add_calendar_features(out)
    out = add_safe_price_lags(out)

    if {"consumption_forecast_day_ahead_mw","production_forecast_day_ahead_mw"}.issubset(out.columns):
        out["forecast_power_balance_mw"] = (
            out["production_forecast_day_ahead_mw"] - out["consumption_forecast_day_ahead_mw"]
        )
    if {"wind_forecast_day_ahead_mw","wind_capacity_mw"}.issubset(out.columns):
        out["wind_forecast_capacity_factor"] = (
            out["wind_forecast_day_ahead_mw"] / out["wind_capacity_mw"].replace(0, np.nan)
        )
    if {"wind_actual_mw","wind_forecast_day_ahead_mw"}.issubset(out.columns):
        out["wind_forecast_error_mw"] = out["wind_actual_mw"] - out["wind_forecast_day_ahead_mw"]

    # Targets/evaluation columns; never include these as training features for their own timestamp.
    if {"consumption_actual_mw","consumption_forecast_day_ahead_mw"}.issubset(out.columns):
        out["consumption_forecast_error_mw"] = (
            out["consumption_actual_mw"] - out["consumption_forecast_day_ahead_mw"]
        )
    if {"production_actual_mw","production_forecast_day_ahead_mw"}.issubset(out.columns):
        out["production_forecast_error_mw"] = (
            out["production_actual_mw"] - out["production_forecast_day_ahead_mw"]
        )
    return out
