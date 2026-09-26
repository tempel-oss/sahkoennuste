
from __future__ import annotations
import csv, json, math, sqlite3, statistics
from pathlib import Path
from .config import ROOT
from .db import connect, init_db

ML_DIR = ROOT / "data" / "ml"

def _r(x,n=2):
    return None if x is None else round(float(x),n)

def _metrics(rows):
    if not rows:
        return {"n":0,"mae_eur_mwh":None,"bias_eur_mwh":None,"rmse_eur_mwh":None,
                "baseline_mae_eur_mwh":None,"p10_p90_coverage":None,"skill_vs_baseline_pct":None}
    err=[float(r["error_eur_mwh"]) for r in rows]
    ae=[float(r["abs_error_eur_mwh"]) for r in rows]
    bae=[float(r["baseline_abs_error_eur_mwh"]) for r in rows]
    cov=[int(r["inside_p10_p90"]) for r in rows]
    mae=statistics.mean(ae)
    bmae=statistics.mean(bae)
    skill=((bmae-mae)/bmae*100.0) if bmae > 1e-9 else None
    return {
      "n":len(rows),"mae_eur_mwh":_r(mae),"bias_eur_mwh":_r(statistics.mean(err)),
      "rmse_eur_mwh":_r(math.sqrt(statistics.mean(e*e for e in err))),
      "baseline_mae_eur_mwh":_r(bmae),"p10_p90_coverage":_r(statistics.mean(cov),3),
      "skill_vs_baseline_pct":_r(skill,1)
    }

def quality_summary():
    init_db()
    with connect() as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("""SELECT forecast_run_id,target_time,horizon_days,error_eur_mwh,
                                 abs_error_eur_mwh,baseline_abs_error_eur_mwh,inside_p10_p90
                          FROM price_forecast_scores ORDER BY target_time""").fetchall()
        runs=c.execute("SELECT COUNT(DISTINCT forecast_run_id) FROM price_forecast_scores").fetchone()[0]
    by={}
    for h in range(2,13):
        by[str(h)]=_metrics([r for r in rows if int(r["horizon_days"])==h])
    weak=[]
    candidates=[]
    for h,m in by.items():
        if m["n"]>=12 and m["mae_eur_mwh"] is not None:
            candidates.append((m["mae_eur_mwh"],int(h),m))
    for _,h,m in sorted(candidates,reverse=True)[:3]:
        weak.append({"label":f"D+{h}","mae_eur_mwh":m["mae_eur_mwh"],
                     "bias_eur_mwh":m["bias_eur_mwh"],"coverage":m["p10_p90_coverage"],"n":m["n"]})
    overall=_metrics(rows)
    return {
      "overall":overall,"by_horizon":by,"weak_spots":weak,
      "scored_hours":overall["n"],"scored_forecast_runs":int(runs),
      "training_ready":overall["n"]>=1000 and runs>=20,
      "walk_forward_ready":overall["n"]>=1500 and runs>=30,
      "training_gate":"1000 scored hours + 20 scored forecast runs",
      "walk_forward_gate":"1500 scored hours + 30 scored forecast runs"
    }

def build_training_matrix():
    init_db(); ML_DIR.mkdir(parents=True,exist_ok=True)
    path=ML_DIR/"training_matrix.csv"
    with connect() as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("""SELECT s.forecast_run_id,r.issue_time,s.target_time,s.horizon_days,
                                 r.model_name,r.model_version,
                                 f.p10_eur_mwh,f.p50_eur_mwh,f.p90_eur_mwh,f.baseline_eur_mwh,
                                 f.load_est_mw,f.wind_est_mw,f.solar_est_mw,f.net_load_est_mw,
                                 s.actual_eur_mwh,s.error_eur_mwh,s.abs_error_eur_mwh,s.inside_p10_p90
                          FROM price_forecast_scores s
                          JOIN price_forecasts_hourly f
                            ON f.forecast_run_id=s.forecast_run_id AND f.target_time=s.target_time
                          JOIN price_forecast_runs r ON r.forecast_run_id=s.forecast_run_id
                          ORDER BY r.issue_time,s.target_time""").fetchall()
    fields=["forecast_run_id","issue_time","target_time","horizon_days","model_name","model_version",
            "p10_eur_mwh","p50_eur_mwh","p90_eur_mwh","baseline_eur_mwh","load_est_mw",
            "wind_est_mw","solar_est_mw","net_load_est_mw","actual_eur_mwh","error_eur_mwh",
            "abs_error_eur_mwh","inside_p10_p90"]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k:r[k] for k in fields})
    meta={"rows":len(rows),"status":"ready" if len(rows)>=1000 else "collecting",
          "leakage_policy":"Predictors are values stored at issue time; realized price is target only."}
    (ML_DIR/"training_matrix_meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[OK] ML training matrix: {len(rows)} rows")
    return meta

def walk_forward_baseline_report(folds=5):
    init_db(); ML_DIR.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("""SELECT r.issue_time,s.forecast_run_id,s.target_time,s.horizon_days,
                                 s.error_eur_mwh,s.abs_error_eur_mwh,
                                 s.baseline_abs_error_eur_mwh,s.inside_p10_p90
                          FROM price_forecast_scores s JOIN price_forecast_runs r
                          ON r.forecast_run_id=s.forecast_run_id
                          ORDER BY r.issue_time,s.target_time""").fetchall()
    run_ids=[]; seen=set()
    for r in rows:
        rid=r["forecast_run_id"]
        if rid not in seen:
            seen.add(rid); run_ids.append(rid)
    result={"status":"insufficient_data","forecast_runs":len(run_ids),"rows":len(rows),"folds":[]}
    if len(run_ids)>=6:
        nfold=min(folds,max(2,len(run_ids)//3))
        block=max(1,len(run_ids)//(nfold+1))
        out=[]
        for i in range(nfold):
            train_end=block*(i+1)
            ids=set(run_ids[train_end:min(len(run_ids),train_end+block)])
            test=[r for r in rows if r["forecast_run_id"] in ids]
            if not test: continue
            m=_metrics(test)
            out.append({"fold":i+1,"train_runs":train_end,"test_runs":len(ids),
                        "test_rows":m["n"],"p50_mae_eur_mwh":m["mae_eur_mwh"],
                        "baseline_mae_eur_mwh":m["baseline_mae_eur_mwh"],
                        "skill_vs_baseline_pct":m["skill_vs_baseline_pct"],
                        "bias_eur_mwh":m["bias_eur_mwh"],"coverage":m["p10_p90_coverage"]})
        result={"status":"ok","forecast_runs":len(run_ids),"rows":len(rows),"folds":out}
    (ML_DIR/"walk_forward_baseline.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[OK] Walk-forward baseline: {result['status']}, {len(result['folds'])} folds")
    return result
