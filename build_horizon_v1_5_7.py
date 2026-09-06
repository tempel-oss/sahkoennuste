from __future__ import annotations

from pathlib import Path
import argparse
import json
import pandas as pd

from historical_v15.asof import (
    DEFAULT_ISSUE_TIMES,
    build_horizon_dataset,
    parse_issue_times,
)


NON_FEATURE_COLUMNS = {
    "issue_time_utc",
    "issue_time_local",
    "target_time_utc",
    "target_price_eur_mwh",
    "issue_slot",       # categorical metadata; encoded later by ML pipeline
    "issue_time_code",  # categorical metadata; encoded later by ML pipeline
}


def main():
    p = argparse.ArgumentParser(
        description=(
            "Sähköennuste v1.5.7 dual-origin "
            "D+2...D+12 as-of dataset builder"
        )
    )
    p.add_argument(
        "--input",
        default=r"data\processed\historical_features_hourly.parquet",
    )
    p.add_argument(
        "--output-dir",
        default=r"data\processed\v1_5_7",
    )
    p.add_argument(
        "--issue-times",
        default=",".join(DEFAULT_ISSUE_TIMES),
        help="Comma-separated local times, default 06:15,16:15",
    )
    p.add_argument("--min-horizon-day", type=int, default=2)
    p.add_argument("--max-horizon-day", type=int, default=12)
    p.add_argument(
        "--write-csv",
        action="store_true",
        help="Also write the full CSV (large; parquet is recommended).",
    )
    args = p.parse_args()

    issue_times = [
        s.strip() for s in args.issue_times.split(",") if s.strip()
    ]
    parsed = parse_issue_times(issue_times)

    inp = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(inp)

    print("Sähköennuste v1.5.7 DUAL FORECAST ORIGINS")
    print(f"input rows: {len(df):,}")
    print(
        "issue times local: "
        + ", ".join(f"{h:02d}:{m:02d}" for h, m, _ in parsed)
    )
    print(
        f"horizons: D+{args.min_horizon_day}..."
        f"D+{args.max_horizon_day}"
    )

    h = build_horizon_dataset(
        df,
        issue_times=issue_times,
        min_horizon_day=args.min_horizon_day,
        max_horizon_day=args.max_horizon_day,
    )

    parquet_path = out_dir / "horizon_asof_dual_d2_d12.parquet"
    h.to_parquet(parquet_path, index=False)

    if args.write_csv:
        h.to_csv(
            out_dir / "horizon_asof_dual_d2_d12.csv",
            index=False,
        )

    # Compact coverage by issue slot and horizon.
    feature_cols = [
        c for c in h.columns if c not in NON_FEATURE_COLUMNS
    ]
    cov_rows = []
    for (slot, hd), g in h.groupby(["issue_slot", "horizon_day"]):
        row = {
            "issue_slot": slot,
            "horizon_day": int(hd),
            "rows": int(len(g)),
        }
        for c in feature_cols:
            row[f"{c}__coverage_pct"] = round(
                100 * g[c].notna().mean(), 3
            )
        cov_rows.append(row)

    coverage = pd.DataFrame(cov_rows)
    coverage.to_csv(
        out_dir / "dual_origin_feature_coverage.csv",
        index=False,
    )

    # One concise origin/horizon count table for quick inspection.
    count_table = (
        h.groupby(["issue_slot", "issue_time_code", "horizon_day"])
         .size()
         .rename("rows")
         .reset_index()
    )
    count_table.to_csv(
        out_dir / "dual_origin_row_counts.csv",
        index=False,
    )

    manifest = {
        "version": "1.5.7",
        "purpose": "Two daily leakage-safe forecast origins",
        "issue_times_local": [
            f"{hour:02d}:{minute:02d}"
            for hour, minute, _ in parsed
        ],
        "timezone": "Europe/Helsinki",
        "min_horizon_day": args.min_horizon_day,
        "max_horizon_day": args.max_horizon_day,
        "rows": int(len(h)),
        "issue_origins": int(h["issue_time_utc"].nunique()) if len(h) else 0,
        "morning_origins": int(
            h.loc[h["issue_slot"] == "morning", "issue_time_utc"].nunique()
        ) if len(h) else 0,
        "afternoon_origins": int(
            h.loc[h["issue_slot"] == "afternoon", "issue_time_utc"].nunique()
        ) if len(h) else 0,
        "target_start_utc": (
            str(h["target_time_utc"].min()) if len(h) else None
        ),
        "target_end_utc": (
            str(h["target_time_utc"].max()) if len(h) else None
        ),
        "target_column": "target_price_eur_mwh",
        "categorical_training_columns": [
            "issue_slot",
            "issue_time_code",
        ],
        "numeric_training_columns": [
            c for c in h.columns if c not in NON_FEATURE_COLUMNS
        ],
        "note": (
            "Morning and afternoon rows are separate forecast origins. "
            "Issue-time anchored historical features are recomputed for each "
            "origin, so 16:15 may use information that was not yet known at "
            "06:15 on the same day."
        ),
    }

    (out_dir / "dual_origin_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    print()
    print("DONE")
    print(f"rows: {len(h):,}")
    print(f"issue_origins: {manifest['issue_origins']:,}")
    print(f"morning_origins: {manifest['morning_origins']:,}")
    print(f"afternoon_origins: {manifest['afternoon_origins']:,}")
    if len(h):
        print()
        print("rows by issue slot:")
        print(h.groupby("issue_slot").size().to_string())
        print()
        print("rows by horizon:")
        print(h.groupby("horizon_day").size().to_string())
    print(f"dataset: {parquet_path}")


if __name__ == "__main__":
    main()
