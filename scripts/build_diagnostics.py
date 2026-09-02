import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","src"))
from electricity_forecaster.config import load_env_file
load_env_file()

from electricity_forecaster.diagnostics import build_diagnostics, build_changes
print(build_diagnostics())
print(build_changes())
