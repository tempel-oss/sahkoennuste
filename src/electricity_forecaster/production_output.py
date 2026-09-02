
from __future__ import annotations
import json, sqlite3, html, math
from datetime import datetime, timezone
from pathlib import Path
from .config import ROOT
from .db import connect, init_db

VAT = 1.255
EURMWH_TO_SNTKWH_VAT = VAT / 10.0
OUTPUT_DIR = ROOT / "output"

def _conn():
    con = connect()
    con.row_factory = sqlite3.Row
    return con

def _safe(v, digits=2):
    if v is None:
        return None
    try:
        x=float(v)
        if not math.isfinite(x):
            return None
        return round(x,digits)
    except Exception:
        return None

def _latest_run(con):
    return con.execute("""
      SELECT forecast_run_id,issue_time,model_name,model_version,feature_run_id,
             data_quality,notes
      FROM price_forecast_runs
      WHERE status='ok'
      ORDER BY issue_time DESC
      LIMIT 1
    """).fetchone()

def _previous_run(con, current_id):
    rows=con.execute("""
      SELECT forecast_run_id,issue_time
      FROM price_forecast_runs
      WHERE status='ok'
      ORDER BY issue_time DESC
      LIMIT 2
    """).fetchall()
    if len(rows)>=2 and rows[0]["forecast_run_id"]==current_id:
        return rows[1]
    return None

def _diag_map(con, run_id, target_date):
    rows=con.execute("""
      SELECT component,value,unit,note
      FROM forecast_diagnostics
      WHERE run_id=? AND target_date=?
    """,(run_id,target_date)).fetchall()
    return {r["component"]:{
        "value":_safe(r["value"],2),"unit":r["unit"] or "","note":r["note"] or ""
    } for r in rows}

def _change_map(con, run_id, target_date):
    rows=con.execute("""
      SELECT metric,old_value,new_value,delta
      FROM forecast_changes
      WHERE run_id=? AND target_date=?
    """,(run_id,target_date)).fetchall()
    return {r["metric"]:{
        "old":_safe(r["old_value"],2),"new":_safe(r["new_value"],2),"delta":_safe(r["delta"],2)
    } for r in rows}

def _service_health(con):
    # service_health has evolved; detect current columns.
    cols={r[1] for r in con.execute("PRAGMA table_info(service_health)").fetchall()}
    if not cols:
        return []
    select=[]
    for wanted in ("service","status","checked_at","detail","message"):
        if wanted in cols:
            select.append(wanted)
    if not select:
        return []
    rows=con.execute("SELECT "+",".join(select)+" FROM service_health ORDER BY checked_at DESC").fetchall()
    seen=set(); out=[]
    for r in rows:
        service=r["service"] if "service" in r.keys() else "?"
        if service in seen: continue
        seen.add(service)
        detail=""
        if "detail" in r.keys() and r["detail"] is not None: detail=str(r["detail"])
        elif "message" in r.keys() and r["message"] is not None: detail=str(r["message"])
        out.append({
          "service":service,
          "status":r["status"] if "status" in r.keys() else "",
          "checked_at":r["checked_at"] if "checked_at" in r.keys() else "",
          "detail":detail
        })
    return out

