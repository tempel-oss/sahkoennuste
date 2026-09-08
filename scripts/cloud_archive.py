"""Archive the validated cloud output with its scheduled origin and actual issue time."""
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import argparse
import hashlib
import json
import shutil

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', required=True, choices=['morning', 'afternoon'])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root/'output/latest_forecast.json').read_text(encoding='utf-8'))
    issue = datetime.fromisoformat(data['forecast_issue_time'].replace('Z','+00:00')).astimezone(ZoneInfo('Europe/Helsinki'))
    scheduled = issue.replace(hour=6 if args.slot == 'morning' else 16, minute=15, second=0, microsecond=0)
    target = root/'data/forecast_archive'/issue.strftime('%Y/%m/%d')
    target.mkdir(parents=True, exist_ok=True)
    base = f'forecast_{scheduled:%Y%m%d_%H%M}_{args.slot}'
    for ext in ['json','html']:
        shutil.copy2(root/f'output/latest_forecast.{ext}',target/f'{base}.{ext}')
    meta = dict(issue_slot=args.slot, scheduled_issue_time_local=scheduled.isoformat(),
                forecast_issue_time=data['forecast_issue_time'], forecast_run_id=data['forecast_run_id'],
                archive_time_utc=datetime.now(timezone.utc).isoformat(),
                json_sha256=hashlib.sha256((target/f'{base}.json').read_bytes()).hexdigest())
    (target/f'{base}.meta.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print('[OK] archived',base)
