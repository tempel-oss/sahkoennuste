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
    if not data.get('forecast_run_id') or len(data.get('days', [])) != 11:
        raise RuntimeError('Incomplete D+2...D+12 forecast')
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
