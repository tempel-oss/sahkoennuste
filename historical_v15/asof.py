from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ISSUE_TIMES = ("06:15", "16:15")


def parse_issue_times(values):
    out = []
    seen = set()
    for value in values:
        s = str(value).strip()
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid issue time {value!r}; expected HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid issue time {value!r}")
        key = (hour, minute)
        if key in seen:
            continue
        seen.add(key)
        out.append((hour, minute, f"{hour:02d}{minute:02d}"))
    return sorted(out)


def _prepare_hourly(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x = (
        x.sort_values("timestamp_utc")
         .drop_duplicates("timestamp_utc", keep="last")
         .set_index("timestamp_utc")
    )

    # Precompute rolling/last-known history ONCE. The old v1.5.7 code
    # recalculated these slices thousands of times, which was very slow.
    if "price_eur_mwh" in x:
        s = x["price_eur_mwh"]
        x["_price_last"] = s
        x["_price_mean_24h"] = s.rolling(24, min_periods=1).mean()
        x["_price_mean_7d"] = s.rolling(168, min_periods=1).mean()
        x["_price_std_7d"] = s.rolling(168, min_periods=2).std(ddof=0)
        x["_price_min_7d"] = s.rolling(168, min_periods=1).min()
        x["_price_max_7d"] = s.rolling(168, min_periods=1).max()

    for source_col, prefix in (
        ("consumption_actual_mw", "consumption"),
        ("production_actual_mw", "production"),
        ("wind_actual_mw", "wind"),
    ):
        if source_col in x:
            s = x[source_col]
            x[f"_{prefix}_last"] = s
            x[f"_{prefix}_mean_24h"] = s.rolling(24, min_periods=1).mean()
            x[f"_{prefix}_mean_7d"] = s.rolling(168, min_periods=1).mean()

    return x


def _issue_table(x: pd.DataFrame, issue_times, timezone: str,
                 max_horizon_day: int) -> pd.DataFrame:
    parsed = parse_issue_times(issue_times)

    start_local = x.index.min().tz_convert(timezone).normalize()
    end_local = x.index.max().tz_convert(timezone).normalize()

    issue_days = pd.date_range(
        start_local + pd.Timedelta(days=28),
        end_local - pd.Timedelta(days=max_horizon_day),
        freq="1D",
        tz=timezone,
    )

    parts = []
    for hour, minute, code in parsed:
        local = issue_days + pd.Timedelta(hours=hour, minutes=minute)
        utc = local.tz_convert("UTC")

        part = pd.DataFrame({
            "issue_time_local": local,
            "issue_time_utc": utc,
            "issue_slot": "morning" if (hour, minute) < (12, 0) else "afternoon",
            "issue_time_code": code,
            "issue_hour_local": hour,
            "issue_minute_local": minute,
            "issue_hour_sin": np.sin(2*np.pi*(hour + minute/60)/24),
            "issue_hour_cos": np.cos(2*np.pi*(hour + minute/60)/24),
        })
        parts.append(part)

    issues = pd.concat(parts, ignore_index=True).sort_values("issue_time_utc")

    # Issue times are xx:15, while truth store is hourly. Use latest hourly
    # timestamp at or before issue_time, never a future row.
    history_cols = [c for c in x.columns if c.startswith("_")]
    base = x[history_cols + (["wind_capacity_mw"] if "wind_capacity_mw" in x else [])]
    base = base.reset_index().rename(columns={"timestamp_utc": "_history_time_utc"})

    issues = pd.merge_asof(
        issues.sort_values("issue_time_utc"),
        base.sort_values("_history_time_utc"),
        left_on="issue_time_utc",
        right_on="_history_time_utc",
        direction="backward",
        allow_exact_matches=True,
    )

    rename = {
        "_price_last": "price_last_at_issue",
        "_price_mean_24h": "price_mean_24h_at_issue",
        "_price_mean_7d": "price_mean_7d_at_issue",
        "_price_std_7d": "price_std_7d_at_issue",
        "_price_min_7d": "price_min_7d_at_issue",
        "_price_max_7d": "price_max_7d_at_issue",
        "_consumption_last": "consumption_last_at_issue",
        "_consumption_mean_24h": "consumption_mean_24h_at_issue",
        "_consumption_mean_7d": "consumption_mean_7d_at_issue",
        "_production_last": "production_last_at_issue",
        "_production_mean_24h": "production_mean_24h_at_issue",
        "_production_mean_7d": "production_mean_7d_at_issue",
        "_wind_last": "wind_last_at_issue",
        "_wind_mean_24h": "wind_mean_24h_at_issue",
        "_wind_mean_7d": "wind_mean_7d_at_issue",
        "wind_capacity_mw": "wind_capacity_latest_at_issue",
    }
    issues = issues.rename(columns={k:v for k,v in rename.items() if k in issues.columns})
    return issues


def build_horizon_dataset(
    df: pd.DataFrame,
    issue_times=DEFAULT_ISSUE_TIMES,
    min_horizon_day: int = 2,
    max_horizon_day: int = 12,
    timezone: str = "Europe/Helsinki",
    progress: bool = True,
):
    """
    Fast, vectorized dual-origin D+2...D+12 dataset builder.

    Same semantics as v1.5.7, but rolling history is precomputed once and
    target rows are generated vectorially instead of one Python dict at a time.
    """
    x = _prepare_hourly(df)
    if "price_eur_mwh" not in x.columns:
        raise ValueError("price_eur_mwh missing from input dataset")

    issues = _issue_table(x, issue_times, timezone, max_horizon_day)
    if progress:
        print(f"prepared issue origins: {len(issues):,}")

    # Fast lookup series for targets and safe historical target-hour lags.
    price = x["price_eur_mwh"]

    parts = []
    total_groups = len(parse_issue_times(issue_times)) * (
        max_horizon_day - min_horizon_day + 1
    )
    group_no = 0

    for code in sorted(issues["issue_time_code"].unique()):
        issue_sub = issues[issues["issue_time_code"] == code].copy()

        for horizon_day in range(min_horizon_day, max_horizon_day + 1):
            group_no += 1
            if progress:
                print(
                    f"  group {group_no:02d}/{total_groups}: "
                    f"issue {code[:2]}:{code[2:]} D+{horizon_day}"
                )

            # Cross each issue date with the 24 target local hours.
            repeated = issue_sub.loc[issue_sub.index.repeat(24)].reset_index(drop=True)
            hours = np.tile(np.arange(24, dtype=int), len(issue_sub))

            target_day_local = (
                repeated["issue_time_local"].dt.normalize()
                + pd.to_timedelta(horizon_day, unit="D")
            )
            target_local = target_day_local + pd.to_timedelta(hours, unit="h")
            target_utc = target_local.dt.tz_convert("UTC")

            # Lookup actual target price.
            target_price = price.reindex(pd.DatetimeIndex(target_utc)).to_numpy()

            out = repeated.drop(columns=["_history_time_utc"], errors="ignore").copy()
            out["target_time_utc"] = target_utc.to_numpy()
            out["horizon_day"] = horizon_day
            out["horizon_hours"] = (
                (target_utc.reset_index(drop=True) -
                 out["issue_time_utc"].reset_index(drop=True))
                / pd.Timedelta(hours=1)
            ).to_numpy()
            out["target_price_eur_mwh"] = target_price
            out["target_hour_local"] = target_local.dt.hour.to_numpy()
            out["target_weekday_local"] = target_local.dt.weekday.to_numpy()
            out["target_month_local"] = target_local.dt.month.to_numpy()
            out["target_is_weekend"] = (
                target_local.dt.weekday >= 5
            ).astype(int).to_numpy()
            out["target_hour_sin"] = np.sin(2*np.pi*out["target_hour_local"]/24)
            out["target_hour_cos"] = np.cos(2*np.pi*out["target_hour_local"]/24)
            doy = target_local.dt.dayofyear.to_numpy()
            out["target_doy_sin"] = np.sin(2*np.pi*doy/365.25)
            out["target_doy_cos"] = np.cos(2*np.pi*doy/365.25)

            # Safe target-hour historical price lags.
            issue_utc = pd.to_datetime(out["issue_time_utc"], utc=True)
            target_idx = pd.DatetimeIndex(pd.to_datetime(out["target_time_utc"], utc=True))

            for lag_days in (7, 14, 21, 28):
                lag_t = target_idx - pd.Timedelta(days=lag_days)
                safe = lag_t <= pd.DatetimeIndex(issue_utc)
                vals = np.array(price.reindex(lag_t).to_numpy(dtype=float), copy=True)
                vals[~safe] = np.nan
                col = f"target_same_hour_price_lag_{lag_days}d"
                out[col] = vals
                out[f"{col}_available"] = np.isfinite(vals).astype(int)

            # Remove target rows outside the truth-store range / without price.
            out = out[out["target_price_eur_mwh"].notna()].copy()
            parts.append(out)

    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values(
        ["issue_time_utc", "target_time_utc"]
    ).reset_index(drop=True)

    if progress:
        print(f"assembled horizon rows: {len(result):,}")

    return result
