
import json, sqlite3
from .db import connect, init_db

VAT = 1.255
EURMWH_TO_SNTKWH_VAT = VAT / 10.0

def _connect():
    con=connect()
    con.row_factory=sqlite3.Row
    return con

def _latest_runs(con, limit=2):
    return con.execute("""
      SELECT forecast_run_id,issue_time,model_name,model_version,feature_run_id
      FROM price_forecast_runs
      WHERE status='ok'
      ORDER BY issue_time DESC
      LIMIT ?
    """,(limit,)).fetchall()

def _daily(con, run_id):
    return con.execute("""
      SELECT forecast_run_id,target_date,horizon_days,
             p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,baseline_eur_mwh,
             min_p50_eur_mwh,max_p50_eur_mwh,
             cheapest_3h,expensive_3h,risk_level,drivers_json
      FROM price_forecasts_daily
      WHERE forecast_run_id=?
      ORDER BY horizon_days
    """,(run_id,)).fetchall()

def _features(con, feature_run_id, target_date):
    if not feature_run_id:
        return {}
    rows=con.execute("""
      SELECT feature_name,AVG(value) value,MAX(unit) unit
      FROM features_hourly
      WHERE feature_run_id=? AND substr(valid_time,1,10)=?
      GROUP BY feature_name
    """,(feature_run_id,target_date)).fetchall()
    return {r["feature_name"]:(float(r["value"]),r["unit"]) for r in rows}

def _gv(m,*names):
    for n in names:
        if n in m and m[n][0] is not None:
            return float(m[n][0])
    return None

