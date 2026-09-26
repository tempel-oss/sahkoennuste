import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile

import joblib
import numpy as np
import pandas as pd
import sklearn

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'train_residual_challenger_v1.py'
py_compile.compile(str(SCRIPT), doraise=True)
spec = importlib.util.spec_from_file_location('challenger', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Uneven splits, excess folds, non-default indices, and preserved dtypes/order.
for n, folds, minimum in [(21, 5, 8), (10, 20, 8), (30, 1, 8), (31, 6, 8)]:
    runs = pd.DataFrame({'forecast_run_id': [f'r{i}' for i in range(n)],
                         'issue_time': pd.date_range('2026-01-01', periods=n, tz='UTC')})
    runs = runs.iloc[::-1].copy()
    before = runs.copy(deep=True)
    blocks = m._fold_blocks(runs, folds, minimum)
    expected = runs.sort_values('issue_time').reset_index(drop=True).iloc[max(minimum, n // 2):]
    assert all(isinstance(b, pd.DataFrame) for b in blocks)
    pd.testing.assert_frame_equal(pd.concat(blocks), expected)
    sizes = [len(x) for x in np.array_split(np.arange(len(expected)), min(folds, len(expected)))]
    assert [len(b) for b in blocks] == sizes
    blocks[0].iloc[0, 0] = 'changed'
    pd.testing.assert_frame_equal(runs, before)
for n, folds in [(9, 5), (21, 0)]:
    runs = pd.DataFrame({'issue_time': pd.date_range('2026-01-01', periods=n)})
    try:
        m._fold_blocks(runs, folds, 8)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Expected original validation error')

with tempfile.TemporaryDirectory(dir=HERE) as tmp:
    root = Path(tmp)
    shutil.copy2(SCRIPT, root / SCRIPT.name)
    rows = []
    for i in range(21):
        issue = pd.Timestamp('2026-01-01T04:00:00Z') + pd.Timedelta(hours=12*i)
        for lead in range(1, 97):
            target = issue + pd.Timedelta(hours=lead)
            price = 50 + 10 * np.sin(target.hour * np.pi / 12)
            rows.append(dict(forecast_run_id=f'run-{i:02}', issue_time=issue,
                             target_time=target, horizon_days=(lead-1)//24+1,
                             p50_eur_mwh=price, actual_eur_mwh=price+8,
                             p10_eur_mwh=price-20, p90_eur_mwh=price+20,
                             baseline_eur_mwh=price-2, load_est_mw=10000,
                             wind_est_mw=2500, solar_est_mw=500, net_load_est_mw=7000))
    matrix = root / 'synthetic.csv'
    pd.DataFrame(rows).to_csv(matrix, index=False)
    env = dict(os.environ, OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, str(root / SCRIPT.name), '--matrix', str(matrix),
                             '--no-rebuild-matrix'], capture_output=True, text=True,
                            encoding='utf-8', env=env, timeout=180)
    print(result.stdout)
    assert result.returncode == 0, result.stderr
    out = root / 'data/ml/challenger_residual_hgb_v1'
    for name in ['model.joblib', 'report.json', 'report.html', 'metadata.json', 'walk_forward_predictions.csv']:
        assert (out / name).stat().st_size > 0
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'shadow_only'
    assert report['promotion']['automatic'] is False
    assert len(report['walk_forward']['folds']) == 5
    assert report['data']['rows'] == 2016
    predictions = pd.read_csv(out / 'walk_forward_predictions.csv')
    assert len(predictions) == 1056
    assert not predictions.duplicated(['forecast_run_id', 'target_time']).any()
    assert np.isfinite(predictions['challenger_p50_eur_mwh']).all()
    np.testing.assert_allclose(predictions.challenger_p50_eur_mwh,
                               predictions.p50_eur_mwh + predictions.residual_pred_eur_mwh)
    df = m._load_matrix(matrix)
    for fold in report['walk_forward']['folds']:
        start = pd.Timestamp(fold['test_issue_start'])
        train = df[(df.issue_time < start) & (df.target_time < start)]
        assert fold['train_rows'] == len(train)
        assert fold['train_runs'] == train.forecast_run_id.nunique()
    saved = joblib.load(out / 'model.joblib')
    assert np.isfinite(saved['pipeline'].predict(df[saved['features']])).all()
    assert report['walk_forward']['overall']['challenger']['mae_eur_mwh'] < 0.01
print(f'PASS: syntax, fold regression cases, full CLI, 5 folds, reports, model reload. '
      f'NumPy {np.__version__}; pandas {pd.__version__}; scikit-learn {sklearn.__version__}')
