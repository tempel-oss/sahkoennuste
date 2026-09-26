from __future__ import annotations

from pathlib import Path
from datetime import datetime
import argparse
import py_compile
import re
import shutil
import subprocess

PATCH_VERSION = "v3.1-whitespace-hotfix"


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


def regex_once(text: str, pattern: str, repl, label: str, flags=0) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise RuntimeError(f"{label}: pattern not found")
    print(f"[OK] {label}")
    return new


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise RuntimeError(f"{label}: missing {needle!r}")


def patch_forecast_engine(path: Path) -> None:
    print("[PATCH] forecast_engine.py")
    text = path.read_text(encoding="utf-8")

    if not re.search(r"(?m)^import os\s*$", text):
        text = regex_once(
            text,
            r"(?m)^(import math\s*)$",
            r"\1\nimport os",
            "forecast_engine: add import os",
        )

    if "def resolve_issue_slot(" not in text:
        helper_lines = [
            "def resolve_issue_slot(now_utc: datetime | None = None) -> str:",
            "    # Explicit 06:15/16:15 forecast origin; env wins over clock fallback.",
            '    forced = os.getenv("FORECAST_ISSUE_SLOT", "").strip().lower()',
            '    if forced in {"morning", "afternoon"}:',
            "        return forced",
            "    local = (now_utc or datetime.now(timezone.utc)).astimezone(HELSINKI)",
            '    return "morning" if (local.hour, local.minute) < (12, 0) else "afternoon"',
            "",
            "",
            "def forecast_horizon_for_slot(slot: str) -> tuple[int, int]:",
            '    if slot == "morning":',
            "        return 1, 11",
            '    if slot == "afternoon":',
            "        return 2, 12",
            '    raise ValueError(f"Unknown forecast issue slot: {slot!r}")',
        ]
        helper = "\n".join(helper_lines)
        text = regex_once(
            text,
            r'(?m)^(MODEL_VERSION\s*=\s*["\']0\.7\.1["\']\s*)$',
            lambda m: m.group(1) + "\n\n" + helper,
            "forecast_engine: add issue-slot helpers",
        )

    if "issue_slot = resolve_issue_slot(now_utc)" not in text:
        pattern = r'(?m)^(\s*)now_local\s*=\s*now_utc\.astimezone\(HELSINKI\)\s*$'
        m = re.search(pattern, text)
        if not m:
            raise RuntimeError("forecast_engine: now_local anchor not found")
        indent = m.group(1)
        replacement = (
            m.group(0)
            + "\n"
            + indent + "issue_slot = resolve_issue_slot(now_utc)\n"
            + indent + "horizon_start, horizon_end = forecast_horizon_for_slot(issue_slot)"
        )
        text = text[:m.start()] + replacement + text[m.end():]
        print("[OK] forecast_engine: resolve slot inside make_forecast")

    fixed_loop = re.compile(r"for\s+day_h\s+in\s+range\(\s*2\s*,\s*13\s*\)\s*:")
    text, _ = fixed_loop.subn(
        "for day_h in range(horizon_start, horizon_end + 1):",
        text,
    )
    dynamic_count = text.count("for day_h in range(horizon_start, horizon_end + 1):")
    if dynamic_count < 2:
        raise RuntimeError(
            f"forecast_engine: expected two slot-specific horizon loops, found {dynamic_count}"
        )
    print(f"[OK] forecast_engine: slot-specific horizon loops ({dynamic_count})")

    if 'r["horizon"] == horizon_start' not in text:
        text, n = re.subn(
            r'r\["horizon"\]\s*==\s*2',
            'r["horizon"] == horizon_start',
            text,
            count=1,
        )
        if n != 1:
            raise RuntimeError("forecast_engine: D+2 anchor expression not found")
        print("[OK] forecast_engine: anchor uses first slot horizon")

    require(text, 'return 1, 11', "forecast_engine morning horizon")
    require(text, 'return 2, 12', "forecast_engine afternoon horizon")
    path.write_text(text, encoding="utf-8")


