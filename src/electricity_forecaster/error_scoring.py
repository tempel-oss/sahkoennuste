
from __future__ import annotations
from datetime import datetime, timezone
import uuid
from .db import connect, init_db

def score_forecast_errors():
    init_db()
    now=datetime.now(timezone.utc).replace(microsecond=0)
    eid=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    pairs=[('wind_forecast_mw','wind_actual_mw'),
           ('consumption_forecast_mw','consumption_actual_mw')]
    count=0
    with connect() as c:
        for fm,am in pairs:
            # Fingrid actual and forecast series use matching validity timestamps.
            # Exact timestamp join is deterministic and avoids SQLite's unsupported
            # outer alias reference inside the old correlated ORDER BY expression.
            rows=c.execute("""
              SELECT f.run_id, r.issue_time, f.valid_time, f.value, a.value
              FROM forecasts f
              JOIN forecast_runs r ON r.run_id=f.run_id
              JOIN actuals a
                ON a.metric=?
               AND a.valid_time=f.valid_time
              WHERE f.metric=? AND f.valid_time <= ?
            """,(am,fm,now.isoformat())).fetchall()
            ins=[]
            for rid,issue,valid,fv,av in rows:
                try:
                    it=datetime.fromisoformat(issue.replace('Z','+00:00'))
                    vt=datetime.fromisoformat(valid.replace('Z','+00:00'))
                    hz=(vt-it).total_seconds()/3600
                except Exception:
                    hz=None
                err=float(fv)-float(av)
                ins.append((eid,rid,fm,valid,float(fv),float(av),err,abs(err),hz,now.isoformat()))
            c.executemany(
                'INSERT OR REPLACE INTO forecast_errors VALUES (?,?,?,?,?,?,?,?,?,?)',
                ins
            )
            count+=len(ins)
    print(f'[OK] ennustevirheita pisteytetty: {count}')
    return count
