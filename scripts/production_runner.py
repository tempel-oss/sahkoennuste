
from _bootstrap import *
from pathlib import Path
from datetime import datetime
import traceback, sys

from electricity_forecaster.monitor import record

ROOT=Path(__file__).resolve().parents[1]
LOGDIR=ROOT/"logs"; LOGDIR.mkdir(exist_ok=True)
stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
log_path=LOGDIR/f"production_{stamp}.log"

_original_stdout=sys.stdout
_original_stderr=sys.stderr
lf=log_path.open("w",encoding="utf-8")

class Tee:
    def __init__(self,*streams): self.streams=streams
    def write(self,s):
        for x in self.streams:
            x.write(s); x.flush()
    def flush(self):
        for x in self.streams: x.flush()

sys.stdout=Tee(_original_stdout,lf)
sys.stderr=Tee(_original_stderr,lf)

results=[]
exit_code=0

def step(name, critical, fn):
    global exit_code
    print(f"\n=== {name} ===")
    try:
        r=fn()
        print("[OK]",r if r is not None else "")
        results.append((name,"ok",""))
        return True,r
    except Exception as e:
        msg=f"{type(e).__name__}: {e}"
        status="error" if critical else "degraded"
        print("[VIRHE]" if critical else "[VAROITUS]",msg)
        traceback.print_exc()
        results.append((name,status,msg))
        if critical:
            exit_code=2
        try: record(name,status,msg)
        except Exception: pass
        return False,None

try:
    print("=== ELECTRICITY FORECASTER v1.3 PRODUCTION RUN ===")
    print("Aika:",datetime.now().isoformat(timespec="seconds"))

    from electricity_forecaster.ingest import ingest as fingrid
    from electricity_forecaster.price_ingest import ingest_prices
    from electricity_forecaster.weather_ingest import ingest_weather
    from electricity_forecaster.features import build_features
    from electricity_forecaster.completeness import check
    from electricity_forecaster.error_scoring import score_forecast_errors
    from electricity_forecaster.price_forecast_scoring import score_price_forecasts
    from electricity_forecaster.forecast_engine import make_forecast
    from electricity_forecaster.diagnostics import build_diagnostics,build_changes
    from electricity_forecaster.production_output import build_latest_outputs

    fingrid_ok,_=step("FINGRID",True,fingrid)
    step("NORDPOOL",False,ingest_prices)

    def entsoe():
        from electricity_forecaster.entsoe_ingest import ingest
        return ingest()
    step("ENTSO-E",False,entsoe)
    weather_ok,_=step("WEATHER",True,ingest_weather)
    ok_features,_=step("FEATURES",True,build_features)
    step("INPUT_ERROR_SCORING",False,score_forecast_errors)

    quality_ok=False
    issues=[]
    if ok_features and fingrid_ok and weather_ok:
        try:
            quality_ok,issues=check(True)
            print("\n=== DATA QUALITY ===")
            print("[OK]" if quality_ok else "[EI VALMIS]",
                  "; ".join(issues) if issues else "critical inputs available")
            results.append(("DATA_QUALITY","ok" if quality_ok else "error",
                            "" if quality_ok else "; ".join(issues)))
            if not quality_ok:
                exit_code=3
        except Exception as e:
            msg=f"{type(e).__name__}: {e}"
            print("[VIRHE] data quality:",msg)
            results.append(("DATA_QUALITY","error",msg))
            exit_code=3
    else:
        msg="keruuvaiheen kriittinen virhe"
        results.append(("DATA_QUALITY","error",msg))
        exit_code=3

    forecast_ok=False
    publish_ok=False
    if quality_ok:
        forecast_ok,_=step("PRICE_FORECAST",True,make_forecast)
    else:
        print("\n[OHITETTU] PRICE_FORECAST: kriittista dataa puuttuu.")

    if forecast_ok:
        step("DIAGNOSTICS",False,build_diagnostics)
        step("FORECAST_CHANGES",False,build_changes)

    step("PRICE_FORECAST_SCORING",False,score_price_forecasts)

    if forecast_ok:
        publish_ok,_=step("PUBLISH_OUTPUT",True,build_latest_outputs)

    if not forecast_ok or not publish_ok:
        if exit_code == 0:
            exit_code=4
        print("\n[EI JULKAISTA] Uutta ennustetta ei syntynyt kokonaan. "
              "Vanhaa output-tiedostoa ei saa tulkita taman ajon ennusteeksi.")

    print("\n=== YHTEENVETO ===")
    for name,status,msg in results:
        print(f"{name:24s} {status:9s} {msg}")
    print("Loki:",log_path)
    print("VALMIS." if exit_code == 0 else f"AJO EPAONNISTUI / VAJAA (exit {exit_code}).")
finally:
    try:
        sys.stdout.flush(); sys.stderr.flush()
    except Exception:
        pass
    sys.stdout=_original_stdout
    sys.stderr=_original_stderr
    lf.close()

raise SystemExit(exit_code)