def patch_production_output(path: Path) -> None:
    print("[PATCH] production_output.py")
    text = path.read_text(encoding="utf-8")

    if not re.search(r"(?m)^from \.forecast_engine import .*resolve_issue_slot", text):
        text = regex_once(
            text,
            r"(?m)^from \.forecast_engine import HELSINKI\s*$",
            "from .forecast_engine import HELSINKI, resolve_issue_slot",
            "production_output: import resolve_issue_slot",
        )

    if not re.search(r"def _published_prices\(con,\s*issue_slot", text):
        pattern = (
            r"def _published_prices\(con\):\s*\n"
            r"\s*now_local\s*=\s*datetime\.now\(timezone\.utc\)\.astimezone\(HELSINKI\)\s*\n"
            r"\s*wanted\s*=\s*\[now_local\.date\(\),\s*now_local\.date\(\)\+timedelta\(days=1\)\][ \t]*"
        )
        repl = (
            "def _published_prices(con, issue_slot, issue_time_utc=None):\n"
            "    now_local=(issue_time_utc or datetime.now(timezone.utc)).astimezone(HELSINKI)\n"
            '    wanted=[now_local.date()] if issue_slot=="morning" else [now_local.date(),now_local.date()+timedelta(days=1)]'
        )
        text = regex_once(
            text, pattern, repl,
            "production_output: slot-specific published day-ahead set",
            flags=re.M,
        )

    if '"value_type":"day_ahead"' not in text:
        text = regex_once(
            text,
            r'("date":d\.isoformat\(\),"d_plus":idx,)',
            r'\1"value_type":"day_ahead",',
            "production_output: add day_ahead value_type",
        )

    if "issue_slot=resolve_issue_slot(issue_dt)" not in text:
        pattern = (
            r'(?m)^(\s*)run_id=meta\["forecast_run_id"\];\s*'
            r'prev=_previous_run\(con,run_id\)\s*$'
        )
        m = re.search(pattern, text)
        if not m:
            raise RuntimeError("production_output: run_id/prev anchor not found")
        indent = m.group(1)
        replacement = (
            m.group(0)
            + "\n"
            + indent + 'issue_dt=_parse_dt(meta["issue_time"])\n'
            + indent + "issue_slot=resolve_issue_slot(issue_dt)"
        )
        text = text[:m.start()] + replacement + text[m.end():]
        print("[OK] production_output: derive issue_slot from forecast issue time")

    if '"value_type":"forecast"' not in text:
        text = regex_once(
            text,
            r'("date":td,"d_plus":int\(r\["horizon_days"\]\),)',
            r'\1"value_type":"forecast",',
            "production_output: add forecast value_type",
        )

    if '"issue_slot":issue_slot' not in text:
        text = regex_once(
            text,
            r'("forecast_run_id":run_id,"forecast_issue_time":meta\["issue_time"\],)',
            r'\1"issue_slot":issue_slot,',
            "production_output: add top-level issue_slot",
        )

    if "_published_prices(con,issue_slot,issue_dt)" not in text:
        text, n = re.subn(
            r"_published_prices\(con\)",
            "_published_prices(con,issue_slot,issue_dt)",
            text,
            count=1,
        )
        if n != 1:
            raise RuntimeError("production_output: published prices call not found")
        print("[OK] production_output: published prices uses issue slot")

    if "def _value_badge(item):" not in text:
        helper_lines = [
            "def _value_badge(item):",
            '    value_type=item.get("value_type")',
            '    if value_type=="day_ahead":',
            '        if item.get("published",True):',
            '            bg,fg,label="#e8f7ee","#147b43","Julkaistu"',
            "        else:",
            '            bg,fg,label="#fff4df","#b56b0b","Ei julkaistu"',
            '    elif value_type=="forecast":',
            '        bg,fg,label="#eaf1ff","#0e4fc4","Ennuste"',
            "    else:",
            '        bg,fg,label="#eef1f5","#657085","Tuntematon"',
            '    return (f\'<span style="display:inline-block;margin-top:5px;border-radius:999px;\'',
            "            f'padding:3px 7px;font-size:.64rem;font-weight:800;'",
            '            f\'background:{bg};color:{fg}">{label}</span>\')',
            "",
        ]
        helper = "\n".join(helper_lines)
        text = regex_once(
            text,
            r"(?m)^def _render_html\(p\):\s*$",
            helper + "\ndef _render_html(p):",
            "production_output: add value_type badge helper",
        )

    if "forecast_heading=" not in text:
        heading_lines = [
            '    forecast_days=p.get("days",[])',
            "    if forecast_days:",
            '        hmin=min(int(d["d_plus"]) for d in forecast_days)',
            '        hmax=max(int(d["d_plus"]) for d in forecast_days)',
            '        forecast_heading=f"D+{hmin}–D+{hmax} ennuste"',
            "    else:",
            '        forecast_heading="Ennuste"',
        ]
        heading_code = "\n".join(heading_lines) + "\n"
        text = regex_once(
            text,
            r"(?m)^(def _render_html\(p\):\s*\n)",
            lambda m: m.group(1) + heading_code,
            "production_output: dynamic forecast heading",
        )

    if "badge_html=_value_badge(x)" not in text:
        pattern = r'(?m)^(\s*)tag="D0" if x\["d_plus"\]==0 else "D\+1"\s*$'
        m = re.search(pattern, text)
        if not m:
            raise RuntimeError("production_output: published card tag anchor not found")
        indent = m.group(1)
        replacement = m.group(0) + "\n" + indent + "badge_html=_value_badge(x)"
        text = text[:m.start()] + replacement + text[m.end():]
        print("[OK] production_output: published badge derives from value_type")

    pub_fragment = '<div class="dayname">{dlabel}<small>{_weekday_fi(x["date"])}</small></div>'
    pub_fragment_new = '<div class="dayname">{dlabel}<small>{_weekday_fi(x["date"])}</small>{badge_html}</div>'
    if pub_fragment in text:
        text = text.replace(pub_fragment, pub_fragment_new)
        if text.count(pub_fragment_new) < 2:
            raise RuntimeError("production_output: expected badges in both published-card branches")
        print("[OK] production_output: published badges inserted")
    elif pub_fragment_new not in text:
        raise RuntimeError("production_output: published-card dayname fragment not found")

    if "forecast_badge=_value_badge(d)" not in text:
        pattern = r'(?m)^(\s*)for d in p\["days"\]:\s*$'
        m = re.search(pattern, text)
        if not m:
            raise RuntimeError("production_output: forecast-day loop not found")
        indent = m.group(1) + "    "
        replacement = m.group(0) + "\n" + indent + "forecast_badge=_value_badge(d)"
        text = text[:m.start()] + replacement + text[m.end():]
        print("[OK] production_output: forecast badge derives from value_type")

    row_fragment = '<small>{_weekday_fi(d["date"])}</small></td>'
    row_fragment_new = '<small>{_weekday_fi(d["date"])}</small>{forecast_badge}</td>'
    if row_fragment in text:
        text = text.replace(row_fragment, row_fragment_new, 1)
        print("[OK] production_output: desktop forecast badge inserted")
    elif row_fragment_new not in text:
        raise RuntimeError("production_output: desktop forecast row fragment not found")

    mobile_fragment = '<small>{_weekday_fi(d["date"])}</small></div>'
    mobile_fragment_new = '<small>{_weekday_fi(d["date"])}</small>{forecast_badge}</div>'
    if mobile_fragment in text:
        text = text.replace(mobile_fragment, mobile_fragment_new, 1)
        print("[OK] production_output: mobile forecast badge inserted")
    elif mobile_fragment_new not in text:
        raise RuntimeError("production_output: mobile forecast fragment not found")

    if 'D+2–D+12 ennuste' in text:
        text = text.replace('D+2–D+12 ennuste', '{forecast_heading}', 1)
        print("[OK] production_output: heading follows actual forecast horizons")
    elif "{forecast_heading}" not in text:
        raise RuntimeError("production_output: forecast heading text not found")

    require(text, '"value_type":"day_ahead"', "production_output day_ahead type")
    require(text, '"value_type":"forecast"', "production_output forecast type")
    require(text, '"issue_slot":issue_slot', "production_output issue slot")
    require(text, "def _value_badge(item):", "production_output badge helper")
    path.write_text(text, encoding="utf-8")


