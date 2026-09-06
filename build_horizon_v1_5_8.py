from __future__ import annotations

from pathlib import Path
import argparse
import json
import time
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
    "issue_slot",
    "issue_time_code",
}


def main():
    p = argparse.ArgumentParser(
        description="Sähköennuste v1.5.8 fast dual-origin horizon builder"
    )
    p.add_argument(
        "--input",
        default=r"data\processed\historical_features_hourly.parquet",
    )
    p.add_argument(
        "--output-dir",
        default=r"data\processed\v1_5_8",
    )
    p.add_argument(
        "--issue-times",
        default=",".join(DEFAULT_ISSUE_TIMES),
    )
    p.add_argument("--min-horizon-day", type=int, default=2)
    p.add_argument("--max-horizon-day", type=int, default=12)
    p.add_argument("--write-csv", action="store_true")
    args = p.parse_args()

    issue_times = [s.strip() for s in args.issue_times.split(",") if s.strip()]
    parsed = parse_issue_times(issue_times)

    inp = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(inp)

    print("Sähköennuste v1.5.8 FAST DUAL FORECAST ORIGINS")
    print(f"input rows: {len(df):,}")
    print("issue times local: " + ", ".join(
        f"{h:02d}:{m:02d}" for h, m, _ in parsed
    ))
    print(f"horizons: D+{args.min_horizon_day}...D+{args.max_horizon_day}")
    print()

    t0 = time.perf_counter()
    h = build_horizon_dataset(
        df,
        issue_times=issue_times,
        min_horizon_day=args.min_horizon_day,
        max_horizon_day=args.max_horizon_day,
        progress=True,
    )
    build_seconds = time.perf_counter() - t0

    parquet_path = out_dir / "horizon_asof_dual_d2_d12.parquet"
    print("writing parquet ...")
    h.to_parquet(parquet_path, index=False)

    if args.write_csv:
        print("writing CSV ...")
        h.to_csv(out_dir / "horizon_asof_dual_d2_d12.csv", index=False)

    count_table = (
        h.groupby(["issue_slot", "issue_time_code", "horizon_day"])
         .size().rename("rows").reset_index()
    )
    count_table.to_csv(out_dir / "dual_origin_row_counts.csv", index=False)

    manifest = {
        "version": "1.5.8",
        "issue_times_local": [f"{h:02d}:{m:02d}" for h,m,_ in parsed],
        "timezone": "Europe/Helsinki",
        "rows": int(len(h)),
        "issue_origins": int(h["issue_time_utc"].nunique()),
        "morning_origins": int(
            h.loc[h["issue_slot"]=="morning","issue_time_utc"].nunique()
        ),
        "afternoon_origins": int(
            h.loc[h["issue_slot"]=="afternoon","issue_time_utc"].nunique()
        ),
        "build_seconds": round(build_seconds, 3),
        "target_start_utc": str(h["target_time_utc"].min()),
        "target_end_utc": str(h["target_time_utc"].max()),
    }
    (out_dir / "dual_origin_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print()
    print("DONE")
    print(f"rows: {len(h):,}")
    print(f"issue_origins: {manifest['issue_origins']:,}")
    print(f"morning_origins: {manifest['morning_origins']:,}")
    print(f"afternoon_origins: {manifest['afternoon_origins']:,}")
    print(f"build_seconds: {build_seconds:.1f}")
    print(f"dataset: {parquet_path}")


if __name__ == "__main__":
    main()
