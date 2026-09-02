from _bootstrap import *
from electricity_forecaster.completeness import check
from electricity_forecaster.forecast_engine import make_forecast
ok,issues=check(False)
if not ok:
    print('ENNUSTETTA EI TEHTY: kriittista dataa puuttuu:')
    for x in issues: print(' -',x)
    raise SystemExit(2)
make_forecast()
