import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","src"))
from electricity_forecaster.config import load_env_file
load_env_file()

from electricity_forecaster.forecast_engine import make_forecast
from electricity_forecaster.diagnostics import build_diagnostics, build_changes
make_forecast()
print("Diagnostiikka:",build_diagnostics())
print("Muutosvertailu:",build_changes())
