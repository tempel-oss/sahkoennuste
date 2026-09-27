from _bootstrap import *
from pathlib import Path
import json
import sqlite3

from electricity_forecaster.config import DB_PATH
from electricity_forecaster.db_maintenance import latest_price_forecast_scores_rows

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dist"
OUT_PATH = OUT_DIR / "cloud_training_export.sqlite3"
MANIFEST_PATH = OUT_DIR / "cloud_training_export_manifest.json"

# Copied verbatim (schema + all rows). price_forecast_scores is handled
# separately below because it needs de-duplicating first (see
# electricity_forecaster.db_maintenance).
VERBATIM_TABLES = ["price_forecast_runs", "price_forecasts_hourly"]


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, name: str) -> int:
    ddl_row = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    if not ddl_row:
        raise RuntimeError(f"Taulua {name} ei loydy pilven kannasta.")
    dst.execute(ddl_row[0])
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({name})")]
    col_list = ",".join(cols)
    rows = src.execute(f"SELECT {col_list} FROM {name}").fetchall()
    if rows:
        placeholders = ",".join(["?"] * len(cols))
        dst.executemany(
            f"INSERT INTO {name} ({col_list}) VALUES ({placeholders})", rows
        )
    return len(rows)


def main() -> int:
    if not Path(DB_PATH).is_file():
        print(f"[VIRHE] Pilven kantaa ei loydy: {DB_PATH}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        OUT_PATH.unlink()

    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    dst = sqlite3.connect(OUT_PATH)

    manifest = {}
    for name in VERBATIM_TABLES:
        manifest[name] = _copy_table(src, dst, name)

    # price_forecast_scores: export only the de-duplicated "latest per pair"
    # rows - the raw table is bloated with repeat scoring of the same
    # (forecast_run_id, target_time) pair on every production run (see
    # electricity_forecaster.db_maintenance for why).
    scores_ddl = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='price_forecast_scores'"
    ).fetchone()
    if not scores_ddl:
        raise RuntimeError("Taulua price_forecast_scores ei loydy pilven kannasta.")
    dst.execute(scores_ddl[0])
    scores_rows = list(latest_price_forecast_scores_rows(src))
    if scores_rows:
        dst.executemany(
            "INSERT INTO price_forecast_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            scores_rows,
        )
    raw_scores_total = src.execute(
        "SELECT COUNT(*) FROM price_forecast_scores"
    ).fetchone()[0]
    manifest["price_forecast_scores"] = len(scores_rows)
    manifest["price_forecast_scores_raw_before_dedupe"] = raw_scores_total

    dst.commit()
    dst.close()
    src.close()

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[OK] Pilven koulutusdatan vienti valmis.")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Tiedosto:", OUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
