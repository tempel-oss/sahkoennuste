
from __future__ import annotations
import json, sqlite3, html, math, statistics
from datetime import datetime, timezone, timedelta
from .config import ROOT
from .db import connect, init_db
from .forecast_engine import HELSINKI
from .model_registry import model_status

VAT = 1.255
EURMWH_TO_SNTKWH_VAT = VAT / 10.0
OUTPUT_DIR = ROOT / "output"

def _conn():
    con=connect(); con.row_factory=sqlite3.Row; return con

def _safe(v,digits=2):
    if v is None: return None
    try:
        x=float(v)
        return round(x,digits) if math.isfinite(x) else None
    except Exception:
        return None

def _parse_dt(s):
    x=str(s).strip()
    if x.endswith("Z"): x=x[:-1]+"+00:00"
    d=datetime.fromisoformat(x)
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def _latest_run(con):
    return con.execute('''SELECT forecast_run_id,issue_time,model_name,model_version,feature_run_id,
             data_quality,notes FROM price_forecast_runs WHERE status='ok'
             ORDER BY issue_time DESC LIMIT 1''').fetchone()

def _previous_run(con,current_id):
    rows=con.execute('''SELECT forecast_run_id,issue_time FROM price_forecast_runs
                        WHERE status='ok' ORDER BY issue_time DESC LIMIT 2''').fetchall()
    return rows[1] if len(rows)>=2 and rows[0]["forecast_run_id"]==current_id else None

def _diag_map(con,run_id,target_date):
    rows=con.execute('''SELECT component,value,unit,note FROM forecast_diagnostics
                        WHERE run_id=? AND target_date=?''',(run_id,target_date)).fetchall()
    return {r["component"]:{"value":_safe(r["value"],2),"unit":r["unit"] or "","note":r["note"] or ""} for r in rows}

def _change_map(con,run_id,target_date):
    rows=con.execute('''SELECT metric,old_value,new_value,delta FROM forecast_changes
                        WHERE run_id=? AND target_date=?''',(run_id,target_date)).fetchall()
    return {r["metric"]:{"old":_safe(r["old_value"],2),"new":_safe(r["new_value"],2),"delta":_safe(r["delta"],2)}
            for r in rows}

def _three_hour_window(rows, cheapest=True):
    if not rows: return None
    rr=sorted(rows,key=lambda x:x[0]); best=None
    for i in range(len(rr)):
        start=rr[i][0]; end=start+timedelta(hours=3)
        vals=[v for dt,v in rr if start <= dt < end]
        if len(vals)<3: continue
        score=statistics.mean(vals)
        if best is None or (score < best[0] if cheapest else score > best[0]):
            best=(score,start,end)
    if not best: return None
    return f"{best[1]:%H:%M}–{best[2]:%H:%M}"

def _published_prices(con):
    now_local=datetime.now(timezone.utc).astimezone(HELSINKI)
    wanted=[now_local.date(),now_local.date()+timedelta(days=1)]
    raw=con.execute('''SELECT mp.valid_time,mp.price_eur_mwh,pr.issue_time
                       FROM market_prices mp JOIN price_runs pr ON pr.run_id=mp.run_id
                       WHERE mp.area='FI' ORDER BY pr.issue_time DESC''').fetchall()
    seen=set(); grouped={d:[] for d in wanted}; issue={}
    for r in raw:
        dt=_parse_dt(r["valid_time"]).astimezone(HELSINKI); d=dt.date()
        if d not in grouped: continue
        key=(d,dt.isoformat())
        if key in seen: continue
        seen.add(key); grouped[d].append((dt,float(r["price_eur_mwh"])))
        issue.setdefault(d,r["issue_time"])
    out=[]
    for idx,d in enumerate(wanted):
        vals=grouped[d]; prices=[v for _,v in vals]
        out.append({
          "date":d.isoformat(),"d_plus":idx,"published":bool(prices),
          "mean_snt_kwh_vat":_safe(statistics.mean(prices)*EURMWH_TO_SNTKWH_VAT) if prices else None,
          "min_snt_kwh_vat":_safe(min(prices)*EURMWH_TO_SNTKWH_VAT) if prices else None,
          "max_snt_kwh_vat":_safe(max(prices)*EURMWH_TO_SNTKWH_VAT) if prices else None,
          "cheapest_3h":_three_hour_window(vals,True),"expensive_3h":_three_hour_window(vals,False),
          "observations":len(prices),"price_run_issue_time":issue.get(d)
        })
    return out

