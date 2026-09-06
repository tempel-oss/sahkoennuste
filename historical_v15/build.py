from __future__ import annotations
from pathlib import Path
import argparse
import pandas as pd
from dotenv import load_dotenv

from .config import Settings, FINGRID_DATASETS
from .fingrid import FingridClient
from .entsoe import EntsoeClient
from .features import build_hourly_table
from .common import atomic_parquet
from .quality import write_quality_reports

ENDED_DATASETS = {
    24: "SE1->FI day-ahead capacity ended 2024-10-29",
    26: "FI->SE1 day-ahead capacity ended 2024-10-29",
}

def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

def main():
    parser = argparse.ArgumentParser(
        description="Sähköennuste v1.5.3 Historical Learning Dataset"
    )
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-09-01")
    parser.add_argument("--root", default=".")
    parser.add_argument("--skip-entsoe", action="store_true")
    parser.add_argument(
        "--only-build", action="store_true",
        help="Build from already downloaded raw parquet files."
    )
    args = parser.parse_args()

    load_dotenv()
    st = Settings(root=Path(args.root).resolve(), start=args.start, end=args.end)
    st.raw_dir.mkdir(parents=True, exist_ok=True)
    st.processed_dir.mkdir(parents=True, exist_ok=True)
    st.reports_dir.mkdir(parents=True, exist_ok=True)

    # Important: during a normal fetch run, build ONLY from data successfully
    # fetched in this run. This prevents stale 10-row files from an earlier
    # failed v1.5.x run contaminating the merged dataset.
    fresh_series = {}
    fresh_prices = None

    if not args.only_build:
        fg = FingridClient(st.fingrid_api_key, st.fingrid_api_base)

        for name, dsid in FINGRID_DATASETS.items():
            print(f"[Fingrid] {name} (dataset {dsid}) ...")

            if (
                dsid in ENDED_DATASETS
                and pd.Timestamp(st.start) >= pd.Timestamp("2024-10-30")
            ):
                print(f"  rows=0 (expected: {ENDED_DATASETS[dsid]})")
                continue

            try:
                df = fg.fetch_dataset(dsid, st.start, st.end)
                fresh_series[name] = df
                atomic_parquet(
                    df, st.raw_dir / f"fingrid_{name}.parquet"
                )
                print(f"  rows={len(df):,}")
            except Exception as e:
                print(f"  WARNING: {e}")

        if not args.skip_entsoe and st.entsoe_token:
            print("[ENTSO-E] Finland day-ahead prices ...")
            try:
                ep = EntsoeClient(st.entsoe_token, st.entsoe_api_base)
                fresh_prices = ep.fetch_day_ahead_prices(st.start, st.end)
                atomic_parquet(
                    fresh_prices,
                    st.raw_dir / "entsoe_fi_day_ahead_price.parquet"
                )
                print(f"  rows={len(fresh_prices):,}")
            except Exception as e:
                print(f"  WARNING: ENTSO-E unavailable: {e}")
        else:
            print("[ENTSO-E] skipped or token missing.")

        series = fresh_series
        prices = fresh_prices

    else:
        series = {}
        for name in FINGRID_DATASETS:
            p = st.raw_dir / f"fingrid_{name}.parquet"
            if p.exists():
                series[name] = pd.read_parquet(p)

        price_path = st.raw_dir / "entsoe_fi_day_ahead_price.parquet"
        prices = (
            pd.read_parquet(price_path)
            if price_path.exists()
            else None
        )

    print("[Build] merging hourly dataset ...")
    hourly = build_hourly_table(series, prices)
    if hourly.empty:
        raise SystemExit(
            "No fresh raw data available from this run. "
            "Check the warnings above."
        )

    start_utc = _utc(st.start)
    end_utc = _utc(st.end)

    hourly["timestamp_utc"] = pd.to_datetime(
        hourly["timestamp_utc"], utc=True
    )
    hourly = hourly[
        (hourly["timestamp_utc"] >= start_utc) &
        (hourly["timestamp_utc"] < end_utc)
    ].copy()

    out = st.processed_dir / "historical_features_hourly.parquet"
    atomic_parquet(hourly, out)
    hourly.to_csv(
        st.processed_dir / "historical_features_hourly.csv",
        index=False
    )

    cov = write_quality_reports(hourly, st.reports_dir)

    expected_rows = int(
        (end_utc - start_utc) / pd.Timedelta(hours=1)
    )

    source_rows = {
        name: int(len(df))
        for name, df in series.items()
    }
    pd.DataFrame(
        [{"source": k, "raw_rows": v} for k, v in source_rows.items()]
    ).to_csv(st.reports_dir / "source_row_counts.csv", index=False)

    summary = {
        "requested_start_utc": str(start_utc),
        "requested_end_utc_exclusive": str(end_utc),
        "start_utc": str(hourly["timestamp_utc"].min()),
        "end_utc": str(hourly["timestamp_utc"].max()),
        "rows": int(len(hourly)),
        "expected_hourly_rows": expected_rows,
        "hourly_row_coverage_pct": round(
            100 * len(hourly) / expected_rows, 2
        ) if expected_rows else 0.0,
        "columns": int(len(hourly.columns)),
        "price_rows": (
            int(hourly["price_eur_mwh"].notna().sum())
            if "price_eur_mwh" in hourly else 0
        ),
        "min_column_coverage_pct": (
            float(cov["coverage_pct"].min())
            if len(cov) else 0.0
        ),
    }

    pd.Series(summary).to_json(
        st.reports_dir / "build_summary.json", indent=2
    )

    print("\nDONE")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"Dataset: {out}")

if __name__ == "__main__":
    main()
