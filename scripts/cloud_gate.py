
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

event=os.getenv("GITHUB_EVENT_NAME","")
schedule=os.getenv("GITHUB_EVENT_SCHEDULE","")
run=False
if event=="workflow_dispatch":
    run=True
elif event=="schedule":
    now=datetime.now(timezone.utc)
    local=now.astimezone(ZoneInfo("Europe/Helsinki"))
    target=local.replace(hour=16,minute=15,second=0,microsecond=0)
    expected=f"15 {target.astimezone(timezone.utc).hour} * * *"
    run=schedule.strip()==expected
reason=f"event={event}, schedule={schedule}, run={run}"
with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
    f.write(f"run={'true' if run else 'false'}\n")
    f.write(f"reason={reason}\n")
print(reason)
