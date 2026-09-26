from __future__ import annotations

from pathlib import Path
from datetime import datetime
import argparse
import py_compile
import shutil
import subprocess


def replace_exact(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found < count:
        raise RuntimeError(
            f"{path}: expected at least {count} occurrence(s), found {found}. "
            "The local file differs from the GitHub main version this patch was built against."
        )
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def replace_all(path: Path, old: str, new: str, expected_min: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found < expected_min:
        raise RuntimeError(f"{path}: expected at least {expected_min} occurrence(s), found {found}.")
    path.write_text(text.replace(old, new), encoding="utf-8")


def backup_files(project: Path, rels: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = project / "patch_backups" / f"issue_slot_display_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    for rel in rels:
        src = project / rel
        if src.exists():
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return backup


def restore_backup(project: Path, backup: Path, rels: list[Path]) -> None:
    for rel in rels:
        src = backup / rel
        if src.exists():
            dst = project / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def must_contain(path: Path, needle: str) -> None:
    if needle not in path.read_text(encoding="utf-8"):
        raise RuntimeError(f"{path}: verification failed, missing {needle!r}")


def main() -> int:
    print("[VIRHE] Tama on alkuperainen (v1) issue-slot-display-patch, jossa on tunnettu bugi:")
    print("  ankkurihaku saattoi sotkea sisennyksen/rivinvaihdot kohdetiedostoissa.")
    print("Se on jo sovellettu tahan projektiin korjatulla versiolla v3.2:")
    print("  apply_issue_slot_display_patch_v3_2.py")
    print("Tata (v1) skriptia ei pida enaa ajaa. Se sailyy vain historiallisena viitteena.")
    return 2


def _original_main_v1_do_not_use() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    project = Path(args.root).resolve()

    rel_forecast = Path("src/electricity_forecaster/forecast_engine.py")
    rel_output = Path("src/electricity_forecaster/production_output.py")
    rel_quality = Path("src/electricity_forecaster/forecast_quality.py")
    rel_validate = Path("scripts/cloud_validate.py")
    rel_workflow = Path(".github/workflows/cloud_forecast.yml")
    rel_wrapper = Path("36_AJA_JA_ARKISTOI.bat")

    required = [rel_forecast, rel_output, rel_quality, rel_validate, rel_workflow]
    for rel in required:
        if not (project / rel).is_file():
            print(f"[VIRHE] Required file missing: {project / rel}")
            return 2

    tracked = required + [rel_wrapper]
    backup = backup_files(project, tracked)
    print(f"[OK] Backup: {backup}")

    try:
        # forecast_engine.py
        p = project / rel_forecast
        text = p.read_text(encoding="utf-8")
        if "def resolve_issue_slot(" not in text:
            # Current GitHub/main has "import json", "import math", "import statistics".
            # Insert os robustly instead of assuming math immediately follows a fixed block.
            current = p.read_text(encoding="utf-8")
            if "\nimport os\n" not in "\n" + current:
                if "import math\n" not in current:
                    raise RuntimeError(f"{p}: import insertion point 'import math' not found")
                p.write_text(current.replace("import math\n", "import math\nimport os\n", 1), encoding="utf-8")
            replace_exact(
                p,
                'MODEL_VERSION = "0.7.1"\n',
                'MODEL_VERSION = "0.7.1"\n\n'
                'def resolve_issue_slot(now_utc: datetime | None = None) -> str:\n'
                '    forced = os.getenv("FORECAST_ISSUE_SLOT", "").strip().lower()\n'
                '    if forced in {"morning", "afternoon"}:\n'
                '        return forced\n'
                '    local = (now_utc or datetime.now(timezone.utc)).astimezone(HELSINKI)\n'
                '    return "morning" if (local.hour, local.minute) < (12, 0) else "afternoon"\n\n'
                'def forecast_horizon_for_slot(slot: str) -> tuple[int, int]:\n'
                '    if slot == "morning":\n'
                '        return 1, 11\n'
                '    if slot == "afternoon":\n'
                '        return 2, 12\n'
                '    raise ValueError(f"Unknown forecast issue slot: {slot!r}")\n',
            )
            replace_exact(
                p,
                "    now_utc = datetime.now(timezone.utc).replace(microsecond=0)\n"
                "    now_local = now_utc.astimezone(HELSINKI)\n"
                '    run_id = now_utc.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]\n',
                "    now_utc = datetime.now(timezone.utc).replace(microsecond=0)\n"
                "    now_local = now_utc.astimezone(HELSINKI)\n"
                "    issue_slot = resolve_issue_slot(now_utc)\n"
                "    horizon_start, horizon_end = forecast_horizon_for_slot(issue_slot)\n"
                '    run_id = now_utc.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]\n',
            )
            text = p.read_text(encoding="utf-8")
            fixed_loop = "for day_h in range(2, 13):"
            if text.count(fixed_loop) != 2:
                raise RuntimeError(
                    f"{p}: expected exactly 2 D+2..D+12 loops, found {text.count(fixed_loop)}"
                )
            p.write_text(
                text.replace(
                    fixed_loop,
                    "for day_h in range(horizon_start, horizon_end + 1):",
                ),
                encoding="utf-8",
            )
            replace_exact(
                p,
                "        # Anchor the residual sensitivity against D+2 if tomorrow features are unavailable.\n"
                '        anchor_candidates = [r["net_load"] for r in hourly if r["horizon"] == 2]\n',
                "        # Anchor residual sensitivity against the first forecast day of this issue slot.\n"
                '        anchor_candidates = [r["net_load"] for r in hourly if r["horizon"] == horizon_start]\n',
            )
            replace_exact(
                p,
                '"method": "Fingrid direct D+2/D+3 where available; weather-calibrated extension thereafter"',
                '"method": "Fingrid direct near-term forecasts where available; weather-calibrated extension thereafter"',
            )
            replace_exact(
                p,
                '                    "First archived fundamental forecast. Not a trained ML/Champion model."))\n',
                '                    f"First archived fundamental forecast. Not a trained ML/Champion model. "\n'
                '                    f"Issue slot: {issue_slot}; horizons D+{horizon_start}...D+{horizon_end}."))\n',
            )
            replace_exact(
                p,
                '    print(f"[OK] Ennusteajo {run_id}: {len(hourly_rows_db)} tuntiennustetta, {len(daily_rows_db)} paivaennustetta")\n'
                '    print("Malli: fundamental_baseline v0.7 - EI viela koulutettu ML/Champion-malli")\n',
                '    print(f"[OK] Ennusteajo {run_id}: {len(hourly_rows_db)} tuntiennustetta, {len(daily_rows_db)} paivaennustetta")\n'
                '    print(f"Issue slot: {issue_slot}; horisontit D+{horizon_start}...D+{horizon_end}")\n'
                '    print("Malli: fundamental_baseline v0.7 - EI viela koulutettu ML/Champion-malli")\n',
            )
        else:
            print("[INFO] forecast_engine.py already patched")

        # production_output.py
        p = project / rel_output
        text = p.read_text(encoding="utf-8")
        if '"issue_slot":issue_slot' not in text:
            replace_exact(
                p,
                "from .forecast_engine import HELSINKI\n",
                "from .forecast_engine import HELSINKI, resolve_issue_slot, forecast_horizon_for_slot\n",
            )
            replace_exact(
                p,
                "def _published_prices(con):\n"
                "    now_local=datetime.now(timezone.utc).astimezone(HELSINKI)\n"
                "    wanted=[now_local.date(),now_local.date()+timedelta(days=1)]\n",
                "def _published_prices(con, issue_slot, issue_time_utc=None):\n"
                "    now_local=(issue_time_utc or datetime.now(timezone.utc)).astimezone(HELSINKI)\n"
                '    wanted=[now_local.date()] if issue_slot=="morning" else [now_local.date(),now_local.date()+timedelta(days=1)]\n',
            )
            replace_exact(
                p,
                '          "date":d.isoformat(),"d_plus":idx,"published":bool(prices),\n',
                '          "date":d.isoformat(),"d_plus":idx,"value_type":"day_ahead","published":bool(prices),\n',
            )
            replace_exact(
                p,
                '    run_id=meta["forecast_run_id"]; prev=_previous_run(con,run_id)\n',
                '    run_id=meta["forecast_run_id"]; prev=_previous_run(con,run_id)\n'
                '    issue_dt=_parse_dt(meta["issue_time"])\n'
                '    issue_slot=resolve_issue_slot(issue_dt)\n',
            )
            replace_exact(
                p,
                '          "date":td,"d_plus":int(r["horizon_days"]),\n',
                '          "date":td,"d_plus":int(r["horizon_days"]),"value_type":"forecast",\n',
            )
            replace_exact(
                p,
                '      "forecast_run_id":run_id,"forecast_issue_time":meta["issue_time"],\n',
                '      "forecast_run_id":run_id,"forecast_issue_time":meta["issue_time"],"issue_slot":issue_slot,\n',
            )
            replace_exact(
                p,
                '      "published_day_ahead":_published_prices(con),"days":days\n',
                '      "published_day_ahead":_published_prices(con,issue_slot,issue_dt),"days":days\n',
            )
            replace_exact(
                p,
                "def _render_html(p):\n    pub=[]\n",
                "def _value_badge(item):\n"
                '    value_type=item.get("value_type")\n'
                '    if value_type=="day_ahead":\n'
                '        return ("published","Julkaistu") if item.get("published",True) else ("pending","Ei julkaistu")\n'
                '    if value_type=="forecast":\n'
                '        return ("forecast","Ennuste")\n'
                '    return ("pending","Tuntematon")\n\n'
                "def _render_html(p):\n"
                '    forecast_days=p.get("days",[])\n'
                "    if forecast_days:\n"
                '        hmin=min(int(d["d_plus"]) for d in forecast_days)\n'
                '        hmax=max(int(d["d_plus"]) for d in forecast_days)\n'
                '        forecast_heading=f"D+{hmin}–D+{hmax} ennuste"\n'
                "    else:\n"
                '        forecast_heading="Ennuste"\n'
                "    pub=[]\n",
            )
            replace_exact(
                p,
                '        tag="D0" if x["d_plus"]==0 else "D+1"\n',
                '        tag="D0" if x["d_plus"]==0 else "D+1"\n'
                '        badge_cls,badge_text=_value_badge(x)\n',
            )
            badge_old = '<div class="dayname">{dlabel}<small>{_weekday_fi(x["date"])}</small></div>'
            badge_new = '<div class="dayname">{dlabel}<small>{_weekday_fi(x["date"])}</small><span class="value-badge {badge_cls}">{badge_text}</span></div>'
            replace_all(p, badge_old, badge_new, expected_min=2)

            replace_exact(
                p,
                '        ch=d.get("change_from_previous"); delta=float(ch["delta"]) if ch and ch.get("delta") is not None else None\n',
                '        badge_cls,badge_text=_value_badge(d)\n'
                '        ch=d.get("change_from_previous"); delta=float(ch["delta"]) if ch and ch.get("delta") is not None else None\n',
            )
            row_old = 'rows.append(f\'\'\'<tr><td><b>D+{d["d_plus"]}</b><small>{_weekday_fi(d["date"])}</small></td>'
            row_new = 'rows.append(f\'\'\'<tr><td><b>D+{d["d_plus"]}</b><small>{_weekday_fi(d["date"])}</small><span class="value-badge {badge_cls}">{badge_text}</span></td>'
            replace_exact(p, row_old, row_new)

            mobile_old = 'mobile.append(f\'\'\'<article class="forecast-day"><div><b>D+{d["d_plus"]}</b><small>{_weekday_fi(d["date"])}</small></div>'
            mobile_new = 'mobile.append(f\'\'\'<article class="forecast-day"><div><b>D+{d["d_plus"]}</b><small>{_weekday_fi(d["date"])}</small><span class="value-badge {badge_cls}">{badge_text}</span></div>'
            replace_exact(p, mobile_old, mobile_new)

            replace_exact(
                p,
                ".card{{background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:14px 16px}}",
                ".value-badge{{display:inline-block;margin-top:5px;border-radius:999px;padding:3px 7px;font-size:.64rem;font-weight:800;letter-spacing:.02em;text-transform:uppercase}}"
                ".value-badge.published{{background:#e8f7ee;color:#147b43}}"
                ".value-badge.forecast{{background:#eaf1ff;color:#0e4fc4}}"
                ".value-badge.pending{{background:#fff4df;color:#b56b0b}}"
                ".card{{background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:14px 16px}}",
            )
            replace_exact(
                p,
                '<h2 class="section-title">D+2–D+12 ennuste <span class="info">i</span></h2>',
                '<h2 class="section-title">{forecast_heading} <span class="info">i</span></h2>',
            )
            replace_exact(
                p,
                '<h2 class="section-title">12 päivän hintakehitys <span class="info">i</span></h2>',
                '<h2 class="section-title">Hintakehitys <span class="info">i</span></h2>',
            )
        else:
            print("[INFO] production_output.py already patched")

        # quality summary includes morning D+1
        p = project / rel_quality
        text = p.read_text(encoding="utf-8")
        if "for h in range(2,13):" in text:
            p.write_text(text.replace("for h in range(2,13):", "for h in range(1,13):", 1), encoding="utf-8")

        # cloud validator
        p = project / rel_validate
        text = p.read_text(encoding="utf-8")
        old = (
            "    if not data.get('forecast_run_id') or len(data.get('days', [])) != 11:\n"
            "        raise RuntimeError('Incomplete D+2...D+12 forecast')\n"
        )
        if old in text:
            new = (
                "    slot = data.get('issue_slot')\n"
                "    if slot not in ('morning', 'afternoon'):\n"
                "        raise RuntimeError('Missing or invalid issue_slot')\n"
                "    expected_horizons = list(range(1, 12)) if slot == 'morning' else list(range(2, 13))\n"
                "    actual_horizons = [int(x.get('d_plus', -1)) for x in data.get('days', [])]\n"
                "    if not data.get('forecast_run_id') or actual_horizons != expected_horizons:\n"
                "        raise RuntimeError(f'Incomplete {slot} forecast: expected {expected_horizons}, got {actual_horizons}')\n"
                "    if any(x.get('value_type') != 'forecast' for x in data.get('days', [])):\n"
                "        raise RuntimeError('Forecast day missing value_type=forecast')\n"
                "    published = data.get('published_day_ahead', [])\n"
                "    expected_published = [0] if slot == 'morning' else [0, 1]\n"
                "    actual_published = [int(x.get('d_plus', -1)) for x in published]\n"
                "    if actual_published != expected_published:\n"
                "        raise RuntimeError(f'Wrong published day-ahead set for {slot}: {actual_published}')\n"
                "    if any(x.get('value_type') != 'day_ahead' for x in published):\n"
                "        raise RuntimeError('Published day missing value_type=day_ahead')\n"
            )
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
        elif "expected_horizons" not in text:
            raise RuntimeError(f"{p}: validation block not recognized")

        # cloud workflow passes gate-selected slot
        p = project / rel_workflow
        text = p.read_text(encoding="utf-8")
        if "FORECAST_ISSUE_SLOT:" not in text:
            old = (
                "          ENTSOE_API_TOKEN: ${{ secrets.ENTSOE_API_TOKEN }}\n"
                '          PYTHONUNBUFFERED: "1"\n'
            )
            new = old + "          FORECAST_ISSUE_SLOT: ${{ needs.gate.outputs.slot }}\n"
            if old not in text:
                raise RuntimeError(f"{p}: workflow env block not recognized")
            p.write_text(text.replace(old, new, 1), encoding="utf-8")

        # local wrapper passes explicit scheduled slot, if present
        p = project / rel_wrapper
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if 'set "FORECAST_ISSUE_SLOT=%~1"' not in text:
                marker = "echo === ELECTRICITY FORECASTER %~1 ===\n"
                if marker in text:
                    p.write_text(
                        text.replace(marker, marker + 'set "FORECAST_ISSUE_SLOT=%~1"\n', 1),
                        encoding="utf-8",
                    )
                else:
                    print("[VAROITUS] 36_AJA_JA_ARKISTOI.bat insertion point not recognized")
        else:
            print("[INFO] 36_AJA_JA_ARKISTOI.bat not present; cloud patch still complete")

        # syntax and structure checks
        for rel in [rel_forecast, rel_output, rel_quality, rel_validate]:
            py_compile.compile(str(project / rel), doraise=True)

        must_contain(project / rel_forecast, 'return 1, 11')
        must_contain(project / rel_forecast, 'return 2, 12')
        must_contain(project / rel_output, '"value_type":"day_ahead"')
        must_contain(project / rel_output, '"value_type":"forecast"')
        must_contain(project / rel_output, '{forecast_heading}')
        must_contain(project / rel_output, 'def _value_badge(item):')
        must_contain(project / rel_validate, "expected_horizons")
        must_contain(project / rel_workflow, "FORECAST_ISSUE_SLOT:")

        if (project / ".git").exists():
            r = subprocess.run(
                ["git", "diff", "--check"],
                cwd=project,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                raise RuntimeError("git diff --check failed:\n" + r.stdout + r.stderr)

        print("")
        print("PATCH OK")
        print("Morning 06:15:   D0 day_ahead + D+1...D+11 forecast")
        print("Afternoon 16:15: D0/D+1 day_ahead + D+2...D+12 forecast")
        print("JSON: explicit value_type")
        print("HTML: Julkaistu / Ennuste badges")
        print("Cloud/local issue slot: explicit")
        print(f"Backup: {backup}")
        return 0

    except Exception as exc:
        print(f"[VIRHE] {type(exc).__name__}: {exc}")
        print("[INFO] Restoring originals...")
        restore_backup(project, backup, tracked)
        print(f"[OK] Restored from {backup}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
