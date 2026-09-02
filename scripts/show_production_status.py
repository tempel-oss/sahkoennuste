
from _bootstrap import *
from pathlib import Path
from electricity_forecaster.config import ROOT
import json
out=ROOT/"output"/"latest_forecast.json"
print("=== v0.9 TUOTANTOTILA ===")
if out.exists():
    d=json.loads(out.read_text(encoding="utf-8"))
    print("Viimeisin julkaistu ajo:",d.get("forecast_issue_time"))
    print("Forecast run:",d.get("forecast_run_id"))
    print("Paivia:",len(d.get("days",[])))
    print("HTML:",ROOT/"output"/"latest_forecast.html")
else:
    print("latest_forecast.json puuttuu. Aja 21_AJA_KAIKKI.bat.")
logs=sorted((ROOT/"logs").glob("production_*.log"),reverse=True)
if logs:
    print("Viimeisin loki:",logs[0])
