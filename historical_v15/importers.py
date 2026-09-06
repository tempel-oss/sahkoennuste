from __future__ import annotations
import pandas as pd
from pathlib import Path

def import_price_csv(path: str | Path,
                     timestamp_col: str,
                     price_col: str,
                     timezone: str = "Europe/Helsinki") -> pd.DataFrame:
    """
    Fallback for Nord Pool / other CSV exports if ENTSO-E API is unavailable.
    If timestamps are timezone-naive, they are interpreted in Europe/Helsinki.
    """
    df = pd.read_csv(path)
    ts = pd.to_datetime(df[timestamp_col], errors="coerce")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(timezone, ambiguous="infer", nonexistent="shift_forward")
    ts = ts.dt.tz_convert("UTC")
    out = pd.DataFrame({
        "timestamp_utc": ts,
        "price_eur_mwh": pd.to_numeric(df[price_col], errors="coerce")
    })
    return out.dropna(subset=["timestamp_utc", "price_eur_mwh"]).sort_values("timestamp_utc")
