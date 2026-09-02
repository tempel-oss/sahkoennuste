from __future__ import annotations
from datetime import datetime, timezone, timedelta
from .db import connect, init_db

CRITICAL_FORECAST=['consumption_forecast_mw','wind_forecast_mw','production_forecast_mw']
CRITICAL_ACTUAL=['consumption_actual_mw','wind_actual_mw']

def _count(c,table,metric,after):
    return c.execute(f'SELECT COUNT(*) FROM {table} WHERE metric=? AND valid_time>=?',(metric,after)).fetchone()[0]

def check(verbose=True):
    init_db(); now=datetime.now(timezone.utc); after_actual=(now-timedelta(hours=36)).isoformat(); after_fc=(now-timedelta(hours=2)).isoformat()
    issues=[]; info=[]
    with connect() as c:
        fr=c.execute("SELECT run_id FROM forecast_runs WHERE source='fingrid' ORDER BY issue_time DESC LIMIT 1").fetchone(); fr=fr[0] if fr else None
        for m in CRITICAL_FORECAST:
            n=c.execute('SELECT COUNT(*) FROM forecasts WHERE run_id=? AND metric=?',(fr,m)).fetchone()[0] if fr else 0
            info.append((m,n,'forecast')); 
            if n==0: issues.append('PUUTTUU: '+m)
        for m in CRITICAL_ACTUAL:
            n=_count(c,'actuals',m,after_actual); info.append((m,n,'actual'))
            if n==0:
                backup='wind_realtime_mw' if m=='wind_actual_mw' else None
                nb=_count(c,'actuals',backup,after_actual) if backup else 0
                if nb: info.append((backup,nb,'backup'))
                else: issues.append('PUUTTUU: '+m)
        np=c.execute("SELECT COUNT(*) FROM market_prices WHERE area='FI'").fetchone()[0]
        info.append(('FI_day_ahead_price',np,'price'))
        if np==0: issues.append('PUUTTUU: FI day-ahead price')
        wr=c.execute("SELECT COUNT(*) FROM weather_series WHERE metric='wind_speed_100m_ms'").fetchone()[0]
        info.append(('weather_wind_100m',wr,'weather'))
        if wr==0: issues.append('PUUTTUU: weather_wind_100m')
        ens=c.execute("SELECT COUNT(*) FROM weather_series WHERE metric='wind_speed_100m_ms_p50'").fetchone()[0]
        info.append(('weather_ensemble_wind_p50',ens,'weather'))
        if ens==0: issues.append('PUUTTUU: weather ensemble')
    if verbose:
        print('=== DATAN TAYDELLISYYSTARKISTUS v0.6.1 ===')
        for m,n,k in info: print(f'{k:10} {m:38} {n:6}')
        print()
        if issues:
            print('EI VALMIS ML-MALLILLE:')
            for x in issues: print(' -',x)
        else:
            print('OK: kriittiset datalajit ovat saatavilla. Ensimmainen mallivaihe voidaan aloittaa.')
    return not issues,issues
