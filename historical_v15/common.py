from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

def utc_ts(x):
    return pd.to_datetime(x, utc=True)

def to_hourly(df: pd.DataFrame, value_col: str, how: str = "mean") -> pd.DataFrame:
    if df.empty:
        return df
    x = df.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x = x.set_index("timestamp_utc").sort_index()
    if how == "sum":
        y = x[value_col].resample("1h").sum(min_count=1)
    elif how == "last":
        y = x[value_col].resample("1h").last()
    else:
        y = x[value_col].resample("1h").mean()
    return y.rename(value_col).to_frame().reset_index()

def atomic_parquet(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)

def safe_numeric(s):
    return pd.to_numeric(s, errors="coerce")

def coverage_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = len(df)
    for c in df.columns:
        missing = int(df[c].isna().sum())
        rows.append({
            "column": c,
            "rows": n,
            "non_null": n - missing,
            "missing": missing,
            "coverage_pct": round(100 * (n - missing) / n, 2) if n else 0.0,
        })
    return pd.DataFrame(rows).sort_values(["coverage_pct", "column"])
