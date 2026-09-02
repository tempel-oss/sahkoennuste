from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import json, math, uuid
from .config import ROOT
from .db import connect, init_db
LOCS={x['name']:x for x in json.loads((ROOT/'config'/'weather_locations.json').read_text(encoding='utf-8'))['locations']}

def hourkey(s): return s[:13]+':00:00'
def wind_cf(v):
    # transparent generic turbine proxy; later learned against Fingrid actuals
    if v < 3: return 0.0
    if v < 12: return min(1.0,((v-3)/9)**2.2)
    if v <= 25: return 1.0
    return 0.0

def build_features():
    init_db(); now=datetime.now(timezone.utc).replace(microsecond=0); fid=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    with connect() as c:
        wr=c.execute("SELECT run_id FROM weather_runs WHERE status='ok' ORDER BY issue_time DESC LIMIT 1").fetchone()
        fr=c.execute("SELECT run_id FROM forecast_runs WHERE source='fingrid' ORDER BY issue_time DESC LIMIT 1").fetchone()
        er=c.execute("SELECT run_id FROM entsoe_runs ORDER BY issue_time DESC LIMIT 1").fetchone()
        wr=wr[0] if wr else None; fr=fr[0] if fr else None; er=er[0] if er else None
        weather=defaultdict(dict)
        if wr:
            for loc,t,m,v,u,src in c.execute('SELECT location,valid_time,metric,value,unit,source FROM weather_series WHERE run_id=?',(wr,)):
                weather[(hourkey(t),loc)][m]=v
        # weighted weather features, preferring deterministic ECMWF metric names
        out=[]
        hours=sorted(set(k[0] for k in weather))
        for h in hours:
            def wavg(metric,weight):
                pairs=[]
                for loc,cfg in LOCS.items():
                    v=weather.get((h,loc),{}).get(metric)
                    if v is not None: pairs.append((v,cfg[weight]))
                sw=sum(w for _,w in pairs)
                return sum(v*w for v,w in pairs)/sw if sw else None
            vals={
                'weather_load_temp_c':wavg('temperature_2m_c','load_weight'),
                'weather_wind100_ms':wavg('wind_speed_100m_ms','wind_weight'),
                'weather_cloud_pct':wavg('cloud_cover_pct','load_weight'),
                'weather_solar_wm2':wavg('shortwave_radiation_wm2','load_weight'),
                'weather_wind_p10_ms':wavg('wind_speed_100m_ms_p10','wind_weight'),
                'weather_wind_p50_ms':wavg('wind_speed_100m_ms_p50','wind_weight'),
                'weather_wind_p90_ms':wavg('wind_speed_100m_ms_p90','wind_weight'),
            }
            if vals['weather_wind100_ms'] is not None: vals['weather_wind_cf_proxy']=wind_cf(vals['weather_wind100_ms'])
            if vals['weather_wind_p10_ms'] is not None and vals['weather_wind_p90_ms'] is not None:
                vals['weather_wind_uncertainty_ms']=vals['weather_wind_p90_ms']-vals['weather_wind_p10_ms']
            for n,v in vals.items():
                if v is not None: out.append((fid,h,n,float(v),'','weather_weighted'))
        # Fingrid latest run values, hour-bucket average
        fg=defaultdict(list)
        if fr:
            for t,m,v in c.execute('SELECT valid_time,metric,value FROM forecasts WHERE run_id=?',(fr,)):
                fg[(hourkey(t),m)].append(v)
            for (h,m),vs in fg.items(): out.append((fid,h,m,sum(vs)/len(vs),'MW','fingrid_latest_snapshot'))
        # derived residual/load features where direct Fingrid data overlaps
        tmp=defaultdict(dict)
        for _,h,n,v,u,s in out: tmp[h][n]=v
        derived=[]
        for h,d in tmp.items():
            load=d.get('consumption_forecast_mw') or d.get('consumption_forecast_daily_mw'); wind=d.get('wind_forecast_mw') or d.get('wind_forecast_daily_mw'); solar=d.get('solar_forecast_mw') or d.get('solar_forecast_daily_mw'); prod=d.get('production_forecast_mw')
            if load is not None and wind is not None:
                val=load-wind-(solar or 0); derived.append((fid,h,'residual_after_wind_solar_mw',val,'MW','fingrid'))
            if load is not None and prod is not None: derived.append((fid,h,'forecast_net_import_need_mw',load-prod,'MW','fingrid'))
        out += derived
        # Nord Pool latest price snapshot + calendar features. Prices only exist for published days.
        pr=c.execute("SELECT run_id FROM price_runs WHERE status IN ('ok','degraded') ORDER BY issue_time DESC LIMIT 1").fetchone()
        if pr:
            price_by=defaultdict(dict)
            for area,t,v in c.execute('SELECT area,valid_time,price_eur_mwh FROM market_prices WHERE run_id=?',(pr[0],)):
                price_by[hourkey(t)][area]=v
            for h,dct in price_by.items():
                for area,v in dct.items(): out.append((fid,h,'price_'+area.lower()+'_eur_mwh',float(v),'EUR/MWh','nordpool_public'))
                if 'FI' in dct and 'SE3' in dct: out.append((fid,h,'price_spread_fi_se3_eur_mwh',float(dct['FI']-dct['SE3']),'EUR/MWh','nordpool_public'))
        # Deterministic time features for all forecast hours.
        all_hours=sorted(set(x[1] for x in out))
        for h in all_hours:
            try: dt=datetime.fromisoformat(h);
            except Exception: continue
            out.append((fid,h,'hour_of_day',float(dt.hour),'','calendar'))
            out.append((fid,h,'day_of_week',float(dt.weekday()),'','calendar'))
            out.append((fid,h,'is_weekend',1.0 if dt.weekday()>=5 else 0.0,'','calendar'))
        status='ok' if out else 'error'
        c.execute('INSERT INTO feature_runs VALUES (?,?,?,?,?,?,?)',(fid,now.isoformat(),fr,wr,er,status,'v0.6.1 combined Fingrid + weather + Nord Pool + calendar; source-aware snapshots'))
        c.executemany('INSERT OR REPLACE INTO features_hourly VALUES (?,?,?,?,?,?)',out)
    print(f'[OK] feature run {fid}: {len(out)} feature-rivia')
    return fid,len(out)
