from pathlib import Path
import shutil, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from electricity_forecaster.db import init_db

env = ROOT / ".env"
example = ROOT / ".env.example"
if not env.exists():
    shutil.copyfile(example, env)
    print("Luotiin .env-tiedosto.")
else:
    print(".env on jo olemassa; sita ei muutettu.")
init_db()
print("SQLite-tietokanta valmis:", ROOT / "data" / "electricity_forecaster.sqlite3")
print("Tarkista .env: FINGRID_API_KEY ja ENTSOE_API_TOKEN.")
