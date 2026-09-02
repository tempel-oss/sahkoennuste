
from _bootstrap import *
from electricity_forecaster.production_output import build_latest_outputs
j,h,n=build_latest_outputs()
print(f"[OK] Julkaisutiedostot paivitetty: {n} paivaa")
print("JSON:",j)
print("HTML:",h)
