
import shutil
from pathlib import Path
old=Path(input("Anna nykyisen v0.8.3 electricity_forecaster-kansion polku: ").strip().strip('"'))
new=Path(__file__).resolve().parents[1]
if not old.exists():
    print("Polkua ei loydy:",old); raise SystemExit(1)
if (old/".env").exists():
    shutil.copy2(old/".env",new/".env")
    print("[OK] .env kopioitu.")
db=old/"data"/"electricity_forecaster.sqlite3"
if db.exists():
    dst=new/"data"/"electricity_forecaster.sqlite3"
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(db,dst)
    print("[OK] SQLite-tietokanta kopioitu.")
else:
    print("[VAROITUS] SQLite-tietokantaa ei loytynyt.")
print("[OK] Paivitys v0.9:aan valmis.")
