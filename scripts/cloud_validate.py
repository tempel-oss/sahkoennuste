
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
required=["index.html","latest_forecast.html","latest_forecast.json","manifest.webmanifest","sw.js"]
missing=[x for x in required if not (ROOT/"output"/x).exists()]
if missing:
    print("[VIRHE] Puuttuu:",", ".join(missing)); raise SystemExit(20)
d=json.loads((ROOT/"output"/"latest_forecast.json").read_text(encoding="utf-8"))
print("[OK] run",d.get("forecast_run_id"))
print("[OK] issue",d.get("forecast_issue_time"))
print("[OK] days",len(d.get("days",[])))
