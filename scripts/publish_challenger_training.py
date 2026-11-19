"""Publish comparable daily research summaries without publishing trained models."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "output"
HISTORY = DEST / "challenger_training_history.json"
PAGE = DEST / "challenger_models.html"

def metrics(version, report):
    if version == "v0.1":
        overall = report["overall"]
        n = report["evaluated_unique_hours"]
        status = report["status"]
    else:
        chosen = report["selected_candidate"]
        overall = report["holdout"][chosen]
        n = report["holdout_rows"]
        status = report["status"]
    if status not in ("research_only", "shadow_only"):
        raise ValueError(f"{version}: research status invalid: {status}")
    return {
        "mae_eur_mwh": float(overall["challenger"]["mae_eur_mwh"]),
        "champion_mae_eur_mwh": float(overall["champion"]["mae_eur_mwh"]),
        "sample_count": int(n),
        "evaluation": "walk_forward" if version == "v0.1" else "historical_holdout",
    }

def build(report1, report2, run_id, timestamp):
    previous = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {"schema_version": 1, "models": {}}
    models = previous.setdefault("models", {})
    for version, report in (("v0.1", report1), ("v0.2", report2)):
        records = models.setdefault(version, [])
        if records and records[-1].get("run_id") == run_id:
            continue
        m = metrics(version, report)
        before = records[-1]["mae_eur_mwh"] if records else None
        m.update({
            "run_id": run_id,
            "completed_at_utc": timestamp,
            "previous_mae_eur_mwh": before,
            "delta_mae_eur_mwh": round(m["mae_eur_mwh"] - before, 6) if before is not None else None,
        })
        records.append(m)
    previous["updated_at_utc"] = timestamp
    DEST.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return previous

def render(data):
    cards = []
    for version in ("v0.1", "v0.2"):
        records = data["models"].get(version, [])
        if not records:
            cards.append(f'<section class="card"><h2>Challenger {version}</h2><p>Ei vielä onnistunutta koulutusajoa.</p></section>')
            continue
        latest = records[-1]
        delta = latest["delta_mae_eur_mwh"]
        delta_text = "Ensimmäinen mittaus" if delta is None else f'{delta / 10:+.2f} c/kWh ({("parani" if delta < 0 else "heikkeni" if delta > 0 else "ennallaan")})'
        cards.append(f'''<section class="card">
<h2>Challenger {version}</h2>
<div class="label">Viimeisin koulutusajo (UTC)</div><p>{html.escape(latest["completed_at_utc"])}</p>
<div class="label">Challenger MAE</div><div class="metric">{latest["mae_eur_mwh"] / 10:.2f} <small>c/kWh</small></div>
<div class="label">Muutos edelliseen onnistuneeseen ajoon</div><p class="delta">{html.escape(delta_text)}</p>
<div class="label">Champion MAE samassa vertailussa</div><p>{latest["champion_mae_eur_mwh"] / 10:.2f} c/kWh</p>
<div class="label">Vertailumenetelmä</div><p>{'Ajallinen walk-forward' if version == 'v0.1' else 'Historiallinen holdout'} · {latest["sample_count"]} {'kohdetuntia' if version == 'v0.1' else 'havaintoriviä'}</p>
<p><a href="https://github.com/tempel-oss/sahkoennuste/actions/runs/{html.escape(latest["run_id"])}">Ajon loki GitHubissa</a></p>
</section>''')
    PAGE.write_text('''<!doctype html><html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Challengerien koulutusseuranta</title><style>
body{font-family:system-ui,sans-serif;background:#F7F4EC;color:#1C1B17;max-width:980px;margin:auto;padding:24px}
a{color:#0B4F49}h1{font-size:1.8rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}
.card{background:white;border:1px solid #ddd9cf;border-radius:16px;padding:24px}
.label{color:#777064;font-size:.85rem;margin-top:16px}.metric{font-size:2.5rem;font-weight:750;color:#0B4F49}
small{font-size:1rem}.delta{font-weight:700}p{margin:7px 0 12px}</style></head><body>
<p><a href="diagnostics.html">← Diagnostiikka</a></p><h1>Challengerien koulutusseuranta</h1>
<p>Molemmat mallit esitetään samalla tavalla. MAE:n pienentyminen on parannus. Muutos vertaa kahta viimeisintä onnistunutta päivittäistä tutkimusajoa, ei samaa muuttumatonta testijoukkoa.</p>
<div class="grid">''' + "\n".join(cards) + '''</div>
<p>v0.1:n walk-forward ja v0.2:n holdout ovat eri vertailumenetelmiä. Niiden MAE-arvoja ei tule tulkita suoraan mallien keskinäiseksi paremmuusjärjestykseksi. Mallit eivät korvaa championia automaattisesti.</p>
</body></html>''', encoding="utf-8")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--v01", type=Path, required=True)
    ap.add_argument("--v02", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    raw = args.v01.read_text(encoding="utf-8")
    report1 = json.loads(raw.split("BEGIN_RESEARCH_SUMMARY", 1)[1].split("END_RESEARCH_SUMMARY", 1)[0])
    report2 = json.loads(args.v02.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    render(build(report1, report2, args.run_id, now))
    print("Wrote comparable challenger history and HTML; no model published")
