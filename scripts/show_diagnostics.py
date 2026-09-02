import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","src"))
from electricity_forecaster.config import load_env_file
load_env_file()

import sqlite3
from electricity_forecaster.db import connect
con=connect(); con.row_factory=sqlite3.Row
r=con.execute("SELECT run_id FROM forecast_diagnostics ORDER BY id DESC LIMIT 1").fetchone()
if not r:
    print("Diagnostiikkaa ei loydy. Aja ensin 18_RAKENNA_DIAGNOSTIIKKA.bat."); raise SystemExit(1)
run=r["run_id"]
print("=== ENNUSTEDIAGNOSTIIKKA v0.8.3 ===")
print("Ajo:",run)
days=con.execute("""SELECT DISTINCT target_date,horizon_day FROM forecast_diagnostics
WHERE run_id=? ORDER BY horizon_day""",(run,)).fetchall()
for drow in days:
    d=drow["target_date"]; h=drow["horizon_day"]
    rr=con.execute("""SELECT component,value,unit FROM forecast_diagnostics
    WHERE run_id=? AND target_date=?""",(run,d)).fetchall()
    m={x["component"]:(x["value"],x["unit"]) for x in rr}
    u=con.execute("""SELECT weather_component,model_component,total_component
    FROM uncertainty_components WHERE run_id=? AND target_date=?""",(run,d)).fetchone()
    print(f"\n{d}  D+{h}")
    for k,label in [
      ("p50_price","P50 hinta"),("baseline_price","Baseline"),("consumption_forecast","Kulutus"),
      ("wind_forecast","Tuuli"),("solar_forecast","Aurinko"),("production_forecast","Tuotanto"),
      ("residual_load","Residual load"),("net_import_need","Nettotuontitarve"),
      ("temperature","Lampotila"),("wind_100m","100 m tuuli"),("wind_uncertainty","Tuulen epavarmuus"),
      ("fi_se1_capacity","FI->SE1 kapasiteetti"),("se1_fi_capacity","SE1->FI kapasiteetti"),
      ("fi_se3_capacity","FI->SE3 kapasiteetti")]:
        if k in m:
            v,unit=m[k]
            print(f"  {label:23s} {v:10.2f} {unit or ''}")
    if u:
        print(f"  P10-P90 puolileveys      {u['total_component']:10.2f} snt/kWh")
        print(f"    saakomponentti         {u['weather_component']:10.2f}")
        print(f"    mallikomponentti       {u['model_component']:10.2f}")
con.close()
