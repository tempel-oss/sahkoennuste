from __future__ import annotations

from pathlib import Path
import argparse
from dotenv import load_dotenv

from historical_v15.config import Settings
from historical_v15.fingrid import FingridClient
from historical_v15.common import atomic_parquet


REPAIR_DATASETS = {
    "wind_actual_mw": 75,
    "capacity_fi_to_ee_mw": 115,
}


def main():
    parser = argparse.ArgumentParser(
        description="Repair Fingrid datasets that failed with HTTP 429."
    )
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-09-01")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    load_dotenv()
    st = Settings(
        root=Path(args.root).resolve(),
        start=args.start,
        end=args.end,
    )
    st.raw_dir.mkdir(parents=True, exist_ok=True)

    fg = FingridClient(
        st.fingrid_api_key,
        st.fingrid_api_base,
        min_interval_s=2.5,
        max_retries=7,
    )

    print("Sähköennuste v1.5.5 repair")
    print(f"period: {st.start} -> {st.end}")

    for name, dataset_id in REPAIR_DATASETS.items():
        print(f"\n[Fingrid repair] {name} (dataset {dataset_id})")
        df = fg.fetch_dataset(
            dataset_id,
            st.start,
            st.end,
            chunk_days=120,
        )
        path = st.raw_dir / f"fingrid_{name}.parquet"
        atomic_parquet(df, path)
        print(f"  SAVED rows={len(df):,}")
        print(f"  {path}")

    print("\nREPAIR DONE")
    print("Next run:")
    print(
        r".\.venv\Scripts\python.exe run_v1_5_historical.py "
        r"--start 2022-01-01 --end 2026-09-01 --only-build"
    )


if __name__ == "__main__":
    main()
