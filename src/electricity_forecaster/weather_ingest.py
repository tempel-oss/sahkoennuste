from __future__ import annotations
from datetime import datetime, timezone
import uuid
from .db import connect, init_db
from .weather import fetch_ecmwf_deterministic, fetch_ecmwf_ensemble, fetch_fmi_harmonie

def ingest_weather():
    init_db(); now=datetime.now(timezone.utc).replace(microsecond=0); run_id=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    allrows=[]; messages=[]
    for provider,fn in [('ecmwf',lambda: fetch_ecmwf_deterministic(run_id)),('ensemble',lambda: fetch_ecmwf_ensemble(run_id)),('fmi',lambda: fetch_fmi_harmonie(run_id))]:
        try:
            r=fn()
            if provider=='ensemble': rows,chosen,errs=r; messages.append('ensemble_model='+str(chosen)); messages += errs
            elif provider=='fmi': rows,errs=r; messages += errs
            else: rows=r
            allrows += rows; print(f'[OK] {provider}: {len(rows)} rivia')
        except Exception as e: messages.append(f'{provider}: {e}'); print(f'[VAROITUS] {provider}: {e}')
    status='ok' if allrows else 'error'
    with connect() as c:
        c.execute('INSERT INTO weather_runs VALUES (?,?,?,?,?,?)',(run_id,now.isoformat(),'ecmwf+fmi',status,' | '.join(messages)[:4000],now.isoformat()))
        c.executemany('INSERT OR REPLACE INTO weather_series(run_id,location,valid_time,metric,value,unit,source) VALUES (?,?,?,?,?,?,?)',[(run_id,*x) for x in allrows])
        for svc,ok,detail in [('WEATHER',bool(allrows),f'{len(allrows)} rows')]:
            c.execute('INSERT OR REPLACE INTO service_health(service,checked_at,status,detail) VALUES (?,?,?,?)',(svc,now.isoformat(),'ok' if ok else 'error',detail))
    return run_id,len(allrows),messages
