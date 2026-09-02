from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from electricity_forecaster.fingrid import FingridClient

print("Testataan Fingrid API -yhteytta...")
try:
    client = FingridClient()
    now = datetime.now(timezone.utc)
    payload, rows = client.fetch(74, now - timedelta(hours=2), now)
    print("\nOK - Fingrid API toimii.")
    print("Dataset 74 (Suomen sahkontuotanto)")
    print("Havaintoja:", len(rows))
    if rows:
        print("Viimeisin aika:", rows[-1].start_time)
        print("Viimeisin arvo:", rows[-1].value, "MW")
except Exception as exc:
    print("\nTESTI EPAONNISTUI:")
    print(exc)
    sys.exit(1)
