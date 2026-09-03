
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if not os.getenv("FINGRID_API_KEY","").strip():
    print("[VIRHE] FINGRID_API_KEY GitHub Secret puuttuu.")
    raise SystemExit(10)
print("=== ELECTRICITY FORECASTER v1.3 CLOUD RUNNER ===")
raise SystemExit(subprocess.call([sys.executable,str(ROOT/"scripts"/"production_runner.py")],cwd=str(ROOT)))
