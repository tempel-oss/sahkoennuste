"""Exercise live capture on a SYNTHETIC origin in a disposable real-DB copy."""
import argparse
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from electricity_forecaster.issue_slots import migrate_issue_slots
from electricity_forecaster import shadow_store


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',type=Path,default=ROOT/'data/electricity_forecaster.sqlite3')
    ap.add_argument('--selection',type=Path,default=ROOT/'research_results/challenger_v2/selection.json')
    args=ap.parse_args()
    spec=json.loads(args.selection.read_text())
    with tempfile.TemporaryDirectory() as temp:
        with contextlib.closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True)) as source:
            with contextlib.closing(sqlite3.connect(str(Path(temp)/'smoke.sqlite3'))) as conn:
                source.backup(conn)
                migrate_issue_slots(conn)
                original=conn.execute("SELECT forecast_run_id,issue_slot FROM price_forecast_runs WHERE status='ok' ORDER BY issue_time DESC LIMIT 1").fetchone()
                stamp=datetime.now(timezone.utc).isoformat()
                test_id='SYNTHETIC-SMOKE-'+stamp
                slot=original[1] or 'afternoon'
                conn.execute('''INSERT INTO price_forecast_runs
                    (forecast_run_id,issue_time,model_name,model_version,status,issue_slot,issue_slot_source)
                    VALUES(?,?,'fundamental_baseline','0.7.1','ok',?,'explicit')''',(test_id,stamp,slot))
                conn.execute('''INSERT INTO price_forecasts_hourly
                    SELECT ?,target_time,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,baseline_eur_mwh,
                    load_est_mw,wind_est_mw,solar_est_mw,net_load_est_mw,drivers_json
                    FROM price_forecasts_hourly WHERE forecast_run_id=?''',(test_id,original[0]))
                conn.commit()
                result=shadow_store.capture(conn,test_id,spec)
                assert result['status']=='recorded',result
                assert result['forecast_count']>0,result
                again=shadow_store.capture(conn,test_id,spec)
                assert again['duplicate']
                n=shadow_store.score(conn)
                report=shadow_store.summary(conn)
                assert report['automatic_promotion'] is False
                print(json.dumps({'test':'synthetic_runtime_smoke_on_disposable_copy',
                                  'capture':result,'new_scores':n,'source_db_written':False,
                                  'production_champion_changed':False},indent=2))


if __name__=='__main__':
    main()
