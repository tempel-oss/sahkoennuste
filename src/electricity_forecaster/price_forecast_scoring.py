from __future__ import annotations
from datetime import datetime, timezone
import uuid
from .db import connect, init_db
from .forecast_engine import _parse_dt


def score_price_forecasts():
    init_db(); now=datetime.now(timezone.utc).replace(microsecond=0); sid=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    with connect() as c:
        # Newest published FI price for each valid time.
        actual={}
        for t,v,issue in c.execute("""SELECT mp.valid_time,mp.price_eur_mwh,pr.issue_time
                                      FROM market_prices mp JOIN price_runs pr ON pr.run_id=mp.run_id
                                      WHERE mp.area='FI' ORDER BY pr.issue_time DESC"""):
            try: k=_parse_dt(t).replace(minute=0,second=0,microsecond=0).isoformat()
            except Exception: continue
            if k not in actual: actual[k]=float(v)
        n=0
        for fr,t,h,p10,p50,p90,base in c.execute("""SELECT forecast_run_id,target_time,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,baseline_eur_mwh
                                                     FROM price_forecasts_hourly"""):
            try: k=_parse_dt(t).replace(minute=0,second=0,microsecond=0).isoformat()
            except Exception: continue
            if k not in actual: continue
            a=actual[k]; err=p50-a; ae=abs(err); bae=abs(base-a); inside=1 if p10 <= a <= p90 else 0
            c.execute("""INSERT OR IGNORE INTO price_forecast_scores
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid,fr,t,h,p50,a,err,ae,base,bae,inside,now.isoformat()))
            n += c.execute('SELECT changes()').fetchone()[0]
    print(f'[OK] Hintennusteiden pisteytys: {n} uutta tuntipistetta')
    return n
