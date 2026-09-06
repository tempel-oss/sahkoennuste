
from _bootstrap import *
from electricity_forecaster.forecast_quality import quality_summary,build_training_matrix,walk_forward_baseline_report
q=quality_summary(); m=build_training_matrix(); w=walk_forward_baseline_report()
print("=== ML READINESS v1.4 ===")
print("Scored hours:",q["scored_hours"])
print("Scored runs:",q["scored_forecast_runs"])
print("Training ready:",q["training_ready"])
print("Walk-forward ready:",q["walk_forward_ready"])
print("Matrix rows:",m["rows"])
print("Walk-forward:",w["status"])
