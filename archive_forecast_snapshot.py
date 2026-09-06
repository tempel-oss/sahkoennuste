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


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def append_index(index_path: Path, row: dict):
    index_path.parent.mkdir(parents=True, exist_ok=True)
    exists = index_path.exists()
    with index_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    p = argparse.ArgumentParser(
        description="Archive the latest production forecast by forecast origin."
    )
    p.add_argument("--root", default=".")
    p.add_argument(
        "--json-source",
        default=r"output\latest_forecast.json",
    )
    p.add_argument(
        "--html-source",
        default=r"output\latest_forecast.html",
    )
    args = p.parse_args()

    root = Path(args.root).resolve()
    json_source = root / args.json_source
    html_source = root / args.html_source

    if not json_source.exists():
        raise SystemExit(
            f"Archive skipped: forecast JSON not found: {json_source}"
        )

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(HELSINKI)

    # Scheduled runs are 06:15 and 16:15. The slot is intentionally based on
    # the actual run time, so a delayed morning run still remains identifiable.
    slot = "morning" if now_local.hour < 12 else "afternoon"
    stamp = now_local.strftime("%Y%m%d_%H%M%S")

    day_dir = (
        root
        / "data"
        / "forecast_archive"
        / now_local.strftime("%Y")
        / now_local.strftime("%m")
        / now_local.strftime("%d")
    )
    day_dir.mkdir(parents=True, exist_ok=True)

    json_dest = day_dir / f"forecast_{stamp}_{slot}.json"
    shutil.copy2(json_source, json_dest)

    html_dest = None
    if html_source.exists():
        html_dest = day_dir / f"forecast_{stamp}_{slot}.html"
        shutil.copy2(html_source, html_dest)

    meta = {
        "issue_time_utc": now_utc.isoformat(),
        "issue_time_local": now_local.isoformat(),
        "issue_slot": slot,
        "source_json": str(json_source.relative_to(root)),
        "archive_json": str(json_dest.relative_to(root)),
        "archive_html": (
            str(html_dest.relative_to(root)) if html_dest else None
        ),
        "json_sha256": sha256(json_dest),
    }

    meta_path = day_dir / f"forecast_{stamp}_{slot}.meta.json"
    meta_path.write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )

    append_index(
        root / "data" / "forecast_archive" / "index.csv",
        {
            "issue_time_utc": meta["issue_time_utc"],
            "issue_time_local": meta["issue_time_local"],
            "issue_slot": slot,
            "archive_json": meta["archive_json"],
            "archive_html": meta["archive_html"] or "",
            "json_sha256": meta["json_sha256"],
        },
    )

    print("FORECAST SNAPSHOT SAVED")
    print(f"slot: {slot}")
    print(f"json: {json_dest}")


if __name__ == "__main__":
    main()
