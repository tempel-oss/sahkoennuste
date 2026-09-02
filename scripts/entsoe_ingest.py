from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from electricity_forecaster.entsoe_ingest import ingest

result=ingest()
failed=[k for k,v in result.items() if v < 0]
print("\nValmis.")
if failed:
    print("Epaonnistuneet:",", ".join(failed))
    sys.exit(2)
