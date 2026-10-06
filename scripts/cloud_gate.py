from __future__ import annotations
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo
import json, os
from pathlib import Path

HELSINKI = ZoneInfo("Europe/Helsinki")
STATUS_FILE = Path(__file__).resolve().parent.parent / "output" / "forecast_status.json"
TARGETS = {"morning": (6, 15), "afternoon": (16, 15)}
# GitHub documents that scheduled workflows may be delayed. A late backup cron
# must never become a production forecast hours after its intended issue time.
MAX_SCHEDULE_DELAY = timedelta(minutes=45)


def already_published_slot(status_path: Path, today_helsinki: date) -> str | None:
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    issue_time = data.get("forecast_issue_time")
    issue_slot = data.get("issue_slot")
    if not issue_time or issue_slot not in TARGETS:
        return None
    try:
        dt = datetime.fromisoformat(str(issue_time).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt.astimezone(HELSINKI).date() == today_helsinki:
        return issue_slot
    return None


def _scheduled_slot(schedule: str) -> str | None:
    # cloud_forecast.yml uses timezone: Europe/Helsinki, so github.event.schedule
    # is the local cron expression itself.
    s = schedule.strip()
    if s == "15 6 * * *":
        return "morning"
    if s == "15 16 * * *":
        return "afternoon"
    return None


def selected_slot(event, schedule, now, requested_slot="", already_published=None):
    local = now.astimezone(HELSINKI)
    slot = None

    if event == "workflow_dispatch":
        requested_slot = requested_slot.strip().lower()
        if requested_slot not in TARGETS:
            return None
        slot = requested_slot

    elif event == "schedule":
        slot = _scheduled_slot(schedule)
        if slot is None:
            return None
        hour, minute = TARGETS[slot]
        target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        delay = local - target
        # Reject early/mismatched and severely delayed cron deliveries. This is
        # intentionally strict: a stale run is worse than a clearly missing run,
        # because it can overwrite the correct issue slot and mislabel freshness.
        if delay < timedelta(minutes=-5) or delay > MAX_SCHEDULE_DELAY:
            return None

    else:
        return None

    if already_published == slot:
        return None
    return slot


if __name__ == "__main__":
    event = os.getenv("GITHUB_EVENT_NAME", "")
    schedule = os.getenv("GITHUB_EVENT_SCHEDULE", "")
    requested = os.getenv("FORECAST_REQUESTED_SLOT", "")
    now = datetime.now(timezone.utc)
    local = now.astimezone(HELSINKI)
    already = already_published_slot(STATUS_FILE, local.date())
    slot = selected_slot(
        event, schedule, now,
        requested_slot=requested,
        already_published=already,
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"run={'true' if slot else 'false'}\n")
        f.write(f"slot={slot or ''}\n")
    print(
        f"event={event}, schedule={schedule}, requested_slot={requested}, "
        f"runner_helsinki={local.isoformat()}, slot={slot}, "
        f"already_published_today={already}"
    )
