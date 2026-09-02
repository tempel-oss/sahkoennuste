from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from electricity_forecaster.db import connect, init_db
from electricity_forecaster.config import DB_PATH

init_db()
print("Tietokanta:", DB_PATH)
with connect() as conn:
    a = conn.execute("SELECT metric, COUNT(*), MAX(valid_time) FROM actuals GROUP BY metric ORDER BY metric").fetchall()
    f = conn.execute("SELECT metric, COUNT(*), MAX(valid_time) FROM forecasts GROUP BY metric ORDER BY metric").fetchall()
    runs = conn.execute("SELECT COUNT(*), MAX(issue_time) FROM forecast_runs").fetchone()
    e = conn.execute("SELECT area, metric, COUNT(*), MAX(valid_time) FROM entsoe_series GROUP BY area,metric ORDER BY metric,area").fetchall()
    eruns = conn.execute("SELECT COUNT(*), MAX(issue_time) FROM entsoe_runs").fetchone()
print("\nFINGRID - TOTEUMAT")
for row in a: print(f"  {row[0]:40s} {row[1]:6d}  viimeisin {row[2]}")
print("\nFINGRID - ENNUSTESNAPSHOTIT")
for row in f: print(f"  {row[0]:40s} {row[1]:6d}  pisimmillaan {row[2]}")
print("\nFingrid-ajoja:", runs[0], " viimeisin:", runs[1])
print("\nENTSO-E - SNAPSHOTIT")
for row in e: print(f"  {row[0]:4s} {row[1]:40s} {row[2]:6d}  viimeisin {row[3]}")
print("\nENTSO-E-ajoja:", eruns[0], " viimeisin:", eruns[1])

with connect() as conn:
    w = conn.execute("SELECT metric, COUNT(*), MAX(valid_time) FROM weather_series GROUP BY metric ORDER BY metric").fetchall()
    wr = conn.execute("SELECT COUNT(*), MAX(issue_time) FROM weather_runs").fetchone()
    ff = conn.execute("SELECT feature_name, COUNT(*), MAX(valid_time) FROM features_hourly GROUP BY feature_name ORDER BY feature_name").fetchall()
    fr = conn.execute("SELECT COUNT(*), MAX(created_at) FROM feature_runs").fetchone()
    health = conn.execute("SELECT service, status, checked_at, detail FROM service_health ORDER BY service").fetchall()
print("\nSAA - SNAPSHOTIT")
for row in w: print(f"  {row[0]:40s} {row[1]:6d}  pisimmillaan {row[2]}")
print("\nSaa-ajoja:", wr[0], " viimeisin:", wr[1])
print("\nYHDISTETYT FEATURET")
for row in ff: print(f"  {row[0]:40s} {row[1]:6d}  pisimmillaan {row[2]}")
print("\nFeature-ajoja:", fr[0], " viimeisin:", fr[1])
print("\nPALVELUJEN TERVEYS")
for row in health: print(f"  {row[0]:10s} {row[1]:10s} {row[2]}  {row[3] or ''}")

with connect() as conn:
    try:
        prices = conn.execute("SELECT area, COUNT(*), MAX(valid_time) FROM market_prices GROUP BY area ORDER BY area").fetchall()
        errors = conn.execute("SELECT COUNT(*), MAX(created_at) FROM forecast_errors").fetchone()
    except Exception:
        prices=[]; errors=(0,None)
print("\nHINTADATA")
for row in prices: print(f"  {row[0]:5s} {row[1]:6d}  viimeisin {row[2]}")
print("\nEnnustevirheita:", errors[0], " viimeisin pisteytys:", errors[1])

with connect() as conn:
    try:
        pfr = conn.execute("SELECT COUNT(*), MAX(issue_time) FROM price_forecast_runs").fetchone()
        pfd = conn.execute("SELECT COUNT(*), MAX(target_date) FROM price_forecasts_daily").fetchone()
        pfs = conn.execute("SELECT COUNT(*), MAX(created_at) FROM price_forecast_scores").fetchone()
    except Exception:
        pfr=(0,None); pfd=(0,None); pfs=(0,None)
print("\nHINTAENNUSTEET v0.7")
print("  Ennusteajoja:", pfr[0], " viimeisin:", pfr[1])
print("  Paivaennusteita:", pfd[0], " pisin kohde:", pfd[1])
print("  Pisteytettyja tuntiennusteita:", pfs[0], " viimeisin pisteytys:", pfs[1])
