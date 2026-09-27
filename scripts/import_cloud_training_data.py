from _bootstrap import *
from pathlib import Path
import argparse
import shutil
import sqlite3

from electricity_forecaster.config import ROOT
from electricity_forecaster.db import connect, init_db
from electricity_forecaster.db_maintenance import dedupe_price_forecast_scores
from electricity_forecaster.forecast_quality import build_training_matrix

TABLES = ["price_forecast_runs", "price_forecasts_hourly", "price_forecast_scores"]

# training_matrix.csv itself lives under data/ml/, which is git-ignored (only
# data/ml/challenger_residual_hgb_v1/ is excepted - see .gitignore and
# loydokset_ja_korjaukset.md, section G). The raw price_forecast_* tables it is
# built from live only in the local SQLite file and in the cloud's GitHub
# Actions cache - and that cache is evicted automatically after 7 days without
# a run, and the whole cron schedule can be auto-disabled after 60 days of
# repository inactivity (see loydokset_ja_korjaukset.md, section J). Neither
# is a permanent store. Copying the freshly-rebuilt matrix into the one
# data/ml subfolder that IS committed to git turns it into something the next
# commit makes permanent, independent of what later happens to the cache.
SNAPSHOT_DIR = ROOT / "data" / "ml" / "challenger_residual_hgb_v1"


def _merge_table(local: sqlite3.Connection, name: str) -> dict:
    cols = [r[1] for r in local.execute(f"PRAGMA table_info({name})")]
    col_list = ",".join(cols)
    before = local.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    local.execute(
        f"INSERT OR IGNORE INTO main.{name} ({col_list}) "
        f"SELECT {col_list} FROM cloud.{name}"
    )
    after = local.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    return {"before": before, "after": after, "added": after - before}


def _refresh_training_matrix_snapshot() -> None:
    print("\n=== TRAINING_MATRIX PAIVITYS ===")
    meta = build_training_matrix()
    print(f"[OK] training_matrix.csv paivitetty ({meta['rows']} rivia, tila: {meta['status']}).")

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "data" / "ml" / "training_matrix.csv",
        SNAPSHOT_DIR / "training_matrix_snapshot.csv",
    )
    shutil.copyfile(
        ROOT / "data" / "ml" / "training_matrix_meta.json",
        SNAPSHOT_DIR / "training_matrix_snapshot_meta.json",
    )
    print(f"[OK] Pysyva snapshot paivitetty: {SNAPSHOT_DIR / 'training_matrix_snapshot.csv'}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Puhdista paikallinen price_forecast_scores-taulu "
                    "duplikaateista, ja tuo (valinnaisesti) pilvesta "
                    "vietyjen ennusteajojen historia mukaan."
    )
    ap.add_argument(
        "--export", default=None,
        help="GitHubista ladattu cloud_training_export.sqlite3-tiedosto. "
             "Jata pois jos haluat vain siivota paikallisen kannan."
    )
    args = ap.parse_args()

    init_db()
    with connect() as c:
        print("=== PAIKALLISEN KANNAN SIIVOUS (price_forecast_scores) ===")
        result = dedupe_price_forecast_scores(c)
        print(f"Ennen: {result['before']:,} rivia, jalkeen: {result['after']:,} rivia "
              f"(poistettu {result['removed']:,} duplikaattia)")

        if args.export:
            export_path = Path(args.export).resolve()
            if not export_path.is_file():
                print(f"[VIRHE] Tiedostoa ei loydy: {export_path}")
                return 2
            print(f"\n=== TUONTI: {export_path} ===")
            c.execute("ATTACH DATABASE ? AS cloud", (str(export_path),))
            try:
                for name in TABLES:
                    r = _merge_table(c, name)
                    print(f"{name:24s} ennen {r['before']:>7,}  jalkeen {r['after']:>7,}  "
                          f"lisatty {r['added']:>6,}")
                # Must commit before DETACH - SQLite refuses to detach a
                # database that a still-open transaction has touched
                # ("database cloud is locked").
                c.commit()
            finally:
                c.execute("DETACH DATABASE cloud")

            print("\n[OK] Tuonti valmis.")
        else:
            print("\n(Ei --export-parametria annettu - vain paikallinen siivous tehtiin.)")

    # Aina, riippumatta --export-lipusta: rebuild training_matrix.csv niin
    # etta se heijastaa juuri tehtya siivousta/tuontia, ja kopioi tuore
    # versio git-seurattuun kansioon (ks. SNAPSHOT_DIR yllä).
    _refresh_training_matrix_snapshot()

    print("\nSeuraava askel (uudelleenkoulutus):")
    print(r"  .\.venv\Scripts\python.exe train_residual_challenger_v1.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
