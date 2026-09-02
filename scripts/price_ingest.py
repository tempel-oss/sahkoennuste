from _bootstrap import *
from electricity_forecaster.price_ingest import ingest_prices
from electricity_forecaster.monitor import record
try:
    n=ingest_prices(); record('NORDPOOL','ok' if n else 'degraded',f'{n} rows')
except Exception as e:
    print('[VAROITUS]',e); record('NORDPOOL','degraded',str(e))
