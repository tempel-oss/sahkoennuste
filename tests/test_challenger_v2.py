import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import numpy as np
import pandas as pd
from electricity_forecaster import db, challenger_v2 as ml, shadow_store as shadow
from electricity_forecaster.issue_slots import migrate_issue_slots


def database():
    con = sqlite3.connect(':memory:')
    con.executescript(db.SCHEMA)
    migrate_issue_slots(con)
    return con


def add_run(con, rid, issue, targets, slot='morning', source='explicit'):
    con.execute('''INSERT INTO price_forecast_runs
        (forecast_run_id,issue_time,model_name,model_version,status,issue_slot,issue_slot_source)
        VALUES(?,?,'fundamental_baseline','0.7.1','ok',?,?)''', (rid, issue.isoformat(), slot, source))
    for target in targets:
        value = 50 + 10*np.sin(target.hour*np.pi/12)
        con.execute('''INSERT INTO price_forecasts_hourly VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (rid, target.isoformat(), max(1, (target.date()-issue.date()).days),
                     value-20, value, value+20, value-2, 10000, 2500, 500, 7000, '{}'))


def add_price(con, rid, target, issue, value=58):
    con.execute('INSERT OR IGNORE INTO price_runs(run_id,issue_time,source,status) VALUES(?,?,?,?)', (rid, issue.isoformat(), 'test', 'ok'))
    # Explicit columns make the fixture independent of the market table order.
    con.execute('''INSERT INTO market_prices(run_id,area,valid_time,end_time,price_eur_mwh,source)
                   VALUES(?,?,?,?,?,'test')''', (rid, 'FI', target.isoformat(),
                                         (target+pd.Timedelta(hours=1)).isoformat(), value))


def history(con):
    for i in range(40):
        issue = pd.Timestamp('2026-01-01T04:00:00Z') + pd.Timedelta(hours=12*i)
        targets = [issue.floor('D')+pd.Timedelta(days=2,hours=h) for h in range(72)]
        add_run(con, 'history-'+str(i), issue, targets)
    for target in pd.date_range('2026-01-01', periods=26*24, freq='h', tz='UTC'):
        published = target.floor('D')-pd.Timedelta(days=1)+pd.Timedelta(hours=12)
        add_price(con, 'prices-'+target.strftime('%Y%m%d'), target, published,
                  58+10*np.sin(target.hour*np.pi/12))
    con.commit()


def spec(candidate='hgb_robust_025'):
    return {'algorithm_version': 'v02-1', 'candidate': candidate,
            'candidate_spec': ml.CANDIDATES[candidate], 'features': ml.BASE_FEATURES,
            'shadow_only': True, 'automatic_promotion': False, 'enabled': True}


class IssueOriginTests(unittest.TestCase):
    def test_migration_is_idempotent_and_never_uses_wall_clock(self):
        c=sqlite3.connect(':memory:');c.executescript(db.SCHEMA)
        issue=pd.Timestamp('2026-10-12T13:45:00Z')
        c.execute("INSERT INTO price_forecast_runs VALUES(?,?,?,? ,NULL,'ok',NULL,NULL)",
                  ('delayed',issue.isoformat(),'fundamental_baseline','0.7.1'))
        for h in range(1,12):
            c.execute('INSERT INTO price_forecasts_hourly VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      ('delayed',str(h),h,1,2,3,2,None,None,None,None,'{}'))
        migrate_issue_slots(c);migrate_issue_slots(c)
        self.assertEqual(c.execute('SELECT issue_slot,issue_slot_source FROM price_forecast_runs').fetchone(),
                         ('morning','inferred_horizon'))
        c.close()

    def test_missing_legacy_origin_stays_unknown(self):
        f=ml.features(pd.DataFrame([{'forecast_run_id':'x','target_time':'2026-10-13T00:00Z',
            'issue_time':'2026-10-12T13:00Z','p50_eur_mwh':50,'horizon_days':1}]))
        self.assertEqual(f.issue_slot.iloc[0], 'unknown')
        self.assertEqual(f.issue_slot_unknown.iloc[0], 1)

    def test_explicit_delayed_origin_and_dst_are_preserved(self):
        f=ml.features(pd.DataFrame([{'forecast_run_id':'x','target_time':'2026-10-25T01:00Z',
            'issue_time':'2026-10-24T13:00Z','p50_eur_mwh':50,'horizon_days':1,'issue_slot':'morning'}]))
        self.assertEqual(f.issue_slot.iloc[0],'morning')
        self.assertEqual(f.issue_slot_afternoon.iloc[0],0)


class PriceTests(unittest.TestCase):
    def test_complete_weighted_hour_first_snapshot_and_publication_time(self):
        rows=[]
        for run,published,values in [('early','2026-01-01T12:00Z',[10,20,30,40]),
                                     ('revision','2026-01-02T12:00Z',[100]*4)]:
            for j,v in enumerate(values):
                start=pd.Timestamp('2026-01-02T00:00Z')+pd.Timedelta(minutes=15*j)
                rows.append(dict(run_id=run,issue_time=published,valid_time=start,
                                 end_time=start+pd.Timedelta(minutes=15),price_eur_mwh=v))
        a=ml.hourly_actuals(pd.DataFrame(rows))
        self.assertEqual(a.actual_eur_mwh.iloc[0],25)
        self.assertEqual(a.actual_available_at.iloc[0],pd.Timestamp('2026-01-02T01:00Z'))
        self.assertEqual(a.first_published_at.iloc[0],pd.Timestamp('2026-01-01T12:00Z'))
        self.assertTrue(ml.hourly_actuals(pd.DataFrame(rows[:3])).empty)

    def test_training_is_purged_by_availability_as_well_as_target(self):
        t=pd.Timestamp('2026-01-03T00:00Z')
        f=pd.DataFrame({'issue_time':[t-pd.Timedelta(days=2)]*3,
                        'target_time':[t-pd.Timedelta(days=1),t,t-pd.Timedelta(days=1)],
                        'actual_available_at':[t-pd.Timedelta(hours=1),t,t+pd.Timedelta(hours=1)]})
        self.assertEqual(len(ml.training_before(f,t)),1)


class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        self.c=database();history(self.c)
        self.now=datetime(2026,2,1,13,tzinfo=timezone.utc)
        self.issue=pd.Timestamp(self.now)
        self.known=pd.Timestamp('2026-02-02T00:00Z')
        self.future=pd.Timestamp('2026-02-03T00:00Z')
        add_run(self.c,'live',self.issue,[self.known,self.future])
        add_price(self.c,'known',self.known,pd.Timestamp('2026-02-01T12:00Z'))
        self.c.commit()

    def tearDown(self):
        self.c.close()

    def test_capture_before_actuals_skip_known_targets_no_overwrite_and_score_once(self):
        result=shadow.capture(self.c,'live',spec(),now=self.now)
        self.assertEqual(result['status'],'recorded',result)
        self.assertEqual(result['forecast_count'],1)
        self.assertEqual(result['skipped_known_price'],1)
        first=self.c.execute('SELECT * FROM shadow_forecasts').fetchone()
        again=shadow.capture(self.c,'live',spec('median_bias'),now=self.now)
        self.assertTrue(again['duplicate'])
        self.assertEqual(self.c.execute('SELECT * FROM shadow_forecasts').fetchone(),first)
        cutoff,maximum=self.c.execute('SELECT training_cutoff_utc,train_max_actual_available_at FROM shadow_models').fetchone()
        self.assertLess(pd.Timestamp(maximum),pd.Timestamp(cutoff))
        self.assertEqual(shadow.score(self.c,now=self.now),0)
        add_price(self.c,'future',self.future,pd.Timestamp('2026-02-02T12:00Z'))
        self.assertEqual(shadow.score(self.c,now=datetime(2026,2,4,tzinfo=timezone.utc)),1)
        self.assertEqual(shadow.score(self.c,now=datetime(2026,2,4,tzinfo=timezone.utc)),0)
        report=shadow.summary(self.c,now=datetime(2026,2,4,tzinfo=timezone.utc))
        self.assertEqual(report['overall']['n'],1)
        self.assertEqual(report['by_slot']['morning']['n'],1)
        self.assertFalse(report['automatic_promotion'])
        self.assertFalse(report['assessment_ready'])

    def test_old_origin_cannot_be_backfilled(self):
        result=shadow.capture(self.c,'live',spec(),now=datetime(2026,2,2,tzinfo=timezone.utc))
        self.assertEqual(result['status'],'not_collected')
        self.assertIn('hindsight',result['message'])
        self.assertEqual(shadow.summary(self.c,now=datetime(2026,2,2,tzinfo=timezone.utc))['status'],'degraded')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM shadow_forecasts').fetchone()[0],0)

    def test_later_import_of_previously_published_price_is_not_prospective(self):
        shadow.capture(self.c,'live',spec('median_bias'),now=self.now)
        add_price(self.c,'late-import',self.future,pd.Timestamp('2026-02-01T12:00Z'))
        self.assertEqual(shadow.score(self.c,now=datetime(2026,2,4,tzinfo=timezone.utc)),0)

    def test_missing_features_remain_finite_and_correction_is_bounded(self):
        train=ml.load_training_data(self.c,self.issue)
        train['wind_est_mw']=np.nan
        fitted=ml.fit_candidate(train,'hgb_robust_025')
        prediction,correction=ml.predict_candidate(fitted,train)
        self.assertTrue(np.isfinite(prediction).all())
        self.assertLessEqual(float(max(abs(correction))),7.5)


class ProductionIntegrationTests(unittest.TestCase):
    def test_missing_ml_dependency_is_recorded_without_hiding_the_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db,'DB_PATH',Path(temp)/'database.sqlite3'):
                db.init_db()
                with db.connect() as c:
                    issue=pd.Timestamp.now(tz='UTC')
                    add_run(c,'failed-collection',issue,[issue+pd.Timedelta(days=2)])
                with patch.object(shadow,'capture',side_effect=ImportError('ML dependency missing')):
                    with self.assertRaises(RuntimeError):
                        shadow.collect_current('failed-collection')
                with db.connect() as c:
                    r=shadow.summary(c)
                    self.assertEqual(r['status'],'degraded')
                    self.assertEqual(r['collection_status']['not_collected'],1)

    def test_generation_and_rendering_use_saved_origin_even_if_environment_changes(self):
        from electricity_forecaster import forecast_engine as engine, production_output as output
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls(2026,1,30,13,tzinfo=timezone.utc).astimezone(tz or timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db,'DB_PATH',Path(temp)/'database.sqlite3'), \
                 patch.object(output,'OUTPUT_DIR',Path(temp)/'output'), \
                 patch.object(engine,'datetime',Clock), \
                 patch.dict(os.environ,{'FORECAST_ISSUE_SLOT':'morning'}):
                db.init_db()
                with db.connect() as c:
                    c.execute("INSERT INTO feature_runs(feature_run_id,created_at,status) VALUES('f','2026-01-30T12:00:00+00:00','ok')")
                    add_price(c,'prices',pd.Timestamp('2026-01-30T00:00Z'),pd.Timestamp('2026-01-29T12:00Z'))
                rid,_=engine.make_forecast()
                with db.connect() as c:
                    self.assertEqual(c.execute('SELECT issue_slot,issue_slot_source FROM price_forecast_runs WHERE forecast_run_id=?',(rid,)).fetchone(),('morning','explicit'))
                os.environ['FORECAST_ISSUE_SLOT']='afternoon'
                jp,_,_=output.build_latest_outputs()
                payload=json.loads(jp.read_text())
                self.assertEqual(payload['issue_slot'],'morning')
                self.assertEqual(payload['issue_slot_source'],'explicit')
                self.assertEqual([r['d_plus'] for r in payload['days']],list(range(1,12)))
                self.assertIn('Challenger v0.2',(Path(temp)/'output/diagnostics.html').read_text())


class ResearchTests(unittest.TestCase):
    def test_holdout_labels_cannot_change_selection(self):
        spec_module=importlib.util.spec_from_file_location('v2_research',ROOT/'research/challenger_v2_research.py')
        module=importlib.util.module_from_spec(spec_module);spec_module.loader.exec_module(module)
        c=database();history(c)
        frame=ml.load_training_data(c,pd.Timestamp('2026-02-01T00:00Z'))
        origins=frame[['forecast_run_id','issue_time']].drop_duplicates().sort_values('issue_time')
        boundary=origins.iloc[int(len(origins)*.8)].issue_time
        changed=frame.copy();changed.loc[changed.issue_time>=boundary,'actual_eur_mwh']+=1000
        changed['residual_target_eur_mwh']=changed.actual_eur_mwh-changed.p50_eur_mwh
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ml,'load_training_data',return_value=frame):
                a=module.research(c,Path(tmp)/'a',pd.Timestamp('2026-02-01T00:00Z'))
            with patch.object(ml,'load_training_data',return_value=changed):
                b=module.research(c,Path(tmp)/'b',pd.Timestamp('2026-02-01T00:00Z'))
        self.assertEqual(a['selection_sha256'],b['selection_sha256'])
        self.assertEqual(a['selected_candidate'],b['selected_candidate'])
        for fold in a['development_folds']:
            self.assertLess(pd.Timestamp(fold['train_max_actual_available_at']),pd.Timestamp(fold['test_issue_start']))
        self.assertFalse(a['production_champion_changed'])
        c.close()


if __name__=='__main__':
    unittest.main()
