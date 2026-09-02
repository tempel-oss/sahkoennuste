from pathlib import Path
import argparse, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from electricity_forecaster.ingest import ingest

p = argparse.ArgumentParser()
p.add_argument("--dataset", action="append", help="Datasetin nimi; voidaan antaa useita kertoja")
a = p.parse_args()
result = ingest(a.dataset)
failed = [k for k,v in result.items() if v < 0]
print("\nValmis.")
if failed:
    print("Epaonnistuneet:", ", ".join(failed))
    sys.exit(2)