def patch_quality(path: Path) -> None:
    print("[PATCH] forecast_quality.py")
    text = path.read_text(encoding="utf-8")
    if "for h in range(1,13):" not in text:
        text, n = re.subn(
            r"for\s+h\s+in\s+range\(\s*2\s*,\s*13\s*\)\s*:",
            "for h in range(1,13):",
            text,
            count=1,
        )
        if n != 1:
            raise RuntimeError("forecast_quality: D+2..D+12 loop not found")
        print("[OK] forecast_quality: include D+1")
    path.write_text(text, encoding="utf-8")


def patch_validate(path: Path) -> None:
    print("[PATCH] cloud_validate.py")
    text = path.read_text(encoding="utf-8")
    if "expected_horizons =" not in text:
        pattern = (
            r"\s*if not data\.get\('forecast_run_id'\) or len\(data\.get\('days', \[\]\)\) != 11:\s*\n"
            r"\s*raise RuntimeError\('Incomplete D\+2\.\.\.D\+12 forecast'\)\s*"
        )
        replacement_lines = [
            "    slot = data.get('issue_slot')",
            "    if slot not in ('morning', 'afternoon'):",
            "        raise RuntimeError('Missing or invalid issue_slot')",
            "    expected_horizons = list(range(1, 12)) if slot == 'morning' else list(range(2, 13))",
            "    actual_horizons = [int(x.get('d_plus', -1)) for x in data.get('days', [])]",
            "    if not data.get('forecast_run_id') or actual_horizons != expected_horizons:",
            "        raise RuntimeError(",
            "            f'Incomplete {slot} forecast: expected {expected_horizons}, got {actual_horizons}'",
            "        )",
            "    if any(x.get('value_type') != 'forecast' for x in data.get('days', [])):",
            "        raise RuntimeError('Forecast day missing value_type=forecast')",
            "    published = data.get('published_day_ahead', [])",
            "    expected_published = [0] if slot == 'morning' else [0, 1]",
            "    actual_published = [int(x.get('d_plus', -1)) for x in published]",
            "    if actual_published != expected_published:",
            "        raise RuntimeError(",
            "            f'Wrong published day-ahead set for {slot}: {actual_published}'",
            "        )",
            "    if any(x.get('value_type') != 'day_ahead' for x in published):",
            "        raise RuntimeError('Published day missing value_type=day_ahead')",
        ]
        replacement = "\n".join(replacement_lines)
        text, n = re.subn(pattern, "\n" + replacement + "\n", text, count=1, flags=re.M)
        if n != 1:
            raise RuntimeError("cloud_validate: old fixed-horizon validation block not found")
        print("[OK] cloud_validate: slot-specific output validation")
    path.write_text(text, encoding="utf-8")


