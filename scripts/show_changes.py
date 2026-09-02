import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","src"))
from electricity_forecaster.config import load_env_file
load_env_file()

import sqlite3
from electricity_forecaster.db import connect
con=connect(); con.row_factory=sqlite3.Row
r=con.execute("SELECT run_id,prev_run_id FROM forecast_changes ORDER BY id DESC LIMIT 1").fetchone()
if not r:
    print("Muutosvertailua ei viela ole."); raise SystemExit(0)
print("=== MUUTOS EDELLISEEN ENNUSTEESEEN v0.8.3 ===")
print("Nykyinen:",r["run_id"]); print("Edellinen:",r["prev_run_id"])
for x in con.execute("""SELECT target_date,metric,old_value,new_value,delta
FROM forecast_changes WHERE run_id=? ORDER BY target_date,metric""",(r["run_id"],)):
    print(f"{x['target_date']} {x['metric']:>3s}: {x['old_value']:7.2f} -> {x['new_value']:7.2f}  {x['delta']:+7.2f}")
con.close()
