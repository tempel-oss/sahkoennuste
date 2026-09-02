
from _bootstrap import *
from electricity_forecaster.model_registry import model_status
s=model_status()
print("=== MALLIN TILA v1.1 ===")
c=s["champion"]; e=s["evaluation"]
print("Champion:",c["name"],c["version"])
print("Koulutettu ML:",c["trained_ml"])
print("Pisteytettyja tunteja:",e["scored_hours"])
print("Pisteytettyja ennusteajoja:",e["scored_forecast_runs"])
print("MAE EUR/MWh:",e["mae_eur_mwh"])
print("P10-P90 coverage:",e["p10_p90_coverage"])
print("Challenger-koulutus valmis:",s["challenger_training_ready"])
print("Portti:",s["training_gate"])
