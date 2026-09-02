from _bootstrap import *
from electricity_forecaster.completeness import check
ok,_=check(True)
raise SystemExit(0 if ok else 2)
