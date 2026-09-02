import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","src"))
from electricity_forecaster.config import load_env_file
load_env_file()

import sqlite3
from electricity_forecaster.db import init_db, connect
init_db()
con=connect()
tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
req={"price_forecast_runs","price_forecasts_daily","price_forecasts_hourly",
     "features_hourly","forecast_diagnostics","forecast_changes","uncertainty_components"}
missing=req-tables
if missing:
    print("VIRHE: puuttuvat taulut:",", ".join(sorted(missing))); raise SystemExit(1)
print("[OK] v0.8.3 yhteensopivuus kunnossa.")
con.close()
