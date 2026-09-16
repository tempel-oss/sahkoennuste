from pathlib import Path
from datetime import datetime
import json
import os

ROOT = Path(__file__).resolve().parents[1]

def validate(root, started):
    required = ['index.html', 'latest_forecast.html', 'latest_forecast.json', 'manifest.webmanifest', 'sw.js']
    for name in required:
        path = root / 'output' / name
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError('Missing or empty output: ' + name)
    data = json.loads((root / 'output/latest_forecast.json').read_text(encoding='utf-8'))
    slot = data.get('issue_slot')
    if slot not in ('morning', 'afternoon'):
        raise RuntimeError('Missing or invalid issue_slot')
    expected_horizons = list(range(1, 12)) if slot == 'morning' else list(range(2, 13))
    actual_horizons = [int(x.get('d_plus', -1)) for x in data.get('days', [])]
    if not data.get('forecast_run_id') or actual_horizons != expected_horizons:
        raise RuntimeError(
            f'Incomplete {slot} forecast: expected {expected_horizons}, got {actual_horizons}'
        )
    if any(x.get('value_type') != 'forecast' for x in data.get('days', [])):
        raise RuntimeError('Forecast day missing value_type=forecast')
    published = data.get('published_day_ahead', [])
    expected_published = [0] if slot == 'morning' else [0, 1]
    actual_published = [int(x.get('d_plus', -1)) for x in published]
    if actual_published != expected_published:
        raise RuntimeError(
            f'Wrong published day-ahead set for {slot}: {actual_published}'
        )
    if any(x.get('value_type') != 'day_ahead' for x in published):
        raise RuntimeError('Published day missing value_type=day_ahead')
    for field in ['forecast_issue_time', 'generated_at_utc']:
        if datetime.fromisoformat(data[field].replace('Z', '+00:00')).timestamp() < started:
            raise RuntimeError('Stale forecast: ' + field)
    for name in ['index.html', 'latest_forecast.html']:
        if data['forecast_run_id'] not in (root / 'output' / name).read_text(encoding='utf-8'):
            raise RuntimeError('HTML and JSON forecast mismatch: ' + name)
    return data

if __name__ == '__main__':
    data = validate(ROOT, float(os.environ['FORECAST_STARTED_AT']))
    print('[OK] fresh forecast', data['forecast_run_id'], data['forecast_issue_time'])
