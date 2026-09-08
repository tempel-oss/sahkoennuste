from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

def selected_slot(event, schedule, now):
    local = now.astimezone(ZoneInfo('Europe/Helsinki'))
    if event == 'workflow_dispatch':
        return 'morning' if local.hour < 16 or (local.hour == 16 and local.minute < 15) else 'afternoon'
    if event == 'schedule':
        for slot, hour in [('morning', 6), ('afternoon', 16)]:
            target = local.replace(hour=hour, minute=15, second=0, microsecond=0)
            if schedule.strip() == f'15 {target.astimezone(timezone.utc).hour} * * *':
                # A severely delayed morning event must not replace an afternoon forecast.
                if slot == 'morning' and (local.hour, local.minute) >= (16, 15):
                    return None
                return slot
    return None

if __name__ == '__main__':
    event = os.getenv('GITHUB_EVENT_NAME', '')
    schedule = os.getenv('GITHUB_EVENT_SCHEDULE', '')
    slot = selected_slot(event, schedule, datetime.now(timezone.utc))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
        f.write(f"run={'true' if slot else 'false'}\n")
        f.write(f"slot={slot or ''}\n")
    print(f'event={event}, schedule={schedule}, slot={slot}')