def patch_workflow(path: Path) -> None:
    print("[PATCH] cloud_forecast.yml")
    text = path.read_text(encoding="utf-8")
    if "FORECAST_ISSUE_SLOT:" not in text:
        text = regex_once(
            text,
            r'(?m)^(\s*PYTHONUNBUFFERED:\s*"1"\s*)$',
            r'\1\n          FORECAST_ISSUE_SLOT: ${{ needs.gate.outputs.slot }}',
            "cloud workflow: pass gate slot to forecast process",
        )
    path.write_text(text, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    if not path.exists():
        print("[INFO] 36_AJA_JA_ARKISTOI.bat not present; local wrapper skipped")
        return
    print("[PATCH] 36_AJA_JA_ARKISTOI.bat")
    text = path.read_text(encoding="utf-8")
    if 'set "FORECAST_ISSUE_SLOT=%~1"' not in text:
        text = regex_once(
            text,
            r"(?im)^(echo === ELECTRICITY FORECASTER %~1 ===\s*)$",
            r'\1\nset "FORECAST_ISSUE_SLOT=%~1"',
            "local wrapper: pass explicit issue slot",
        )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    print(f"[VIRHE] Tama on {PATCH_VERSION}, jonka cloud_validate.py-korvaus kaytti")
    print("  regexia, joka saattoi sotkea sisennyksen (ks. README_v3_2.md).")
    print("Se on jo sovellettu tahan projektiin korjatulla versiolla v3.2:")
    print("  apply_issue_slot_display_patch_v3_2.py")
    print(f"Tata ({PATCH_VERSION}) skriptia ei pida enaa ajaa. Se sailyy vain historiallisena viitteena.")
    return 2


def _original_main_v3_1_do_not_use() -> int:
    ap = argparse.ArgumentParser(description=f"Electricity Forecaster issue-slot patch {PATCH_VERSION}")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    project = Path(args.root).resolve()

    rels = [
        Path("src/electricity_forecaster/forecast_engine.py"),
        Path("src/electricity_forecaster/production_output.py"),
        Path("src/electricity_forecaster/forecast_quality.py"),
        Path("scripts/cloud_validate.py"),
        Path(".github/workflows/cloud_forecast.yml"),
        Path("36_AJA_JA_ARKISTOI.bat"),
    ]
    for rel in rels[:-1]:
        if not (project / rel).is_file():
            print(f"[VIRHE] Required file missing: {project / rel}")
            return 2

    backup = backup_files(project, rels)
    print(f"[OK] Backup: {backup}")
    print(f"[INFO] Patch version: {PATCH_VERSION}")

    try:
        patch_forecast_engine(project / rels[0])
        patch_production_output(project / rels[1])
        patch_quality(project / rels[2])
        patch_validate(project / rels[3])
        patch_workflow(project / rels[4])
        patch_wrapper(project / rels[5])

        for rel in rels[:4]:
            py_compile.compile(str(project / rel), doraise=True)
        print("[OK] Python syntax checks")

        if (project / ".git").exists():
            r = subprocess.run(
                ["git", "diff", "--check"],
                cwd=project,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                raise RuntimeError("git diff --check failed:\n" + r.stdout + r.stderr)
            print("[OK] git diff --check")

        print("")
        print("PATCH OK")
        print("Morning 06:15:   D0 day_ahead + D+1...D+11 forecast")
        print("Afternoon 16:15: D0/D+1 day_ahead + D+2...D+12 forecast")
        print("JSON: explicit issue_slot and value_type")
        print("HTML: badges use JSON value_type")
        print("Cloud/local scheduling: explicit issue slot preserved")
        print(f"Backup: {backup}")
        return 0

    except Exception as exc:
        print(f"[VIRHE] {type(exc).__name__}: {exc}")
        print("[INFO] Restoring originals...")
        restore_backup(project, backup, rels)
        print(f"[OK] Restored from {backup}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
