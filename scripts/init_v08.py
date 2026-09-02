import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","src"))
from electricity_forecaster.config import load_env_file
load_env_file()

from electricity_forecaster.db import init_db
init_db()
print("[OK] v0.8.3 skeema valmis.")
