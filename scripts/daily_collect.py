from _bootstrap import *
from electricity_forecaster.ingest import ingest as fingrid_ingest
from electricity_forecaster.weather_ingest import ingest_weather
from electricity_forecaster.features import build_features
from electricity_forecaster.monitor import record
from electricity_forecaster.price_ingest import ingest_prices
from electricity_forecaster.error_scoring import score_forecast_errors
from electricity_forecaster.price_forecast_scoring import score_price_forecasts
from electricity_forecaster.completeness import check
from electricity_forecaster.forecast_engine import make_forecast

print('=== 1/9 Fingrid ===')
try: fingrid_ingest(); record('FINGRID','ok','collection completed')
except Exception as e: print('[VIRHE]',e); record('FINGRID','error',str(e))
print('\n=== 2/9 Nord Pool hintadata ===')
try:
    n=ingest_prices(); record('NORDPOOL','ok' if n else 'degraded',f'{n} rows')
except Exception as e: print('[VAROITUS]',e); record('NORDPOOL','degraded',str(e))
print('\n=== 3/9 ENTSO-E (best effort) ===')
try:
    from electricity_forecaster.entsoe_ingest import ingest
    r=ingest(); bad=sum(1 for v in r.values() if v < 0)
    record('ENTSO-E','degraded' if bad else 'ok',f'collection completed; failed series={bad}')
except Exception as e: print('[VAROITUS] ENTSO-E ohitettiin:',e); record('ENTSO-E','degraded',str(e))
print('\n=== 4/9 Saa ===')
try: ingest_weather(); record('WEATHER','ok','collection completed')
except Exception as e: print('[VAROITUS]',e); record('WEATHER','degraded',str(e))
print('\n=== 5/9 Featuret ===')
try: build_features(); record('FEATURES','ok','combined features built')
except Exception as e: print('[VIRHE]',e); record('FEATURES','error',str(e))
print('\n=== 6/9 Syotedatan ennustevirheet ===')
try: score_forecast_errors()
except Exception as e: print('[VAROITUS]',e)
print('\n=== 7/9 Datan taydellisyys ===')
ok,issues=check(True); record('DATA_QUALITY','ok' if ok else 'degraded','; '.join(issues) if issues else 'critical inputs available')
print('\n=== 8/9 Hintennuste D+2...D+12 ===')
if ok:
    try: make_forecast(); record('PRICE_FORECAST','ok','fundamental v0.7 forecast archived')
    except Exception as e: print('[VIRHE]',e); record('PRICE_FORECAST','error',str(e))
else: print('[OHITETTU] kriittista dataa puuttuu')
print('\n=== 9/9 Vanhojen hintennusteiden pisteytys ===')
try: score_price_forecasts()
except Exception as e: print('[VAROITUS]',e)
print('\nVALMIS.')
