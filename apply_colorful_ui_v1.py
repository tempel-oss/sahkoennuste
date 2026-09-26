from pathlib import Path
from datetime import datetime
import py_compile, shutil, subprocess

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "electricity_forecaster" / "production_output.py"
BACKUP_DIR = ROOT / "patch_backups" / f"colorful_ui_{datetime.now():%Y%m%d_%H%M%S}"
MARKER = "COLORFUL_UI_V1"

def require(text, needle, label):
    if needle not in text:
        raise RuntimeError(f"{label}: expected anchor not found")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 occurrence, found {count}")
    print(f"[OK] {label}")
    return text.replace(old, new, 1)

def main():
    if not TARGET.is_file():
        print(f"[VIRHE] Tiedostoa ei löydy: {TARGET}")
        return 1

    original = TARGET.read_text(encoding="utf-8")
    if MARKER in original:
        print("[INFO] Colorful UI v1 on jo asennettu.")
        return 0

    require(original, "def _value_badge(item):", "issue-slot UI helper")
    require(original, 'forecast_heading=f"D+{hmin}–D+{hmax} ennuste"', "dynamic forecast heading")
    require(original, '"value_type":"forecast"', "explicit forecast value_type")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / "production_output.py"
    shutil.copy2(TARGET, backup)
    print(f"[OK] Backup: {BACKUP_DIR}")

    try:
        text = original

        helper = '''
def _price_tone(value):
    # Visual-only price band based on snt/kWh incl. VAT.
    if value is None:
        return "price-tone-unknown"
    try:
        v=float(value)
    except (TypeError, ValueError):
        return "price-tone-unknown"
    if v < 4.0:
        return "price-tone-very-cheap"
    if v < 7.0:
        return "price-tone-cheap"
    if v < 12.0:
        return "price-tone-normal"
    if v < 20.0:
        return "price-tone-expensive"
    return "price-tone-very-expensive"

'''
        text = replace_once(text, "\ndef _render_html(p):", "\n"+helper+"def _render_html(p):", "add visual price-tone helper")

        text = replace_once(
            text,
            '        badge_html=_value_badge(x)\n        if x["published"]:',
            '        badge_html=_value_badge(x)\n        price_tone=_price_tone(x.get("mean_snt_kwh_vat"))\n        if x["published"]:',
            "published card price tone",
        )
        text = replace_once(
            text,
            'pub.append(f\'\'\'<article class="price-card {accent}">',
            'pub.append(f\'\'\'<article class="price-card {accent} {price_tone}">',
            "published card class",
        )
        text = replace_once(
            text,
            '        forecast_badge=_value_badge(d)\n        ch=d.get("change_from_previous")',
            '        forecast_badge=_value_badge(d)\n        price_tone=_price_tone(d.get("p50_snt_kwh_vat"))\n        ch=d.get("change_from_previous")',
            "forecast price tone",
        )
        text = replace_once(
            text,
            'rows.append(f\'\'\'<tr><td><b>D+{d["d_plus"]}</b>',
            'rows.append(f\'\'\'<tr class="{price_tone}"><td><b>D+{d["d_plus"]}</b>',
            "desktop forecast row class",
        )
        text = replace_once(
            text,
            'mobile.append(f\'\'\'<article class="forecast-day"><div><b>D+{d["d_plus"]}</b>',
            'mobile.append(f\'\'\'<article class="forecast-day {price_tone}"><div><b>D+{d["d_plus"]}</b>',
            "mobile forecast card class",
        )

        css = r'''
/* COLORFUL_UI_V1 */
:root{{--blue:#2563eb;--cyan:#06b6d4;--green:#16a34a;--red:#e5484d;--orange:#f59e0b;--purple:#8b5cf6;--bg:#eef4fb;--card:#fff;--text:#12213d;--muted:#64748b;--line:#dce5f1;--shadow:0 12px 32px rgba(30,64,120,.10)}}
body{{background:radial-gradient(circle at 8% 2%,rgba(34,211,238,.10),transparent 24rem),radial-gradient(circle at 92% 8%,rgba(139,92,246,.08),transparent 27rem),var(--bg)}}
.app-header{{background:linear-gradient(120deg,#092f76 0%,#2563eb 42%,#0ea5e9 75%,#14b8a6 100%)}}
.logo{{background:linear-gradient(145deg,#22d3ee 0%,#2563eb 55%,#7c3aed 100%);box-shadow:0 10px 28px rgba(10,54,130,.28)}}
.refresh{{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.18)}}
.source-strip,.card,.price-card,.factor,.quality-kpi,.readiness-card{{box-shadow:0 10px 28px rgba(30,64,120,.08)}}
.section-title{{position:relative;padding-left:13px}}
.section-title::before{{content:"";position:absolute;left:0;width:5px;height:22px;border-radius:999px;background:linear-gradient(180deg,#2563eb,#06b6d4)}}
.price-card{{position:relative;overflow:hidden;border-width:1px}}
.price-card::before{{content:"";position:absolute;left:0;right:0;top:0;height:4px;background:#cbd5e1}}
.price-card.price-tone-very-cheap{{background:linear-gradient(145deg,#fff 48%,#ecfdf5)}} .price-card.price-tone-very-cheap::before{{background:#16a34a}}
.price-card.price-tone-cheap{{background:linear-gradient(145deg,#fff 48%,#ecfeff)}} .price-card.price-tone-cheap::before{{background:#06b6d4}}
.price-card.price-tone-normal{{background:linear-gradient(145deg,#fff 48%,#eff6ff)}} .price-card.price-tone-normal::before{{background:#2563eb}}
.price-card.price-tone-expensive{{background:linear-gradient(145deg,#fff 48%,#fff7ed)}} .price-card.price-tone-expensive::before{{background:#f59e0b}}
.price-card.price-tone-very-expensive{{background:linear-gradient(145deg,#fff 48%,#fff1f2)}} .price-card.price-tone-very-expensive::before{{background:#e5484d}}
.price-card.price-tone-very-cheap .hero-price{{color:#15803d}}
.price-card.price-tone-cheap .hero-price{{color:#0891b2}}
.price-card.price-tone-normal .hero-price{{color:#1d4ed8}}
.price-card.price-tone-expensive .hero-price{{color:#d97706}}
.price-card.price-tone-very-expensive .hero-price{{color:#dc2626}}
.window-grid{{background:linear-gradient(135deg,rgba(239,246,255,.88),rgba(236,254,255,.72));border-color:#c7d8ef}}
table tbody tr{{transition:background .15s ease}} table tbody tr:hover{{background:#f8fbff}}
tr.price-tone-very-cheap td:first-child{{box-shadow:inset 4px 0 #16a34a}} tr.price-tone-very-cheap td.p50{{color:#15803d}}
tr.price-tone-cheap td:first-child{{box-shadow:inset 4px 0 #06b6d4}} tr.price-tone-cheap td.p50{{color:#0891b2}}
tr.price-tone-normal td:first-child{{box-shadow:inset 4px 0 #2563eb}} tr.price-tone-normal td.p50{{color:#1d4ed8}}
tr.price-tone-expensive td:first-child{{box-shadow:inset 4px 0 #f59e0b}} tr.price-tone-expensive td.p50{{color:#d97706}}
tr.price-tone-very-expensive td:first-child{{box-shadow:inset 4px 0 #e5484d}} tr.price-tone-very-expensive td.p50{{color:#dc2626}}
.change-cell.rise{{color:#e76f00}} .change-cell.fall{{color:#15803d}}
.risk.low{{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}}
.risk.med{{background:#ffedd5;color:#9a4d00;border:1px solid #fed7aa}}
.risk.high{{background:#fee2e2;color:#b91c1c;border:1px solid #fecaca}}
.source-item:nth-child(1) .source-icon{{background:#eef2ff;color:#4f46e5}}
.source-item:nth-child(2) .source-icon{{background:#ecfeff;color:#0891b2}}
.source-item:nth-child(3) .source-icon{{background:#fef9c3;color:#a16207}}
.source-item:nth-child(4) .source-icon{{background:#ecfdf5;color:#15803d}}
.factor:nth-child(1) .factor-icon{{background:#f3e8ff;color:#7e22ce}} .factor:nth-child(1){{border-top:3px solid #a855f7}}
.factor:nth-child(2) .factor-icon{{background:#cffafe;color:#0e7490}} .factor:nth-child(2){{border-top:3px solid #06b6d4}}
.factor:nth-child(3) .factor-icon{{background:#fef9c3;color:#a16207}} .factor:nth-child(3){{border-top:3px solid #eab308}}
.factor:nth-child(4) .factor-icon{{background:#dbeafe;color:#1d4ed8}} .factor:nth-child(4){{border-top:3px solid #3b82f6}}
.factor:nth-child(5) .factor-icon{{background:#ffedd5;color:#c2410c}} .factor:nth-child(5){{border-top:3px solid #f97316}}
.quality-kpi:nth-child(1){{border-top:3px solid #2563eb}}
.quality-kpi:nth-child(2){{border-top:3px solid #8b5cf6}}
.quality-kpi:nth-child(3){{border-top:3px solid #06b6d4}}
.quality-kpi:nth-child(4){{border-top:3px solid #16a34a}}
.progress-fill{{background:linear-gradient(90deg,#2563eb,#06b6d4,#14b8a6)}}
.uncertainty{{fill:#c7d2fe;opacity:.72}} .p50line{{stroke:#2563eb}} .dot{{stroke:#2563eb}}
.mobile-forecast .forecast-day{{position:relative;overflow:hidden}}
.mobile-forecast .forecast-day::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:#cbd5e1}}
.mobile-forecast .forecast-day.price-tone-very-cheap::before{{background:#16a34a}}
.mobile-forecast .forecast-day.price-tone-cheap::before{{background:#06b6d4}}
.mobile-forecast .forecast-day.price-tone-normal::before{{background:#2563eb}}
.mobile-forecast .forecast-day.price-tone-expensive::before{{background:#f59e0b}}
.mobile-forecast .forecast-day.price-tone-very-expensive::before{{background:#e5484d}}
.mobile-forecast .forecast-day.price-tone-very-cheap .mobile-p50{{color:#15803d}}
.mobile-forecast .forecast-day.price-tone-cheap .mobile-p50{{color:#0891b2}}
.mobile-forecast .forecast-day.price-tone-normal .mobile-p50{{color:#1d4ed8}}
.mobile-forecast .forecast-day.price-tone-expensive .mobile-p50{{color:#d97706}}
.mobile-forecast .forecast-day.price-tone-very-expensive .mobile-p50{{color:#dc2626}}
'''
        text = replace_once(text, "\n</style>", "\n"+css+"\n</style>", "insert colorful UI CSS")

        TARGET.write_text(text, encoding="utf-8")
        py_compile.compile(str(TARGET), doraise=True)
        print("[OK] Python syntax check")

        cp = subprocess.run(["git","diff","--check","--","src/electricity_forecaster/production_output.py"], cwd=ROOT, capture_output=True, text=True)
        if cp.returncode != 0:
            raise RuntimeError("git diff --check failed:\n"+cp.stdout+cp.stderr)
        print("[OK] git diff --check")

        print("\nPATCH OK")
        print("Only production_output.py was changed.")
        print("Forecast logic, JSON values, scheduling and issue-slot logic were not changed.")
        return 0
    except Exception as exc:
        print(f"[VIRHE] {type(exc).__name__}: {exc}")
        shutil.copy2(backup, TARGET)
        print(f"[OK] Restored from {backup}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
