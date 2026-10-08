from __future__ import annotations
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
import json, os
from pathlib import Path

HELSINKI = ZoneInfo("Europe/Helsinki")
STATUS_FILE = Path(__file__).resolve().parent.parent / "output" / "forecast_status.json"
TARGETS = {"morning": (6, 15), "afternoon": (16, 15)}
# Scheduled runs use the current Helsinki issue window, not delayed cron identity.


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


def selected_slot(event, schedule, now, requested_slot="", already_published=None, force_republish=False):
    local = now.astimezone(HELSINKI)
    if event == "workflow_dispatch":
        slot = requested_slot.strip().lower()
        if slot not in TARGETS:
            return None
    elif event == "schedule":
        # A delayed cron must never publish yesterday's or the wrong slot's
        # forecast. Recover the CURRENT local slot if it has not been published.
        # The periodic watchdog cron retries until the publication succeeds.
        morning = local.replace(hour=6, minute=15, second=0, microsecond=0)
        afternoon = local.replace(hour=16, minute=15, second=0, microsecond=0)
        if local >= afternoon:
            slot = "afternoon"
        elif local >= morning:
            slot = "morning"
        else:
            return None
    else:
        return None

    if already_published == slot and not force_republish:
        return None
    return slot


if __name__ == "__main__":
    event = os.getenv("GITHUB_EVENT_NAME", "")
    schedule = os.getenv("GITHUB_EVENT_SCHEDULE", "")
    requested = os.getenv("FORECAST_REQUESTED_SLOT", "")
    force_republish = os.getenv("FORECAST_FORCE_REPUBLISH", "").strip().lower() in {"1", "true", "yes", "on"}
    now = datetime.now(timezone.utc)
    local = now.astimezone(HELSINKI)
    already = already_published_slot(STATUS_FILE, local.date())
    slot = selected_slot(
        event, schedule, now,
        requested_slot=requested,
        already_published=already,
        force_republish=force_republish,
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"run={'true' if slot else 'false'}\n")
        f.write(f"slot={slot or ''}\n")
    print(
        f"event={event}, schedule={schedule}, requested_slot={requested}, "
        f"force_republish={force_republish}, runner_helsinki={local.isoformat()}, "
        f"slot={slot}, already_published_today={already}"
    )