def build_latest_outputs():
    init_db()
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    con=_conn()
    meta=_latest_run(con)
    if not meta:
        con.close()
        raise RuntimeError("Onnistunutta hintaennusteajoa ei loydy.")

    run_id=meta["forecast_run_id"]
    prev=_previous_run(con,run_id)
    rows=con.execute("""
      SELECT target_date,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,
             baseline_eur_mwh,min_p50_eur_mwh,max_p50_eur_mwh,
             cheapest_3h,expensive_3h,risk_level,drivers_json
      FROM price_forecasts_daily
      WHERE forecast_run_id=?
      ORDER BY horizon_days
    """,(run_id,)).fetchall()

    days=[]
    for r in rows:
        td=r["target_date"]
        p10=float(r["p10_eur_mwh"])*EURMWH_TO_SNTKWH_VAT
        p50=float(r["p50_eur_mwh"])*EURMWH_TO_SNTKWH_VAT
        p90=float(r["p90_eur_mwh"])*EURMWH_TO_SNTKWH_VAT
        diag=_diag_map(con,run_id,td)
        changes=_change_map(con,run_id,td)

        total_unc=None; weather_unc=None; model_unc=None
        u=con.execute("""
          SELECT weather_component,model_component,total_component
          FROM uncertainty_components
          WHERE run_id=? AND target_date=?
        """,(run_id,td)).fetchone()
        if u:
            weather_unc=_safe(u["weather_component"])
            model_unc=_safe(u["model_component"])
            total_unc=_safe(u["total_component"])

        days.append({
          "date":td,
          "d_plus":int(r["horizon_days"]),
          "p10_snt_kwh_vat":_safe(p10),
          "p50_snt_kwh_vat":_safe(p50),
          "p90_snt_kwh_vat":_safe(p90),
          "baseline_snt_kwh_vat":_safe(float(r["baseline_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "min_p50_snt_kwh_vat":_safe(float(r["min_p50_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "max_p50_snt_kwh_vat":_safe(float(r["max_p50_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "cheapest_3h":r["cheapest_3h"],
          "expensive_3h":r["expensive_3h"],
          "risk":r["risk_level"],
          "uncertainty":{
            "half_width_snt_kwh":total_unc,
            "weather_component_snt_kwh":weather_unc,
            "model_component_snt_kwh":model_unc
          },
          "diagnostics":diag,
          "change_from_previous":changes.get("p50")
        })

    payload={
      "schema_version":"0.9",
      "generated_at_utc":datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
      "forecast_run_id":run_id,
      "forecast_issue_time":meta["issue_time"],
      "model":{"name":meta["model_name"],"version":meta["model_version"],
               "trained_ml":False},
      "previous_forecast_run_id":prev["forecast_run_id"] if prev else None,
      "data_quality":meta["data_quality"],
      "days":days,
      "service_health":_service_health(con)
    }
    con.close()

    json_path=OUTPUT_DIR/"latest_forecast.json"
    json_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

    html_path=OUTPUT_DIR/"latest_forecast.html"
    html_path.write_text(_render_html(payload),encoding="utf-8")
    index_path=OUTPUT_DIR/"index.html"
    index_path.write_text(html_path.read_text(encoding="utf-8"),encoding="utf-8")
    return json_path,html_path,len(days)

def _fmt(v):
    return "—" if v is None else f"{v:.2f}"

def _render_html(p):
    rows=[]
    detail_cards=[]
    for d in p["days"]:
        change=d.get("change_from_previous")
        change_txt=""
        if change and change.get("delta") is not None:
            delta=change["delta"]
            sign="+" if delta>=0 else ""
            change_txt=f'<span class="change">{sign}{delta:.2f}</span>'
        rows.append(f"""
          <tr>
            <td><strong>{html.escape(d["date"])}</strong><div class="muted">D+{d["d_plus"]}</div></td>
            <td class="num"><strong>{_fmt(d["p50_snt_kwh_vat"])}</strong>{change_txt}</td>
            <td class="num">{_fmt(d["p10_snt_kwh_vat"])} – {_fmt(d["p90_snt_kwh_vat"])}</td>
            <td>{html.escape(d["cheapest_3h"] or "—")}</td>
            <td>{html.escape(d["expensive_3h"] or "—")}</td>
            <td>{html.escape(d["risk"] or "—")}</td>
          </tr>""")
        dg=d["diagnostics"]
        def val(name, suffix=""):
            x=dg.get(name)
            if not x or x.get("value") is None: return "—"
            u=x.get("unit","")
            return f'{x["value"]:.1f} {html.escape(u)}'
        detail_cards.append(f"""
        <details>
          <summary>{html.escape(d["date"])} · D+{d["d_plus"]} · P50 {_fmt(d["p50_snt_kwh_vat"])} snt/kWh</summary>
          <div class="detailgrid">
            <div><span>Kulutus</span><strong>{val("consumption_forecast")}</strong></div>
            <div><span>Tuuli</span><strong>{val("wind_forecast")}</strong></div>
            <div><span>Aurinko</span><strong>{val("solar_forecast")}</strong></div>
            <div><span>Residual load</span><strong>{val("residual_load")}</strong></div>
            <div><span>Lämpötila</span><strong>{val("temperature")}</strong></div>
            <div><span>100 m tuuli</span><strong>{val("wind_100m")}</strong></div>
          </div>
        </details>""")

    health=[]
    for s in p.get("service_health",[]):
        cls="ok" if str(s["status"]).lower()=="ok" else "warn"
        health.append(f'<span class="pill {cls}">{html.escape(str(s["service"]))}: {html.escape(str(s["status"]))}</span>')

    return f"""<!doctype html>
<html lang="fi"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#27306A">\n<link rel="manifest" href="manifest.webmanifest">\n<link rel="icon" href="icons/icon-192.png">\n<link rel="apple-touch-icon" href="icons/icon-192.png">
<title>Sähköennuste</title>
<style>
:root{{--bg:#f5f7fa;--card:#fff;--text:#18202a;--muted:#667085;--line:#dce2e8;--accent:#27306A;--ok:#18794e;--warn:#9a6700}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:980px;margin:auto;padding:18px}}
header{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:14px}}
h1{{font-size:1.55rem;margin:0}}
.muted{{color:var(--muted);font-size:.86rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:12px 0}}
.tablewrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;min-width:720px}}
th,td{{padding:11px 9px;border-bottom:1px solid var(--line);text-align:left;font-size:.94rem}}
th{{font-size:.82rem;color:var(--muted);position:sticky;top:0;background:#fff}}
.num{{text-align:right}}
.change{{display:block;font-size:.76rem;color:var(--muted);font-weight:500}}
.pill{{display:inline-block;padding:5px 9px;border-radius:999px;margin:3px;font-size:.78rem;background:#eef1f4}}
.pill.ok{{color:var(--ok);background:#e8f5ee}} .pill.warn{{color:var(--warn);background:#fff4ce}}
details{{border-top:1px solid var(--line);padding:10px 0}} summary{{cursor:pointer;font-weight:650}}
.detailgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}}
.detailgrid div{{background:#f7f8fa;padding:10px;border-radius:9px}}
.detailgrid span{{display:block;color:var(--muted);font-size:.78rem}} .detailgrid strong{{font-size:.95rem}}
footer{{color:var(--muted);font-size:.8rem;margin:18px 0}}
@media(max-width:650px){{main{{padding:10px}}h1{{font-size:1.3rem}}.detailgrid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head>
<body><main>
<header>
<div><h1>Suomen pörssisähkön 12 päivän ennuste</h1>
<div class="muted">Päivitetty {html.escape(str(p["forecast_issue_time"]))} · {html.escape(p["model"]["name"])} {html.escape(p["model"]["version"])}</div></div>
<div>{"".join(health)}</div>
</header>
<div class="card">
<div class="tablewrap"><table>
<thead><tr><th>Päivä</th><th class="num">P50 snt/kWh</th><th class="num">P10–P90</th><th>Halvin 3 h</th><th>Kallein 3 h</th><th>Riski</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
<div class="muted" style="margin-top:9px">Hinnat sisältävät ALV 25,5 %. P50 on perusennuste. Tämä versio on vielä fundamentaalinen baseline, ei koulutettu ML/Champion-malli.</div>
</div>
<div class="card"><strong>Ennusteen taustatekijät</strong>{"".join(detail_cards)}</div>
<footer>Forecast run: {html.escape(p["forecast_run_id"])} · Electricity Forecaster v0.9</footer>
</main><script>if("serviceWorker" in navigator){{window.addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{{}}));}}</script></body></html>"""