def _freshness(con):
    now=datetime.now(timezone.utc)
    specs=[
      ("Fingrid","forecast_runs","issue_time","source='fingrid'"),
      ("Nord Pool","price_runs","issue_time","1=1"),
      ("Sää","weather_runs","issue_time","status IN ('ok','degraded')"),
      ("ENTSO-E","entsoe_runs","issue_time","1=1")
    ]
    items=[]
    for name,table,col,where in specs:
        try:
            r=con.execute(f"SELECT MAX({col}) FROM {table} WHERE {where}").fetchone()
            ts=r[0] if r and r[0] else None
        except Exception:
            ts=None
        age=None
        if ts:
            try: age=(now-_parse_dt(ts)).total_seconds()/60
            except Exception: age=None
        green=180 if name=="Sää" else 120
        amber=720 if name=="Sää" else 360
        state="unknown" if age is None else ("fresh" if age<=green else ("aging" if age<=amber else "stale"))
        items.append({"source":name,"timestamp":ts,"age_minutes":_safe(age,0),"state":state})
    states=[x["state"] for x in items if x["state"]!="unknown"]
    overall="fresh" if states and all(s=="fresh" for s in states) else ("stale" if "stale" in states else "mixed")
    return {"overall":overall,"sources":items}

def build_latest_outputs():
    init_db(); OUTPUT_DIR.mkdir(parents=True,exist_ok=True); con=_conn()
    meta=_latest_run(con)
    if not meta:
        con.close(); raise RuntimeError("Onnistunutta hintaennusteajoa ei loydy.")
    run_id=meta["forecast_run_id"]; prev=_previous_run(con,run_id)
    rows=con.execute('''SELECT target_date,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,
             baseline_eur_mwh,min_p50_eur_mwh,max_p50_eur_mwh,
             cheapest_3h,expensive_3h,risk_level,drivers_json
             FROM price_forecasts_daily WHERE forecast_run_id=? ORDER BY horizon_days''',(run_id,)).fetchall()
    days=[]
    for r in rows:
        td=r["target_date"]; changes=_change_map(con,run_id,td)
        u=con.execute('''SELECT weather_component,model_component,total_component
                         FROM uncertainty_components WHERE run_id=? AND target_date=?''',(run_id,td)).fetchone()
        days.append({
          "date":td,"d_plus":int(r["horizon_days"]),
          "p10_snt_kwh_vat":_safe(float(r["p10_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "p50_snt_kwh_vat":_safe(float(r["p50_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "p90_snt_kwh_vat":_safe(float(r["p90_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "baseline_snt_kwh_vat":_safe(float(r["baseline_eur_mwh"])*EURMWH_TO_SNTKWH_VAT),
          "cheapest_3h":r["cheapest_3h"],"expensive_3h":r["expensive_3h"],"risk":r["risk_level"],
          "uncertainty":{"weather_component_snt_kwh":_safe(u["weather_component"]) if u else None,
                         "model_component_snt_kwh":_safe(u["model_component"]) if u else None,
                         "half_width_snt_kwh":_safe(u["total_component"]) if u else None},
          "diagnostics":_diag_map(con,run_id,td),"change_from_previous":changes.get("p50")
        })
    payload={
      "schema_version":"1.1",
      "generated_at_utc":datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
      "forecast_run_id":run_id,"forecast_issue_time":meta["issue_time"],
      "model":{"name":meta["model_name"],"version":meta["model_version"],
               "trained_ml":meta["model_name"]!="fundamental_baseline"},
      "model_status":model_status(),"previous_forecast_run_id":prev["forecast_run_id"] if prev else None,
      "data_quality":meta["data_quality"],"freshness":_freshness(con),
      "published_day_ahead":_published_prices(con),"days":days
    }
    con.close()
    jp=OUTPUT_DIR/"latest_forecast.json"; jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    hp=OUTPUT_DIR/"latest_forecast.html"; hp.write_text(_render_html(payload),encoding="utf-8")
    (OUTPUT_DIR/"index.html").write_text(hp.read_text(encoding="utf-8"),encoding="utf-8")
    return jp,hp,len(days)

def _fmt(v): return "—" if v is None else f"{v:.2f}"


def _icon_svg(kind):
    icons={
      "bolt":'<svg viewBox="0 0 24 24"><path d="M13.2 2 5 13h6l-.8 9L19 10h-6.2L13.2 2Z"/></svg>',
      "grid":'<svg viewBox="0 0 24 24"><path d="M12 2 8 7h3L7 22h2.6l1.4-6h2l1.4 6H17l-4-15h3l-4-5Zm0 7.2 1 4.3h-2l1-4.3Z"/></svg>',
      "wind":'<svg viewBox="0 0 24 24"><path d="M3 8h10.5a2.5 2.5 0 1 0-2.2-3.7M3 12h15a2.5 2.5 0 1 1-2.2 3.7M3 16h8"/></svg>',
      "sun":'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
      "thermo":'<svg viewBox="0 0 24 24"><path d="M10 5a2 2 0 1 1 4 0v8.2a4 4 0 1 1-4 0V5Z"/><path d="M12 8v8"/></svg>',
      "chart":'<svg viewBox="0 0 24 24"><path d="M4 19V5M4 19h16M7 15l4-4 3 2 5-6"/></svg>',
      "db":'<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
      "trophy":'<svg viewBox="0 0 24 24"><path d="M8 4h8v4a4 4 0 0 1-8 0V4ZM10 12v3h4v-3M8 19h8M4 5h4v3a3 3 0 0 1-3 3H4V5ZM20 5h-4v3a3 3 0 0 0 3 3h1V5Z"/></svg>',
      "brain":'<svg viewBox="0 0 24 24"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 5 2V5a3 3 0 0 0-2-1ZM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-5 2V5a3 3 0 0 1 2-1Z"/></svg>',
      "check":'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></svg>'
    }
    return icons.get(kind,icons["bolt"])

def _weekday_fi(date_str):
    try:
        d=datetime.fromisoformat(date_str).date()
        names=["ma","ti","ke","to","pe","la","su"]
        return f"{names[d.weekday()]} {d.day}.{d.month}."
    except Exception:
        return date_str

def _chart_svg(p):
    pts=[]
    for x in p.get("published_day_ahead",[]):
        if x.get("published") and x.get("mean_snt_kwh_vat") is not None:
            v=float(x["mean_snt_kwh_vat"])
            pts.append({"label":f'D+{x["d_plus"]}',"date":x["date"],"p50":v,"p10":v,"p90":v})
    for d in p.get("days",[]):
        pts.append({"label":f'D+{d["d_plus"]}',"date":d["date"],"p50":d["p50_snt_kwh_vat"],
                    "p10":d["p10_snt_kwh_vat"],"p90":d["p90_snt_kwh_vat"]})
    pts=[x for x in pts if x["p50"] is not None]
    if len(pts)<2:
        return '<div class="empty-chart">Kaavioon ei ole vielä riittävästi dataa.</div>'
    W,H,left,right,top,bottom=900,290,48,22,28,58
    vals=[]
    for x in pts:
        vals.extend([v for v in (x.get("p10"),x.get("p50"),x.get("p90")) if v is not None])
    ymin=min(vals); ymax=max(vals); pad=max(1.0,(ymax-ymin)*.15)
    ymin=min(0,ymin-pad); ymax=ymax+pad
    if ymax-ymin<1: ymax=ymin+1
    def X(i): return left+(W-left-right)*(i/(len(pts)-1))
    def Y(v): return top+(H-top-bottom)*(1-(float(v)-ymin)/(ymax-ymin))
    grid=[]
    for i in range(5):
        val=ymin+(ymax-ymin)*i/4; y=Y(val)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{W-right}" y2="{y:.1f}" class="gridline"/>')
        grid.append(f'<text x="{left-9}" y="{y+4:.1f}" text-anchor="end" class="axis">{val:.1f}</text>')
    upper=[(X(i),Y(x["p90"] if x["p90"] is not None else x["p50"])) for i,x in enumerate(pts)]
    lower=[(X(i),Y(x["p10"] if x["p10"] is not None else x["p50"])) for i,x in reversed(list(enumerate(pts)))]
    area=" ".join(f"{x:.1f},{y:.1f}" for x,y in upper+lower)
    line=" ".join(f"{X(i):.1f},{Y(x['p50']):.1f}" for i,x in enumerate(pts))
    marks=[]
    for i,x in enumerate(pts):
        xx=X(i); yy=Y(x["p50"])
        marks.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="4" class="dot"/>')
        marks.append(f'<text x="{xx:.1f}" y="{yy-10:.1f}" text-anchor="middle" class="value-label">{x["p50"]:.2f}</text>')
        marks.append(f'<text x="{xx:.1f}" y="{H-bottom+22}" text-anchor="middle" class="xlab">{int(x["date"][8:10])}.{int(x["date"][5:7])}.</text>')
        marks.append(f'<text x="{xx:.1f}" y="{H-bottom+39}" text-anchor="middle" class="xlab2">{x["label"]}</text>')
    return f'<svg class="price-chart" viewBox="0 0 {W} {H}">{"".join(grid)}<polygon points="{area}" class="uncertainty"/><polyline points="{line}" class="p50line"/>{"".join(marks)}</svg>'

def _change_summary(p):
    days=p.get("days",[]); deltas=[]
    for d in days:
        ch=d.get("change_from_previous")
        if ch and ch.get("delta") is not None:
            deltas.append((float(ch["delta"]),d))
    out=[]
    if deltas:
        avg=sum(x[0] for x in deltas)/len(deltas)
        direction="nousi" if avg>.05 else ("laski" if avg<-.05 else "pysyi lähes ennallaan")
        tone="red" if avg>.05 else ("green" if avg<-.05 else "amber")
        out.append(("chart",tone,f"Kokonaisennuste {direction}",f"Keskimääräinen P50-muutos {avg:+.2f} snt/kWh."))
        b=max(deltas,key=lambda x:abs(x[0]))
        out.append(("bolt","amber",f"Suurin muutos D+{b[1]['d_plus']}",f"{b[0]:+.2f} snt/kWh päivälle {b[1]['date']}."))
    else:
        out.append(("chart","amber","Vertailuhistoria kertyy","Edelliseen ajoon verrattavaa muutosta ei vielä ole."))
    tail=[d for d in days if d["d_plus"]>=8 and d["p90_snt_kwh_vat"] is not None and d["p10_snt_kwh_vat"] is not None]
    if tail:
        widths=[d["p90_snt_kwh_vat"]-d["p10_snt_kwh_vat"] for d in tail]
        out.append(("wind","purple","D+8–D+12 epävarmuus",f"Keskimääräinen P10–P90-leveys {sum(widths)/len(widths):.2f} snt/kWh."))
    return out[:3]

def _render_html(p):
    pub=[]
    for x in p["published_day_ahead"]:
        dlabel="Tänään" if x["d_plus"]==0 else "Huomenna"
        accent="blue" if x["d_plus"]==0 else "green"
        tag="D0" if x["d_plus"]==0 else "D+1"
        if x["published"]:
            pub.append(f'''<article class="price-card {accent}">
              <div class="price-top"><div><span class="dtag">{tag}</span><div class="dayname">{dlabel}<small>{_weekday_fi(x["date"])}</small></div></div></div>
              <div class="hero-price">{_fmt(x["mean_snt_kwh_vat"])} <span>snt/kWh</span></div>
              <div class="statrow"><span>Min <b class="good">{_fmt(x["min_snt_kwh_vat"])}</b></span><span>Keski <b>{_fmt(x["mean_snt_kwh_vat"])}</b></span><span>Max <b class="bad">{_fmt(x["max_snt_kwh_vat"])}</b></span></div>
              <div class="window-grid"><div><span>Halvin 3 h</span><b>{html.escape(x["cheapest_3h"] or "—")}</b></div><div><span>Kallein 3 h</span><b>{html.escape(x["expensive_3h"] or "—")}</b></div></div>
            </article>''')
        else:
            pub.append(f'''<article class="price-card {accent} pending"><div class="price-top"><div><span class="dtag">{tag}</span><div class="dayname">{dlabel}<small>{_weekday_fi(x["date"])}</small></div></div></div><div class="hero-price small">Ei julkaistu</div><div class="muted">FI day-ahead -hintaa ei ole vielä tietokannassa.</div></article>''')

    rows=[]; mobile=[]
    for d in p["days"]:
        ch=d.get("change_from_previous"); delta=float(ch["delta"]) if ch and ch.get("delta") is not None else None
        change="—" if delta is None else f"{delta:+.2f}"
        chcls="" if delta is None else ("rise" if delta>0 else ("fall" if delta<0 else ""))
        arrow="" if delta is None else ("↑" if delta>0 else ("↓" if delta<0 else "→"))
        r=(d["risk"] or "—").lower(); riskcls="high" if "kork" in r else ("low" if "mat" in r else "med")
        rows.append(f'''<tr><td><b>D+{d["d_plus"]}</b><small>{_weekday_fi(d["date"])}</small></td><td class="p50">{_fmt(d["p50_snt_kwh_vat"])}</td><td>{_fmt(d["p10_snt_kwh_vat"])} – {_fmt(d["p90_snt_kwh_vat"])}</td><td class="change-cell {chcls}">{change} {arrow}<small>vs edellinen</small></td><td><span class="risk {riskcls}">{html.escape(d["risk"] or "—")}</span></td></tr>''')
        mobile.append(f'''<article class="forecast-day"><div><b>D+{d["d_plus"]}</b><small>{_weekday_fi(d["date"])}</small></div><div class="mobile-p50">{_fmt(d["p50_snt_kwh_vat"])}<small>snt/kWh</small></div><div class="mobile-range">P10–P90<br><b>{_fmt(d["p10_snt_kwh_vat"])} – {_fmt(d["p90_snt_kwh_vat"])}</b></div><div class="mobile-change {chcls}">{change} {arrow}<small>vs edellinen</small></div><span class="risk {riskcls}">{html.escape(d["risk"] or "—")}</span></article>''')

    labels={"fresh":"Tuore","aging":"Ikääntyvä","stale":"Vanhentunut","unknown":"Ei tietoa"}
    logos={"Fingrid":"grid","Nord Pool":"bolt","Sää":"sun","ENTSO-E":"check"}
    fresh=[]
    for x in p["freshness"]["sources"]:
        fresh.append(f'''<div class="source-item"><span class="source-icon">{_icon_svg(logos.get(x["source"],"check"))}</span><div><b>{html.escape(x["source"])}</b><small class="{x["state"]}"><i></i>{labels[x["state"]]}</small></div></div>''')

    dg=p["days"][0].get("diagnostics",{}) if p.get("days") else {}
    factor_specs=[("Kulutus","consumption_forecast","grid","MW"),("Tuuli","wind_forecast","wind","MW"),("Aurinko","solar_forecast","sun","MW"),("Residual load","residual_load","bolt","MW"),("Lämpötila","temperature","thermo","°C")]
    factors=[]
    for title,key,icon,unit in factor_specs:
        x=dg.get(key,{})
        val=x.get("value")
        if val is None: v,u="—",""
        elif unit=="MW" and abs(val)>=1000: v,u=f"{val/1000:.1f}","GW"
        else: v,u=f"{val:.1f}",unit
        factors.append(f'''<div class="factor"><span class="factor-icon">{_icon_svg(icon)}</span><div><small>{title}</small><b>{v} <em>{u}</em></b></div></div>''')

    changes=[]
    for icon,tone,title,desc in _change_summary(p):
        changes.append(f'''<div class="change-item"><span class="change-icon {tone}">{_icon_svg(icon)}</span><div><b>{html.escape(title)}</b><small>{html.escape(desc)}</small></div></div>''')

    ms=p["model_status"]; ev=ms["evaluation"]; champ=ms["champion"]; ready=ms["challenger_training_ready"]

    return f'''<!doctype html><html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#083b9a">
<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icons/icon-192.png"><link rel="apple-touch-icon" href="icons/icon-192.png"><title>Sähköennuste</title>
<style>
:root{{--blue:#0e4fc4;--green:#168a4b;--red:#d83b32;--orange:#e98319;--purple:#7656c8;--bg:#f4f7fb;--card:#fff;--text:#12213d;--muted:#6e7b91;--line:#e4eaf2;--shadow:0 10px 30px rgba(29,58,105,.08)}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}svg{{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}}
.app-header{{background:linear-gradient(125deg,#062a70 0%,#0c49b8 60%,#1260d0 100%);color:#fff;padding:24px max(18px,calc((100vw - 1080px)/2 + 18px)) 58px}}.header-inner{{max-width:1080px;margin:auto;display:flex;justify-content:space-between;align-items:center}}.brand{{display:flex;align-items:center;gap:14px}}.logo{{width:54px;height:54px;border-radius:15px;background:linear-gradient(145deg,#22a3ff,#0d49d5);display:grid;place-items:center;box-shadow:0 8px 24px rgba(0,0,0,.18)}}.logo svg{{width:32px;height:32px;fill:#fff;stroke:none}}.brand h1{{margin:0;font-size:2rem;letter-spacing:-.03em}}.brand p{{margin:2px 0 0;opacity:.86}}.updated{{font-size:.86rem;opacity:.82;margin-top:5px}}.refresh{{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.1);font-size:24px}}
main{{max-width:1080px;margin:-34px auto 0;padding:0 18px 38px}}.source-strip{{background:#fff;border-radius:16px;box-shadow:var(--shadow);display:grid;grid-template-columns:repeat(4,1fr);padding:10px 6px;margin-bottom:22px}}.source-item{{display:flex;gap:10px;align-items:center;padding:8px 16px;border-right:1px solid var(--line)}}.source-item:last-child{{border-right:0}}.source-icon{{width:34px;height:34px;border-radius:10px;background:#edf4ff;color:var(--blue);display:grid;place-items:center}}.source-item b{{display:block;font-size:.9rem}}.source-item small{{display:flex;gap:5px;align-items:center;color:var(--muted);font-size:.75rem}}.source-item i{{width:8px;height:8px;border-radius:50%;background:#aaa}}.source-item .fresh{{color:var(--green)}}.source-item .fresh i{{background:#27b35f}}.source-item .aging{{color:#b87412}}.source-item .aging i{{background:#f0a22c}}.source-item .stale{{color:var(--red)}}.source-item .stale i{{background:var(--red)}}
.section-title{{display:flex;align-items:center;gap:8px;font-size:1.18rem;margin:24px 4px 12px}}.info{{width:18px;height:18px;border:1px solid #aeb9ca;border-radius:50%;font-size:.7rem;color:#7c899d;display:inline-grid;place-items:center}}.price-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.price-card{{background:#fff;border:1px solid #dfe7f3;border-radius:18px;box-shadow:var(--shadow);padding:18px 20px}}.price-card.blue{{background:linear-gradient(145deg,#fff 55%,#f4f8ff)}}.price-card.green{{background:linear-gradient(145deg,#fff 55%,#f3fbf6)}}.price-top>div{{display:flex;gap:10px;align-items:flex-start}}.dtag{{border-radius:8px;padding:5px 8px;font-weight:800;color:#fff;background:var(--blue)}}.green .dtag{{background:#20a454}}.dayname{{font-weight:700}}.dayname small{{display:block;color:var(--muted);font-size:.76rem;font-weight:500}}.hero-price{{font-size:3rem;font-weight:800;letter-spacing:-.05em;color:#0c46b5;text-align:center;margin:8px 0 6px}}.green .hero-price{{color:#148a49}}.hero-price span{{font-size:.8rem;font-weight:600;letter-spacing:0;color:var(--text)}}.hero-price.small{{font-size:1.5rem;text-align:left;letter-spacing:0;margin-top:28px}}.statrow{{display:grid;grid-template-columns:repeat(3,1fr);text-align:center;color:#55647b;margin:8px 0 14px}}.statrow span+span{{border-left:1px solid var(--line)}}.statrow b{{color:#163b84}}.statrow .good{{color:var(--green)}}.statrow .bad{{color:var(--red)}}.window-grid{{border:1px solid #cfdcf4;background:rgba(244,248,255,.75);border-radius:13px;display:grid;grid-template-columns:1fr 1fr;padding:10px;text-align:center}}.window-grid div+div{{border-left:1px solid var(--line)}}.window-grid span{{display:block;color:#5f6d80;font-size:.75rem}}.window-grid b{{font-size:.9rem}}
.card{{background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:14px 16px}}.tablewrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:760px}}th{{font-size:.72rem;color:#7a8799;text-transform:uppercase;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}td{{padding:8px 10px;border-bottom:1px solid #edf1f6;font-size:.88rem}}td small{{display:block;color:var(--muted);font-size:.72rem}}td.p50{{font-size:1.12rem;font-weight:800;color:#0c49bd}}.change-cell{{font-weight:750}}.change-cell.rise{{color:var(--orange)}}.change-cell.fall{{color:var(--green)}}.risk{{display:inline-block;min-width:92px;text-align:center;border-radius:8px;padding:5px 9px;font-size:.72rem}}.risk.low{{background:#eaf7ef;color:#147b43}}.risk.med{{background:#fff4df;color:#c96c08}}.risk.high{{background:#fdeceb;color:#c82e28}}.mobile-forecast{{display:none}}
.chart-head{{display:flex;justify-content:space-between}}.legend{{display:flex;gap:16px;color:#64738a;font-size:.75rem}}.legend i{{display:inline-block;width:22px;height:3px;background:#1157ca;vertical-align:middle;margin-right:5px}}.legend .band{{height:10px;background:#dce8fb}}.price-chart{{width:100%;height:auto}}.gridline{{stroke:#e7edf5;stroke-width:1}}.axis,.xlab,.xlab2,.value-label{{font-family:inherit;fill:#738198;font-size:10px}}.value-label{{fill:#0b3e99;font-weight:700}}.xlab2{{fill:#42536e;font-weight:700}}.uncertainty{{fill:#dce8fb;opacity:.85;stroke:none}}.p50line{{fill:none;stroke:#0b52c7;stroke-width:3}}.dot{{fill:#fff;stroke:#0b52c7;stroke-width:2.5}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.subhead{{font-size:1.05rem;margin:0 0 10px}}.change-item{{display:flex;gap:11px;align-items:center;padding:10px;border:1px solid #edf1f6;border-radius:12px;margin-top:8px}}.change-icon{{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:#e9f2ff;color:#1a5fcc;flex:0 0 auto}}.change-icon.green{{background:#e8f7ee;color:#15924c}}.change-icon.red{{background:#ffefed;color:#d84a3c}}.change-icon.amber{{background:#fff3df;color:#e38719}}.change-icon.purple{{background:#f0ebff;color:#7656c8}}.change-item b{{display:block;font-size:.86rem}}.change-item small{{display:block;color:var(--muted);font-size:.74rem}}
.model-row{{display:flex;align-items:center;gap:10px;padding:10px 2px;border-bottom:1px solid #edf1f6}}.model-row:last-child{{border-bottom:0}}.model-ic{{color:#255cb2;width:24px;display:grid;place-items:center}}.model-row span{{font-size:.82rem;color:#526179}}.model-row b{{margin-left:auto;font-size:.84rem;color:#173a76}}.model-row b.ready{{color:var(--green)}}
.factor-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.factor{{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px;box-shadow:0 5px 16px rgba(34,58,92,.05)}}.factor-icon{{width:34px;height:34px;border-radius:10px;background:#f0f5fd;color:#2459a8;display:grid;place-items:center;flex:0 0 auto}}.factor small{{display:block;color:#6f7c90;font-size:.72rem}}.factor b{{display:block;font-size:.98rem}}.factor em{{font-style:normal;font-size:.7rem;color:#728096}}footer{{text-align:center;color:#7e8999;font-size:.72rem;padding:24px 0}}
@media(max-width:760px){{.app-header{{padding:18px 14px 48px}}.brand h1{{font-size:1.55rem}}.logo{{width:46px;height:46px}}main{{padding:0 10px 28px}}.source-strip{{grid-template-columns:1fr 1fr;padding:5px}}.source-item{{border-right:0;border-bottom:1px solid var(--line);padding:8px 10px}}.source-item:nth-last-child(-n+2){{border-bottom:0}}.price-grid{{grid-template-columns:1fr}}.desktop-table{{display:none}}.mobile-forecast{{display:flex;gap:10px;overflow-x:auto;padding:2px 1px 8px;scroll-snap-type:x mandatory}}.forecast-day{{min-width:210px;scroll-snap-align:start;border:1px solid var(--line);border-radius:14px;padding:12px;background:#fff;position:relative}}.forecast-day small{{color:var(--muted)}}.mobile-p50{{font-size:1.7rem;font-weight:800;color:#0c49bd;margin:10px 0}}.mobile-p50 small{{font-size:.65rem;margin-left:4px}}.mobile-range{{font-size:.7rem;color:var(--muted)}}.mobile-range b{{font-size:.83rem;color:var(--text)}}.mobile-change{{font-weight:750;font-size:.82rem;margin:8px 0}}.mobile-change.rise{{color:var(--orange)}}.mobile-change.fall{{color:var(--green)}}.mobile-change small{{display:block;font-size:.65rem}}.forecast-day .risk{{position:absolute;right:10px;top:10px;min-width:auto}}.two-col{{grid-template-columns:1fr}}.factor-grid{{grid-template-columns:1fr 1fr}}.legend{{display:none}}.chart-scroll{{overflow-x:auto}}.price-chart{{min-width:720px}}.refresh{{display:none}}}}
</style></head><body>
<header class="app-header"><div class="header-inner"><div class="brand"><span class="logo">{_icon_svg("bolt")}</span><div><h1>Sähköennuste</h1><p>Suomen pörssisähkö</p><div class="updated">◷ Päivitetty {html.escape(str(p["forecast_issue_time"]))}</div></div></div><div class="refresh">↻</div></div></header>
<main><section class="source-strip">{"".join(fresh)}</section>
<h2 class="section-title">Julkaistut day-ahead-hinnat <span class="info">i</span></h2><section class="price-grid">{"".join(pub)}</section>
<h2 class="section-title">D+2–D+12 ennuste <span class="info">i</span></h2><section class="card desktop-table"><div class="tablewrap"><table><thead><tr><th>Päivä</th><th>P50 (snt/kWh)</th><th>P10–P90</th><th>Vs. edellinen</th><th>Riski</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section><section class="mobile-forecast">{"".join(mobile)}</section>
<h2 class="section-title">12 päivän hintakehitys <span class="info">i</span></h2><section class="card"><div class="chart-head"><div class="legend"><span><i></i>P50</span><span><i class="band"></i>P10–P90</span></div></div><div class="chart-scroll">{_chart_svg(p)}</div></section>
<section class="two-col" style="margin-top:16px"><div class="card"><h3 class="subhead">Mitä muuttui <span class="info">i</span></h3>{"".join(changes)}</div><div class="card"><h3 class="subhead">Mallin tila <span class="info">i</span></h3><div class="model-row"><span class="model-ic">{_icon_svg("trophy")}</span><span>Champion</span><b>{html.escape(str(champ["name"]))} {html.escape(str(champ["version"]))}</b></div><div class="model-row"><span class="model-ic">{_icon_svg("brain")}</span><span>Koulutettu ML</span><b>{'Kyllä' if champ.get("trained_ml") else 'Ei vielä'}</b></div><div class="model-row"><span class="model-ic">{_icon_svg("db")}</span><span>Pisteytettyjä tunteja</span><b>{ev["scored_hours"]}</b></div><div class="model-row"><span class="model-ic">{_icon_svg("check")}</span><span>Challenger-koulutus</span><b class="{'ready' if ready else ''}">{'Valmis' if ready else 'Ei vielä'}</b></div></div></section>
<h2 class="section-title">Ennusteen taustatekijät <span class="info">i</span></h2><section class="factor-grid">{"".join(factors)}</section>
<footer>Forecast run: {html.escape(p["forecast_run_id"])} · Electricity Forecaster v1.2 Visual Dashboard</footer></main>
<script>if("serviceWorker" in navigator){{window.addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{{}}));}}</script></body></html>'''
