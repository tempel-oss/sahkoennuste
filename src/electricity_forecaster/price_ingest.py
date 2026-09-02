from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json, uuid
from .config import ROOT
from .db import connect, init_db

BASE='https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices'
RAW=ROOT/'data'/'raw'/'nordpool'
AREAS=['FI','SE1','SE2','SE3','SE4','EE','NO1','NO2','NO3','NO4','NO5','DK1','DK2']

def _fetch(day: str, areas: list[str]):
    q=urlencode({'date':day,'market':'DayAhead','deliveryArea':','.join(areas),'currency':'EUR'})
    req=Request(BASE+'?'+q,headers={'Accept':'application/json','User-Agent':'electricity-forecaster/0.6-windows-native'})
    try:
        with urlopen(req,timeout=45) as r:
            if r.status==204: return None
            return json.loads(r.read().decode('utf-8'))
    except HTTPError as e:
        if e.code==204: return None
        body=e.read().decode('utf-8',errors='replace')[:300]
        raise RuntimeError(f'Nord Pool HTTP {e.code}: {body}') from e
    except URLError as e:
        raise RuntimeError(f'Nord Pool -yhteys epaonnistui: {e.reason}') from e

def _rows(payload):
    if not payload: return []
    entries=payload.get('multiAreaEntries') or payload.get('entries') or []
    out=[]
    for x in entries:
        start=x.get('deliveryStart') or x.get('startTime')
        end=x.get('deliveryEnd') or x.get('endTime') or start
        per=x.get('entryPerArea') or x.get('areaPrices') or {}
        if isinstance(per,list):
            per={str(i.get('area') or i.get('deliveryArea')): i.get('price') for i in per}
        if not start or not isinstance(per,dict): continue
        for area,val in per.items():
            if val is None: continue
            try: v=float(val)
            except Exception: continue
            out.append((area,start,end,v))
    return out

def ingest_prices(days_back=2, days_forward=1):
    init_db(); now=datetime.now(timezone.utc).replace(microsecond=0); rid=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    fetched=0; status='ok'; msg=''
    RAW.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.execute('INSERT INTO price_runs(run_id,issue_time,source,status,message) VALUES (?,?,?,?,?)',(rid,now.isoformat(),'nordpool_public','running',''))
        for off in range(-days_back,days_forward+1):
            day=(now+timedelta(days=off)).date().isoformat()
            try:
                p=_fetch(day,AREAS)
                if p is None: continue
                (RAW/f'{rid}_{day}.json').write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
                rows=_rows(p)
                c.executemany('INSERT OR REPLACE INTO market_prices(run_id,area,valid_time,end_time,price_eur_mwh,source) VALUES (?,?,?,?,?,?)',[(rid,a,s,e,v,'nordpool_public') for a,s,e,v in rows])
                fetched += len(rows)
            except Exception as e:
                status='degraded'; msg=(msg+'; '+day+': '+str(e)).strip('; ')
        c.execute('UPDATE price_runs SET status=?,message=? WHERE run_id=?',(status,msg,rid))
    print(f'[OK]' if fetched else '[VAROITUS]',f'Nord Pool: {fetched} hintarivia; status={status}')
    return fetched
