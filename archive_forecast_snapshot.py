from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import argparse
import csv
import hashlib
import json
import shutil

HELSINKI = ZoneInfo("Europe/Helsinki")
SLOT_TIMES = {
    "morning": (6, 15),
    "afternoon": (16, 15),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _upsert_index(index_path: Path, row: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if index_path.exists():
        with index_path.open("r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    key = row["scheduled_issue_time_local"]
    rows = [r for r in rows if r.get("scheduled_issue_time_local") != key]
    rows.append(row)
    rows.sort(key=lambda r: r.get("scheduled_issue_time_local", ""))

    with index_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerows(rows)


def archive_snapshot(root: Path, slot: str,
                     json_source_rel: str = "output/latest_forecast.json",
                     html_source_rel: str = "output/latest_forecast.html") -> int:
    root = Path(root).resolve()
    json_source = root / Path(json_source_rel)
    html_source = root / Path(html_source_rel)

    if not json_source.exists():
        print(f"[VIRHE] Ennuste-JSON puuttuu: {json_source}")
        return 2

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(HELSINKI)

    hour, minute = SLOT_TIMES[slot]
    scheduled_local = now_local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    scheduled_utc = scheduled_local.astimezone(timezone.utc)

    day_dir = (
        root
        / "data"
        / "forecast_archive"
        / scheduled_local.strftime("%Y")
        / scheduled_local.strftime("%m")
        / scheduled_local.strftime("%d")
    )
    day_dir.mkdir(parents=True, exist_ok=True)

    code = scheduled_local.strftime("%H%M")
    base = f"forecast_{scheduled_local:%Y%m%d}_{code}_{slot}"

    json_dest = day_dir / f"{base}.json"
    shutil.copy2(json_source, json_dest)

    html_dest = None
    if html_source.exists():
        html_dest = day_dir / f"{base}.html"
        shutil.copy2(html_source, html_dest)

    source_mtime_local = datetime.fromtimestamp(
        json_source.stat().st_mtime, tz=timezone.utc
    ).astimezone(HELSINKI)

    meta = {
        "scheduled_issue_time_local": scheduled_local.isoformat(),
        "scheduled_issue_time_utc": scheduled_utc.isoformat(),
        "archive_time_local": now_local.isoformat(),
        "archive_time_utc": now_utc.isoformat(),
        "issue_slot": slot,
        "source_json": str(json_source.relative_to(root)),
        "source_json_mtime_local": source_mtime_local.isoformat(),
        "archive_json": str(json_dest.relative_to(root)),
        "archive_html": str(html_dest.relative_to(root)) if html_dest else None,
        "json_sha256": sha256(json_dest),
    }

    meta_path = day_dir / f"{base}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    _upsert_index(
        root / "data" / "forecast_archive" / "index.csv",
        {
            "scheduled_issue_time_local": meta["scheduled_issue_time_local"],
            "scheduled_issue_time_utc": meta["scheduled_issue_time_utc"],
            "archive_time_local": meta["archive_time_local"],
            "issue_slot": slot,
            "archive_json": meta["archive_json"],
            "archive_html": meta["archive_html"] or "",
            "json_sha256": meta["json_sha256"],
        },
    )

    print("[OK] Ennustesnapshot tallennettu.")
    print(f"Slot: {slot}")
    print(f"Issue: {scheduled_local:%Y-%m-%d %H:%M %Z}")
    print(f"JSON: {json_dest}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Archive one successful Electricity Forecaster production run."
    )
    p.add_argument("--root", default=".")
    p.add_argument(
        "--slot",
        choices=("morning", "afternoon"),
        required=True,
        help="Scheduled forecast origin.",
    )
    p.add_argument("--json-source", default="output/latest_forecast.json")
    p.add_argument("--html-source", default="output/latest_forecast.html")
    args = p.parse_args()

    return archive_snapshot(
        Path(args.root),
        args.slot,
        args.json_source,
        args.html_source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
