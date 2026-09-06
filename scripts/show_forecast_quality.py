
from _bootstrap import *
from electricity_forecaster.forecast_quality import quality_summary
q=quality_summary(); o=q["overall"]
print("=== ENNUSTELAATU v1.4 ===")
print("n:",o["n"],"MAE:",o["mae_eur_mwh"],"Bias:",o["bias_eur_mwh"],
      "RMSE:",o["rmse_eur_mwh"],"Coverage:",o["p10_p90_coverage"],
      "Skill vs baseline %:",o["skill_vs_baseline_pct"])
for h,m in q["by_horizon"].items():
    if m["n"]:
        print(f"D+{h}: n={m['n']} MAE={m['mae_eur_mwh']} bias={m['bias_eur_mwh']} coverage={m['p10_p90_coverage']}")