def build_diagnostics():
    init_db()
    con=_connect()
    runs=_latest_runs(con,1)
    if not runs:
        con.close()
        return {"ok":False,"error":"price_forecast_runs-taulussa ei ole onnistunutta ennusteajoa."}
    meta=runs[0]
    run_id=meta["forecast_run_id"]
    feature_run_id=meta["feature_run_id"]
    daily=_daily(con,run_id)
    if not daily:
        con.close()
        return {"ok":False,"error":"price_forecasts_daily-taulussa ei ole uusimman ajon paivaennusteita."}

    con.execute("DELETE FROM forecast_diagnostics WHERE run_id=?",(run_id,))
    con.execute("DELETE FROM uncertainty_components WHERE run_id=?",(run_id,))
    n=0
    for r in daily:
        td=r["target_date"]; h=int(r["horizon_days"])
        f=_features(con,feature_run_id,td)

        consumption=_gv(f,"consumption_forecast_mw","load_forecast_mw")
        wind=_gv(f,"wind_forecast_mw","wind_forecast_daily_mw")
        solar=_gv(f,"solar_forecast_mw","solar_forecast_daily_mw")
        production=_gv(f,"production_forecast_mw")
        temp=_gv(f,"weather_load_temp_c")
        wind100=_gv(f,"weather_wind100_ms")
        windunc=_gv(f,"weather_wind_uncertainty_ms")
        fi_se1=_gv(f,"fi_se1_intraday_capacity_mw")
        se1_fi=_gv(f,"se1_fi_intraday_capacity_mw")
        fi_se3=_gv(f,"fi_se3_intraday_capacity_mw")

        residual = consumption - wind - (solar or 0.0) if consumption is not None and wind is not None else None
        net_import = consumption - production if consumption is not None and production is not None else None

        items={
          "p10_price":(r["p10_eur_mwh"]*EURMWH_TO_SNTKWH_VAT,"snt/kWh","paivaennuste"),
          "p50_price":(r["p50_eur_mwh"]*EURMWH_TO_SNTKWH_VAT,"snt/kWh","paivaennuste"),
          "p90_price":(r["p90_eur_mwh"]*EURMWH_TO_SNTKWH_VAT,"snt/kWh","paivaennuste"),
          "baseline_price":(r["baseline_eur_mwh"]*EURMWH_TO_SNTKWH_VAT,"snt/kWh","baseline"),
          "consumption_forecast":(consumption,"MW","paivakeskiarvo"),
          "wind_forecast":(wind,"MW","paivakeskiarvo"),
          "solar_forecast":(solar,"MW","paivakeskiarvo"),
          "production_forecast":(production,"MW","paivakeskiarvo"),
          "residual_load":(residual,"MW","kulutus-tuuli-aurinko"),
          "net_import_need":(net_import,"MW","kulutus-tuotanto"),
          "temperature":(temp,"C","paivakeskiarvo"),
          "wind_100m":(wind100,"m/s","paivakeskiarvo"),
          "wind_uncertainty":(windunc,"m/s","ensemble spread"),
          "fi_se1_capacity":(fi_se1,"MW","paivakeskiarvo"),
          "se1_fi_capacity":(se1_fi,"MW","paivakeskiarvo"),
          "fi_se3_capacity":(fi_se3,"MW","paivakeskiarvo"),
        }
        try:
            drivers=json.loads(r["drivers_json"] or "{}")
            if isinstance(drivers,dict):
                for k,v in drivers.items():
                    if isinstance(v,(int,float)):
                        items["driver_"+str(k)]=(float(v),"","forecast_engine driver")
        except Exception:
            pass

        for name,(val,unit,note) in items.items():
            if val is None: continue
            con.execute("""INSERT INTO forecast_diagnostics
              (run_id,target_date,horizon_day,component,value,unit,note)
              VALUES(?,?,?,?,?,?,?)""",(run_id,td,h,name,float(val),unit,note))
            n+=1

        p10=r["p10_eur_mwh"]*EURMWH_TO_SNTKWH_VAT
        p90=r["p90_eur_mwh"]*EURMWH_TO_SNTKWH_VAT
        total=max(0.0,(p90-p10)/2)
        share=0.30+min(0.35,max(0,h-2)*0.03)
        if windunc is not None:
            share += min(0.20,max(0,windunc)*0.025)
        share=max(0.20,min(0.80,share))
        weather=total*share
        model=total-weather
        con.execute("""INSERT INTO uncertainty_components
          (run_id,target_date,weather_component,model_component,total_component,unit)
          VALUES(?,?,?,?,?,?)""",(run_id,td,weather,model,total,"snt/kWh"))
    con.commit(); con.close()
    return {"ok":True,"run_id":run_id,"feature_run_id":feature_run_id,"days":len(daily),"diagnostic_rows":n}

def build_changes():
    init_db()
    con=_connect()
    runs=_latest_runs(con,2)
    if len(runs)<2:
        con.close()
        return {"ok":True,"count":0,"message":"Vain yksi onnistunut ennusteajo."}
    cur,prev=runs[0],runs[1]
    curid=cur["forecast_run_id"]; previd=prev["forecast_run_id"]
    a={r["target_date"]:r for r in _daily(con,curid)}
    b={r["target_date"]:r for r in _daily(con,previd)}
    con.execute("DELETE FROM forecast_changes WHERE run_id=?",(curid,))
    n=0
    for td,r in a.items():
        if td not in b: continue
        old=b[td]
        for metric,col in [("p10","p10_eur_mwh"),("p50","p50_eur_mwh"),("p90","p90_eur_mwh")]:
            nv=float(r[col])*EURMWH_TO_SNTKWH_VAT
            ov=float(old[col])*EURMWH_TO_SNTKWH_VAT
            con.execute("""INSERT INTO forecast_changes
              (run_id,prev_run_id,target_date,metric,old_value,new_value,delta,note)
              VALUES(?,?,?,?,?,?,?,?)""",(curid,previd,td,metric,ov,nv,nv-ov,"snt/kWh sis. ALV"))
            n+=1
    con.commit(); con.close()
    return {"ok":True,"run_id":curid,"prev_run_id":previd,"count":n}
