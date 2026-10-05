from __future__ import annotations
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
import json, os
from pathlib import Path

STATUS_FILE = Path(__file__).resolve().parent.parent / 'output' / 'forecast_status.json'


def already_published_slot(status_path: Path, today_helsinki: date) -> str | None:
    """Return the issue_slot already published for the given Helsinki calendar
    date according to the committed output/forecast_status.json, or None.

    HUOM (ks. dokumentin Q-kohta): lisatty koska GitHubin oma schedule-cron on
    alkanut laukeamaan jopa 4-7h myohassa (GitHubin oma, vahvistettu,
    tunnettu, tama kirjoitushetkella korjaamaton infrastruktuuribugi - ei
    mitaan tekemista tamam repon koodin kanssa). Tama vika yksinaan sai aikaan
    sen etta "aamun" tai "iltapaivan" ennuste julkaistiin satunnaisena
    ajankohtana (esim. klo 12:48) alkuperaisen klo 6:15/16:15 sijaan. Koska
    korjaus lisaa rinnakkaisen, luotettavan paikallisen laukaisimen (Windows
    Task Scheduler + "gh workflow run", ks. trigger_cloud_forecast.ps1) TAMAN
    rikkinaisen cronin paalle (varalle, siina tapauksessa etta GitHub joskus
    korjaa oman ajastimensa), pitaa estaa etta sama aamu-/iltapaivaslotti
    julkaistaan kahdesti samana paivana - kerran ajallaan ulkoisesta
    laukaisimesta klo 6:15/16:15, ja kerran myohemmin kun GitHubin oma
    myohastynyt cron vihdoin laukeaa ja silti tasmaa paivan DST-tilaan.
    """
    try:
        data = json.loads(status_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    issue_time = data.get('forecast_issue_time')
    issue_slot = data.get('issue_slot')
    if not issue_time or not issue_slot:
        return None
    try:
        dt = datetime.fromisoformat(issue_time)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    published_date = dt.astimezone(ZoneInfo('Europe/Helsinki')).date()
    if published_date == today_helsinki:
        return issue_slot
    return None


def selected_slot(event, schedule, now, already_published=None):
    local = now.astimezone(ZoneInfo('Europe/Helsinki'))
    slot = None
    if event == 'workflow_dispatch':
        slot = 'morning' if local.hour < 16 or (local.hour == 16 and local.minute < 15) else 'afternoon'
    elif event == 'schedule':
        for candidate_slot, hour in [('morning', 6), ('afternoon', 16)]:
            target = local.replace(hour=hour, minute=15, second=0, microsecond=0)
            if schedule.strip() == f'15 {target.astimezone(timezone.utc).hour} * * *':
                # A severely delayed morning event must not replace an afternoon forecast.
                if candidate_slot == 'morning' and (local.hour, local.minute) >= (16, 15):
                    return None
                slot = candidate_slot
                break
    if slot is None:
        return None
    # Idempotency guard (ks. yllaoleva HUOM): jos tama slotti on jo
    # julkaistu tanaan (riippumatta siita, tuliko aiempi julkaisu tasta
    # samasta tai eri tapahtumalahteesta), ei ajeta uudelleen.
    if already_published is not None and slot == already_published:
        return None
    return slot


if __name__ == '__main__':
    event = os.getenv('GITHUB_EVENT_NAME', '')
    schedule = os.getenv('GITHUB_EVENT_SCHEDULE', '')
    now = datetime.now(timezone.utc)
    today_helsinki = now.astimezone(ZoneInfo('Europe/Helsinki')).date()
    already = already_published_slot(STATUS_FILE, today_helsinki)
    slot = selected_slot(event, schedule, now, already_published=already)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
        f.write(f"run={'true' if slot else 'false'}\n")
        f.write(f"slot={slot or ''}\n")
    print(f'event={event}, schedule={schedule}, slot={slot}, already_published_today={already}')
