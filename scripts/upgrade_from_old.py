
import shutil
from pathlib import Path
old=Path(input("Anna vanhan version electricity_forecaster-kansion polku: ").strip().strip('"'))
new=Path(__file__).resolve().parents[1]
if not old.exists():
    print("Polkua ei loydy:",old); raise SystemExit(1)
if (old/".env").exists():
    shutil.copy2(old/".env",new/".env")
db=old/"data"/"electricity_forecaster.sqlite3"
if db.exists():
    target=new/"data"/"electricity_forecaster.sqlite3"
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(db,target)
    print("[OK] Tietokanta kopioitu.")
else:
    print("[VAROITUS] Tietokantaa ei loytynyt.")
print("[OK] Paivitys valmis.")
