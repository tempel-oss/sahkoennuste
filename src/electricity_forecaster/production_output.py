
from __future__ import annotations
import json, sqlite3, html, math, statistics
from datetime import datetime, timezone, timedelta
from .config import ROOT, EUR_MWH_TO_SNT_KWH_VAT
from .db import connect, init_db
from .forecast_engine import HELSINKI, resolve_issue_slot
from .model_registry import model_status
from .forecast_quality import quality_summary

# Canonical VAT definition now lives in config.py (see the note there); re-exported
# under this module's previous local name so the usage sites below don't change.
EURMWH_TO_SNTKWH_VAT = EUR_MWH_TO_SNT_KWH_VAT
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

def _three_hour_window(rows, cheapest=True, min_points=3):
    """Cheapest/priciest *complete* rolling 3h window (start on any observed
    timestamp). min_points should reflect the data's native settlement
    resolution (e.g. 12 for 15-min prices, 3 for hourly) - without it, a
    window with only a handful of the ~12 quarter-hour points a real 3h span
    now contains would still pass the old flat '<3' check and could get
    reported as complete when it is actually mostly missing data."""
    if not rows: return None
    rr=sorted(rows,key=lambda x:x[0]); best=None
    for i in range(len(rr)):
        start=rr[i][0]; end=start+timedelta(hours=3)
        vals=[v for dt,v in rr if start <= dt < end]
        if len(vals)<min_points: continue
        score=statistics.mean(vals)
        if best is None or (score < best[0] if cheapest else score > best[0]):
            best=(score,start,end)
    if not best: return None
    return {"window":f"{best[1]:%H:%M}–{best[2]:%H:%M}","mean_eur_mwh":best[0]}

def _published_prices(con, issue_slot, issue_time_utc=None):
    now_local=(issue_time_utc or datetime.now(timezone.utc)).astimezone(HELSINKI)
    wanted=[now_local.date()] if issue_slot=="morning" else [now_local.date(),now_local.date()+timedelta(days=1)]
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
        vals_sorted=sorted(vals,key=lambda x:x[0])
        # The Nordic day-ahead market publishes sub-hourly (15-min) prices; average
        # them per clock hour so the chart/table always show exactly one value per
        # hour, regardless of the underlying settlement resolution. Min/max below
        # stay at the *native* resolution (so they can differ from the hourly
        # chart's cheapest/priciest hour) — carry an explicit detail record for
        # each so the UI can label which resolution/instant they refer to instead
        # of silently mixing the two.
        by_hour={}
        for dt,v in vals_sorted:
            hkey=dt.replace(minute=0,second=0,microsecond=0)
            by_hour.setdefault(hkey,[]).append(v)
        hourly=[{"hour":hkey.hour,"valid_time":hkey.isoformat(),
                 "price_snt_kwh_vat":_safe(statistics.mean(hvals)*EURMWH_TO_SNTKWH_VAT)}
                for hkey,hvals in sorted(by_hour.items())]
        cheapest_hour=min(hourly,key=lambda h:h["price_snt_kwh_vat"]) if hourly else None
        expensive_hour=max(hourly,key=lambda h:h["price_snt_kwh_vat"]) if hourly else None
        steps=[b[0]-a[0] for a,b in zip(vals_sorted,vals_sorted[1:]) if b[0]>a[0]]
        step=min(steps) if steps else timedelta(hours=1)
        step_minutes=max(1,int(round(step.total_seconds()/60)))
        # A "complete" 3h window needs roughly 3h worth of points at whatever the
        # native resolution actually is (12 for 15-min prices, 3 for hourly) -
        # see _three_hour_window's docstring for why this can't stay a flat 3.
        min_points_3h=max(1,round(180/step_minutes))
        cheap3=_three_hour_window(vals,True,min_points_3h)
        exp3=_three_hour_window(vals,False,min_points_3h)
        min_detail=max_detail=None
        if vals_sorted:
            min_dt,min_v=min(vals_sorted,key=lambda x:x[1])
            max_dt,max_v=max(vals_sorted,key=lambda x:x[1])
            min_detail={"price_snt_kwh_vat":_safe(min_v*EURMWH_TO_SNTKWH_VAT),"valid_time":min_dt.isoformat(),
                        "window":f"{min_dt:%H:%M}–{(min_dt+step):%H:%M}","resolution_minutes":step_minutes}
            max_detail={"price_snt_kwh_vat":_safe(max_v*EURMWH_TO_SNTKWH_VAT),"valid_time":max_dt.isoformat(),
                        "window":f"{max_dt:%H:%M}–{(max_dt+step):%H:%M}","resolution_minutes":step_minutes}
        # Full native-resolution series (not just the per-hour average used for
        # the chart) - the consumer page needs this to work out, in the
        # visitor's own browser, which single slot is "right now" (see
        # _sw_script). A static page built once per issue slot but viewed at
        # any later time can't bake that in server-side without it going stale
        # the moment the clock moves past the build time - the same reason the
        # hourly chart's "nyt" marker is drawn client-side rather than here.
        resolution_prices=[{"valid_time":dt.isoformat(),"price_snt_kwh_vat":_safe(v*EURMWH_TO_SNTKWH_VAT)}
                            for dt,v in vals_sorted]
        out.append({
          "date":d.isoformat(),"d_plus":idx,"value_type":"day_ahead","published":bool(prices),
          "mean_snt_kwh_vat":_safe(statistics.mean(prices)*EURMWH_TO_SNTKWH_VAT) if prices else None,
          "min_snt_kwh_vat":_safe(min(prices)*EURMWH_TO_SNTKWH_VAT) if prices else None,
          "max_snt_kwh_vat":_safe(max(prices)*EURMWH_TO_SNTKWH_VAT) if prices else None,
          "min_price_detail":min_detail,"max_price_detail":max_detail,"price_resolution_minutes":step_minutes,
          "cheapest_3h":{"window":cheap3["window"],"mean_snt_kwh_vat":_safe(cheap3["mean_eur_mwh"]*EURMWH_TO_SNTKWH_VAT)} if cheap3 else None,
          "expensive_3h":{"window":exp3["window"],"mean_snt_kwh_vat":_safe(exp3["mean_eur_mwh"]*EURMWH_TO_SNTKWH_VAT)} if exp3 else None,
          "cheapest_hour":cheapest_hour,"expensive_hour":expensive_hour,"hourly":hourly,
          "resolution_prices":resolution_prices,
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
    issue_dt=_parse_dt(meta["issue_time"])
    issue_slot=resolve_issue_slot(issue_dt)
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
          "date":td,"d_plus":int(r["horizon_days"]),"value_type":"forecast",
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
      "schema_version":"1.4",
      "generated_at_utc":datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
      "forecast_run_id":run_id,"forecast_issue_time":meta["issue_time"],"issue_slot":issue_slot,
      "model":{"name":meta["model_name"],"version":meta["model_version"],
               "trained_ml":meta["model_name"]!="fundamental_baseline"},
      "model_status":model_status(),"forecast_quality":quality_summary(),"previous_forecast_run_id":prev["forecast_run_id"] if prev else None,
      "data_quality":meta["data_quality"],"freshness":_freshness(con),
      "published_day_ahead":_published_prices(con,issue_slot,issue_dt),"days":days
    }
    con.close()
    jp=OUTPUT_DIR/"latest_forecast.json"; jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    hp=OUTPUT_DIR/"latest_forecast.html"; hp.write_text(_render_html(payload),encoding="utf-8")
    (OUTPUT_DIR/"index.html").write_text(hp.read_text(encoding="utf-8"),encoding="utf-8")
    dp=OUTPUT_DIR/"diagnostics.html"; dp.write_text(_render_diagnostics_html(payload),encoding="utf-8")
    return jp,hp,len(days)

def _fmt(v): return "—" if v is None else f"{v:.2f}"

def _fmt_fi(v,digits=1):
    """Finnish-style decimal comma formatting, used throughout the redesigned UI."""
    if v is None: return "—"
    try:
        x=float(v)
        if not math.isfinite(x): return "—"
    except Exception:
        return "—"
    x=round(x,digits)
    if x==0: x=0.0  # avoid a stray "-0" from rounding
    return f"{x:.{digits}f}".replace(".", ",")

def _fmt_fi_signed(v,digits=2):
    if v is None: return "—"
    try:
        x=float(v)
        if not math.isfinite(x): return "—"
    except Exception:
        return "—"
    x=round(x,digits)
    if x==0: x=0.0
    sign="+" if x>=0 else ""
    return f"{sign}{x:.{digits}f}".replace(".", ",")

def _fmt_int_fi(n):
    try:
        n=int(n)
    except Exception:
        return "—"
    return f"{n:,}".replace(",", " ")


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
        grid.append(f'<text x="{left-9}" y="{y+4:.1f}" text-anchor="end" class="axis">{_fmt_fi(val,1)}</text>')
    upper=[(X(i),Y(x["p90"] if x["p90"] is not None else x["p50"])) for i,x in enumerate(pts)]
    lower=[(X(i),Y(x["p10"] if x["p10"] is not None else x["p50"])) for i,x in reversed(list(enumerate(pts)))]
    area=" ".join(f"{x:.1f},{y:.1f}" for x,y in upper+lower)
    line=" ".join(f"{X(i):.1f},{Y(x['p50']):.1f}" for i,x in enumerate(pts))
    marks=[]
    for i,x in enumerate(pts):
        xx=X(i); yy=Y(x["p50"])
        marks.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="4" class="dot"/>')
        marks.append(f'<text x="{xx:.1f}" y="{yy-10:.1f}" text-anchor="middle" class="value-label">{_fmt_fi(x["p50"],2)}</text>')
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


def _format_helsinki_time(value):
    """Render an ISO timestamp in Europe/Helsinki local time."""
    try:
        s=str(value).strip()
        if s.endswith("Z"):
            s=s[:-1] + "+00:00"
        dt=datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        local=dt.astimezone(HELSINKI)
        return local.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(value)

def _value_badge(item):
    value_type=item.get("value_type")
    if value_type=="day_ahead":
        if item.get("published",True):
            bg,fg,label="#e8f7ee","#147b43","Julkaistu"
        else:
            bg,fg,label="#fff4df","#b56b0b","Ei julkaistu"
    elif value_type=="forecast":
        bg,fg,label="#eaf1ff","#0e4fc4","Ennuste"
    else:
        bg,fg,label="#eef1f5","#657085","Tuntematon"
    return (f'<span style="display:inline-block;margin-top:5px;border-radius:999px;'
            f'padding:3px 7px;font-size:.64rem;font-weight:800;'
            f'background:{bg};color:{fg}">{label}</span>')


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

# --- Redesigned UI (2026-09): ivory/teal "Kuluttaja" + "Diagnostiikka" two-page layout. ---
# Shared visual language between the two pages below: warm ivory background (#F7F4EC),
# Fraunces for headings, IBM Plex Sans/Mono for body and figures, and a teal<->terracotta
# diverging scale standing in for the old five-colour rainbow (cheap/uncertain <-> expensive/risky).

# Diverging 5-step price-tone ramp: two hues (teal / terracotta) + a neutral gray
# midpoint, each arm monotone in lightness (darkest at the extremes, lightest at the
# neutral centre) and monotone in chroma (most saturated at the extremes) so the
# ramp reads as magnitude, not five arbitrary colours. Validated: OKLCH L/C per stop
# increases/decreases monotonically outward from "normal" on both arms, and every
# dot clears 3:1 contrast against the #F7F4EC page surface (3.35:1-8.57:1).
# Text never wears the tone colour (only the small dot carries identity) — labels
# stay in page ink, per the dataviz skill's "text wears text tokens" rule.
_TONE_META = {
  "price-tone-very-cheap":     ("Erittäin edullinen", "#E4F0EE", "#0B4F49"),
  "price-tone-cheap":          ("Edullinen",           "#EDF3F1", "#527E79"),
  "price-tone-normal":         ("Tavallinen",          "#F1EFE9", "#8A8577"),
  "price-tone-expensive":      ("Kallis",              "#F5EAE6", "#A66258"),
  "price-tone-very-expensive": ("Erittäin kallis",     "#F7E4E0", "#B03A2E"),
  "price-tone-unknown":        ("Ei tietoa",           "#F1EFE9", "#8A8577"),
}
_INK="#1C1B17"

def _tone_pill(tone):
    label,bg,dot=_TONE_META.get(tone,_TONE_META["price-tone-unknown"])
    return (f'<span style="display:inline-flex;align-items:center;gap:6px;background:{bg};'
            f'color:{_INK};padding:7px 13px;border-radius:999px;font-size:14px;font-weight:700;'
            f'white-space:nowrap;"><span style="width:7px;height:7px;border-radius:50%;'
            f'background:{dot};"></span>{html.escape(label)}</span>')

_RISK_META = {"low":("#E4F2EF","#0B6E63"),"med":("#FBEEDD","#D98A3D"),"high":("#F7E4E0","#B03A2E")}

def _risk_class(risk_text):
    r=(risk_text or "—").lower()
    return "high" if "kork" in r else ("low" if "mat" in r else "med")

def _risk_pill(risk_text):
    cls=_risk_class(risk_text)
    bg,dot=_RISK_META[cls]
    label=html.escape(risk_text or "—")
    return (f'<span style="display:inline-flex;align-items:center;gap:5px;background:{bg};'
            f'color:{_INK};padding:5px 11px;border-radius:999px;font-size:13.5px;font-weight:700;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{dot};"></span>{label}</span>')

def _change_arrow(delta):
    if delta is None: return "→","#8A8577"
    if delta>0.0001: return "↑","#B03A2E"
    if delta<-0.0001: return "↓","#0B4F49"
    return "→","#8A8577"

def _factor_value(dg,key,unit):
    """Mirrors the unit-scaling rule used across the app: MW values >=1000 show as GW."""
    x=dg.get(key,{}) or {}
    val=x.get("value")
    if val is None:
        return None,"—",""
    if unit=="MW" and abs(val)>=1000:
        return val,_fmt_fi(val/1000,1),"GW"
    return val,_fmt_fi(val,1),unit

def _narrative_paragraphs(p):
    """Two short, plain-language paragraphs for the consumer page: what changed, and why —
    built from the same change/uncertainty data as the 'Mitä muuttui' diagnostics, so the two
    pages never disagree with each other."""
    items=_change_summary(p)
    sentences=[]
    for _icon,_tone,title,desc in items:
        title=title.rstrip(".")
        sentences.append(f"{title}: {desc}" if desc else f"{title}.")
    para1=" ".join(sentences)

    days=p.get("days",[])
    dg=days[0].get("diagnostics",{}) if days else {}
    _,cons,cons_u=_factor_value(dg,"consumption_forecast","MW")
    _,wind,wind_u=_factor_value(dg,"wind_forecast","MW")
    _,solar,solar_u=_factor_value(dg,"solar_forecast","MW")
    _,temp,temp_u=_factor_value(dg,"temperature","°C")
    lead_bits=[]
    if cons!="—": lead_bits.append(f"sähkönkulutus pysyy korkeana ({cons} {cons_u})")
    if wind!="—": lead_bits.append(f"tuulivoiman tuotanto on {wind} {wind_u}")
    para2=""
    if lead_bits:
        para2="Taustalla vaikuttaa erityisesti "+" ja ".join(lead_bits)+"."
        tail_bits=[]
        if solar!="—": tail_bits.append(f"aurinkovoimaa on tarjolla {solar} {solar_u}")
        if temp!="—": tail_bits.append(f"ilman lämpötila on {temp} {temp_u}")
        if tail_bits:
            extra=" ja ".join(tail_bits)
            para2+=" "+extra[0:1].upper()+extra[1:]+"."
    return para1,para2

def _hourly_bar_chart(hourly, chart_date=None):
    """24-bar hourly price chart for one published day-ahead day: bar height is the
    exact hourly price (zero-baselined, since Finnish spot prices occasionally go
    negative), bar colour is the same 5-step price-tone ramp used on the pill next
    to it, and the cheapest/priciest hour are direct-labelled on the chart itself.
    A native <title> per bar gives a free hover tooltip and is screen-reader
    reachable; the caller also renders a <details> table twin of the same data.

    The viewBox is sized close to the real card width (roughly 280-450px on
    phone/desktop, see .price-grid) rather than the wide 900-unit desktop chart
    used elsewhere on the page: an SVG without an explicit pixel width scales its
    whole coordinate space — including text — down to fit its box, so a viewBox
    far wider than the card was rendering the hour/price labels illegibly small
    on a phone. Keeping the viewBox near 1:1 with the card, and taller/squarer
    than a typical wide line chart, keeps the bars and their labels readable at
    the sizes this chart is actually shown at, with .hourly-chart's own
    (larger) text classes so the separate 12-day chart is untouched.

    This page is static HTML built at forecast-run time (roughly 06:xx and
    16:xx), but is often viewed hours later — a "now" marker computed here,
    server-side, would freeze at the generation time instead of tracking when
    the visitor actually looks at the page. So no "now" line is drawn here at
    all: each bar gets a data-hour attribute and the svg a data-chart-date
    attribute, and a small script at the bottom of the page (see
    _page_scripts) works out the real Europe/Helsinki wall-clock time in the
    visitor's browser and draws the marker onto the matching bar client-side."""
    hourly=[h for h in hourly if h.get("price_snt_kwh_vat") is not None]
    if not hourly:
        return '<div class="empty-chart">Tuntihintoja ei ole vielä saatavilla.</div>'
    n=len(hourly)
    W,H,left,right,top,bottom=360,300,46,10,18,40
    prices=[h["price_snt_kwh_vat"] for h in hourly]
    pmin=min(0.0,min(prices)); pmax=max(prices)
    pad=max(0.3,(pmax-pmin)*0.20)
    ymin=(pmin-pad) if pmin<0 else 0.0
    ymax=pmax+pad
    if ymax-ymin<1: ymax=ymin+1
    plot_w=W-left-right; plot_h=H-top-bottom
    gap=2.5
    bw=max(4.0,(plot_w-(n-1)*gap)/n)
    def X(i): return left+i*(bw+gap)
    def Y(v): return top+plot_h*(1-(float(v)-ymin)/(ymax-ymin))
    y0=Y(0.0)
    cheapest=min(hourly,key=lambda h:h["price_snt_kwh_vat"])
    expensive=max(hourly,key=lambda h:h["price_snt_kwh_vat"])
    grid=[]
    for i in range(4):
        val=ymin+(ymax-ymin)*i/3
        y=Y(val)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{W-right}" y2="{y:.1f}" class="gridline"/>')
        grid.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" class="hbar-axis">{_fmt_fi(val,1)}</text>')
    grid.append(f'<line x1="{left}" y1="{y0:.1f}" x2="{W-right}" y2="{y0:.1f}" class="zeroline"/>')
    bars=[]
    for i,h in enumerate(hourly):
        v=h["price_snt_kwh_vat"]; hr=h["hour"]
        x=X(i); y=Y(v)
        top_y=min(y,y0); bar_h=max(1.5,abs(y-y0))
        color=_TONE_META.get(_price_tone(v),_TONE_META["price-tone-unknown"])[2]
        is_extreme=(h is cheapest) or (h is expensive)
        label=f"klo {hr:02d}–{(hr+1)%24:02d}: {_fmt_fi(v,2)} snt/kWh"
        bars.append(
          f'<rect x="{x:.1f}" y="{top_y:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" rx="3" data-hour="{hr}" '
          f'fill="{color}" opacity="{1.0 if is_extreme else 0.8}"><title>{html.escape(label)}</title></rect>'
        )
        if hr%3==0:
            bars.append(f'<text x="{x+bw/2:.1f}" y="{H-bottom+20}" text-anchor="middle" class="hbar-hourlab">{hr:02d}</text>')
    for h in (cheapest,expensive):
        i=hourly.index(h); x=X(i)+bw/2; y=min(Y(h["price_snt_kwh_vat"]),y0)
        anchor,lx="middle",x
        if i<=1: anchor,lx="start",X(i)
        elif i>=n-2: anchor,lx="end",X(i)+bw
        bars.append(f'<text x="{lx:.1f}" y="{y-8:.1f}" text-anchor="{anchor}" class="hbar-valuelabel">{_fmt_fi(h["price_snt_kwh_vat"],2)}</text>')
    date_attr=f' data-chart-date="{html.escape(chart_date)}"' if chart_date else ''
    return (f'<svg class="hourly-chart" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet"{date_attr} '
            f'data-now-top="{top-6}" data-now-label-y="{top-9}" data-now-bottom="{H-bottom}">'
            f'{"".join(grid)}{"".join(bars)}</svg>')

def _hourly_table(hourly):
    """Accessible table twin of the hourly bar chart, tucked behind a native
    <details> disclosure so it doesn't compete with the chart for attention."""
    hourly=[h for h in hourly if h.get("price_snt_kwh_vat") is not None]
    if not hourly:
        return ""
    rows=[]
    for h in hourly:
        hr=h["hour"]; v=h["price_snt_kwh_vat"]
        pill=_tone_pill(_price_tone(v))
        rows.append(f'<tr><td style="padding:7px 10px;border-bottom:1px solid rgba(28,27,23,0.06);font-family:\'IBM Plex Mono\',monospace;">{hr:02d}–{(hr+1)%24:02d}</td>'
                    f'<td style="padding:7px 10px;border-bottom:1px solid rgba(28,27,23,0.06);font-family:\'IBM Plex Mono\',monospace;font-weight:600;">{_fmt_fi(v,2)}</td>'
                    f'<td style="padding:7px 10px;border-bottom:1px solid rgba(28,27,23,0.06);">{pill}</td></tr>')
    return (f'<details style="margin-top:10px;"><summary style="cursor:pointer;font-size:14px;font-weight:600;color:#0B4F49;">Näytä kaikki tunnit</summary>'
            f'<div style="overflow-x:auto;margin-top:10px;"><table style="width:100%;min-width:280px;">'
            f'<thead><tr><th style="text-align:left;font-size:12.5px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:6px 10px;">Klo</th>'
            f'<th style="text-align:left;font-size:12.5px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:6px 10px;">snt/kWh</th>'
            f'<th style="text-align:left;font-size:12.5px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:6px 10px;">Luokka</th></tr></thead>'
            f'<tbody style="font-size:14.5px;">{"".join(rows)}</tbody></table></div></details>')

_SHARED_STYLE = """
  body{margin:0;background:#F7F4EC;}
  a{color:#0B4F49;text-decoration:none;}
  a:hover{color:#0B6E63;}
  .stat-col+.stat-col{border-left:1px solid rgba(28,27,23,0.08);}
  table{border-collapse:collapse;}
  .gridline{stroke:#E7E3D9;stroke-width:1;}
  .zeroline{stroke:#C9C4B4;stroke-width:1.2;}
  .nowline{stroke:#1C1B17;stroke-width:1;stroke-dasharray:2,2;opacity:.55;}
  .nowlabel{font-family:'IBM Plex Sans',sans-serif;font-size:11px;font-weight:700;fill:#1C1B17;}
  .hourlab{font-family:'IBM Plex Mono',monospace;font-size:11px;fill:#8A8577;}
  .axis,.xlab{font-family:'IBM Plex Mono',monospace;font-size:12px;fill:#8A8577;}
  .xlab2{font-family:'IBM Plex Sans',sans-serif;font-size:12px;font-weight:700;fill:#3A382F;}
  .value-label{font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:700;fill:#1C1B17;}
  /* Hourly bar chart: rendered at a viewBox close to its real card width (see
     _hourly_bar_chart), so it gets its own larger text classes rather than
     reusing .axis/.value-label — those stay tuned for the wide 12-day chart. */
  .hourly-chart{width:100%;height:auto;display:block;}
  .hbar-nowlabel{font-family:'IBM Plex Sans',sans-serif;font-size:13px;font-weight:700;fill:#1C1B17;}
  .hbar-hourlab{font-family:'IBM Plex Mono',monospace;font-size:13px;fill:#8A8577;}
  .hbar-axis{font-family:'IBM Plex Mono',monospace;font-size:13px;fill:#8A8577;}
  .hbar-valuelabel{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:700;fill:#1C1B17;}
  .uncertainty{fill:#DCEDEA;opacity:.9;stroke:none;}
  .p50line{fill:none;stroke:#0B4F49;stroke-width:2.5;}
  .dot{fill:#F7F4EC;stroke:#0B4F49;stroke-width:2.5;}
  .empty-chart{padding:24px;text-align:center;color:#8A8577;font-size:14px;}
"""

_FONT_LINK = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600;700;900&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">'

def _page_head(title):
    return (f'<!doctype html><html lang="fi"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0B4F49">'
            f'<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icons/icon-192.png">'
            f'<link rel="apple-touch-icon" href="icons/icon-192.png">{_FONT_LINK}<title>{title}</title>')

def _sw_script():
    return ('''<script>
(function(){
  function parseUtc(raw){
    if(!raw) return null;
    raw=String(raw).trim();
    if(raw.endsWith("Z")) return new Date(raw);
    if(/[+-]\\d{2}:\\d{2}$/.test(raw)) return new Date(raw);
    return new Date(raw + "Z");
  }
  function renderHelsinki(){
    const el=document.getElementById("updated-local");
    if(!el) return;
    const d=parseUtc(el.dataset.utc || "");
    if(!d || isNaN(d.getTime())) return;
    const formatted=new Intl.DateTimeFormat("fi-FI",{
      timeZone:"Europe/Helsinki",
      day:"2-digit",month:"2-digit",year:"numeric",
      hour:"2-digit",minute:"2-digit",
      hour12:false
    }).format(d);
    el.textContent=formatted;
    el.title="Europe/Helsinki";
  }
  renderHelsinki();
  if("serviceWorker" in navigator){
    window.addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{}));
  }
  // The hourly price chart is static HTML built at forecast-run time
  // (roughly 06:xx/16:xx), often viewed hours later, so the "now" marker on
  // it cannot be baked in server-side — it would freeze at generation time
  // instead of showing when the visitor is actually looking. Each bar carries
  // a data-hour attribute and its chart a data-chart-date attribute; this
  // works out the real Europe/Helsinki wall-clock time in the visitor's own
  // browser (regardless of the visitor's device timezone) and draws the
  // marker onto the matching bar, re-checking every minute in case the page
  // is left open across an hour boundary.
  function helsinkiNow(){
    const fmt=new Intl.DateTimeFormat("en-CA",{
      timeZone:"Europe/Helsinki",year:"numeric",month:"2-digit",day:"2-digit",
      hour:"2-digit",hour12:false
    });
    const parts={};
    fmt.formatToParts(new Date()).forEach(p=>{ parts[p.type]=p.value; });
    let hour=parseInt(parts.hour,10);
    if(!Number.isFinite(hour) || hour===24) hour=0;
    return {date:`${parts.year}-${parts.month}-${parts.day}`,hour:hour};
  }
  function positionNowMarkers(){
    let now;
    try{ now=helsinkiNow(); }catch(e){ return; }
    document.querySelectorAll("svg.hourly-chart[data-chart-date]").forEach((svg)=>{
      svg.querySelectorAll(".js-nowline,.js-nowlabel").forEach((el)=>el.remove());
      if(svg.getAttribute("data-chart-date")!==now.date) return;
      const bar=svg.querySelector('rect[data-hour="'+now.hour+'"]');
      if(!bar) return;
      const x=parseFloat(bar.getAttribute("x")), w=parseFloat(bar.getAttribute("width"));
      if(!Number.isFinite(x) || !Number.isFinite(w)) return;
      const nx=(x+w/2).toFixed(1);
      const top=svg.getAttribute("data-now-top"), labelY=svg.getAttribute("data-now-label-y"),
            bottom=svg.getAttribute("data-now-bottom");
      const ns="http://www.w3.org/2000/svg";
      const line=document.createElementNS(ns,"line");
      line.setAttribute("x1",nx); line.setAttribute("y1",top);
      line.setAttribute("x2",nx); line.setAttribute("y2",bottom);
      line.setAttribute("class","nowline js-nowline");
      const label=document.createElementNS(ns,"text");
      label.setAttribute("x",nx); label.setAttribute("y",labelY);
      label.setAttribute("text-anchor","middle");
      label.setAttribute("class","hbar-nowlabel js-nowlabel");
      label.textContent="nyt";
      svg.appendChild(line); svg.appendChild(label);
    });
  }
  positionNowMarkers();
  setInterval(positionNowMarkers,60000);

  // "Tämän hetken pörssihinta" banner: each point below carries an absolute
  // timestamp (t, with its UTC offset) and its settlement length in minutes
  // (r), so - unlike the hourly chart's "nyt" marker, which has to match a
  // specific calendar day/hour in Helsinki time - this can just compare
  // real instants: no timezone reconstruction needed, it works the same
  // regardless of the visitor's own device timezone.
  function findCurrentPrice(points){
    const now=new Date();
    for(const pt of points){
      const start=new Date(pt.t);
      if(isNaN(start.getTime())) continue;
      const end=new Date(start.getTime()+pt.r*60000);
      if(now>=start && now<end) return {price:pt.v,start:start,end:end};
    }
    return null;
  }
  function renderNowPrice(){
    const dataEl=document.getElementById("now-price-data");
    const valueEl=document.getElementById("now-price-value");
    const windowEl=document.getElementById("now-price-window");
    if(!dataEl || !valueEl || !windowEl) return;
    let points;
    try{ points=JSON.parse(dataEl.textContent || "[]"); }catch(e){ return; }
    const hit=findCurrentPrice(points);
    if(!hit){
      valueEl.textContent="—";
      windowEl.textContent="Tämän hetken hintaa ei ole vielä saatavilla.";
      return;
    }
    valueEl.textContent=hit.price.toFixed(2).replace(".",",");
    const fmt=new Intl.DateTimeFormat("fi-FI",{timeZone:"Europe/Helsinki",hour:"2-digit",minute:"2-digit",hour12:false});
    windowEl.textContent="klo "+fmt.format(hit.start)+"–"+fmt.format(hit.end);
  }
  renderNowPrice();
  setInterval(renderNowPrice,60000);
})();
</script>''')

def _render_html(p):
    """Consumer page ('Kuluttaja'): today/tomorrow price, the 12-day outlook, a short
    plain-language recap of what changed and why, and a link through to Diagnostiikka."""
    accent="#0B4F49"
    pub_cards=[]
    for x in p.get("published_day_ahead",[]):
        d_plus=x.get("d_plus",0)
        dlabel="Tänään" if d_plus==0 else ("Huomenna" if d_plus==1 else f"D+{d_plus}")
        if x.get("published"):
            pill=_tone_pill(_price_tone(x.get("mean_snt_kwh_vat")))
            hourly=x.get("hourly") or []
            cheap_h=x.get("cheapest_hour"); exp_h=x.get("expensive_hour")
            min_d=x.get("min_price_detail"); max_d=x.get("max_price_detail")
            res_min=x.get("price_resolution_minutes") or 60
            def _hr_range(h): return f'klo {h["hour"]:02d}–{(h["hour"]+1)%24:02d}' if h else "—"
            def _res_caption(detail):
                # Only worth calling out when the native resolution is finer than
                # an hour — at plain hourly resolution this would just repeat the
                # cheapest/priciest-hour line below.
                if not detail or detail.get("resolution_minutes",60)>=60: return ""
                return (f'<div style="font-size:11px;color:#8A8577;margin-top:3px;line-height:1.3;">'
                        f'klo {detail["window"]}<br>({detail["resolution_minutes"]} min)</div>')
            chart_svg=_hourly_bar_chart(hourly, chart_date=x.get("date"))
            table_html=_hourly_table(hourly)
            res_note=(f'Kaavio: tuntien keskiarvohinnat ({res_min} min -pohjadatasta)' if res_min!=60
                       else 'Kaavio: tuntihinnat')
            cheap3=x.get("cheapest_3h"); exp3=x.get("expensive_3h")
            def _3h_line(win):
                if not win: return "—"
                return f'{win["window"]} · {_fmt_fi(win.get("mean_snt_kwh_vat"),2)}'
            pub_cards.append(f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:18px;padding:26px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;gap:10px;">
          <div>
            <div style="font-size:15px;font-weight:700;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;">{html.escape(dlabel)}</div>
            <div style="font-size:14px;color:#8A8577;margin-top:2px;">{_weekday_fi(x["date"])} · julkaistu</div>
          </div>
          {pill}
        </div>
        <div style="font-size:13px;font-weight:700;color:#8A8577;text-align:center;text-transform:uppercase;letter-spacing:0.04em;">Päivän keskihinta</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:58px;line-height:1;color:#1C1B17;text-align:center;margin:6px 0 8px;">{_fmt_fi(x.get("mean_snt_kwh_vat"),2)}<span style="font-size:17px;font-weight:500;color:#8A8577;margin-left:6px;">snt/kWh</span></div>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);text-align:center;margin:22px 0 18px;padding:14px 0;border-top:1px solid rgba(28,27,23,0.08);border-bottom:1px solid rgba(28,27,23,0.08);">
          <div class="stat-col"><div style="font-size:13px;color:#8A8577;margin-bottom:4px;">Min</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:18px;">{_fmt_fi(x.get("min_snt_kwh_vat"),2)}</div>{_res_caption(min_d)}</div>
          <div class="stat-col"><div style="font-size:13px;color:#8A8577;margin-bottom:4px;">Max</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:18px;">{_fmt_fi(x.get("max_snt_kwh_vat"),2)}</div>{_res_caption(max_d)}</div>
        </div>
        <div style="font-size:12px;color:#8A8577;margin-bottom:6px;">{html.escape(res_note)}</div>
        <div style="margin:4px 0 2px;">{chart_svg}</div>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:6px;">
          <div style="display:flex;align-items:center;gap:6px;font-size:13.5px;color:#3A382F;min-width:0;"><span style="width:6px;height:6px;border-radius:50%;background:#0B4F49;flex:0 0 auto;"></span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;">Halvin tunti: <b style="font-family:'IBM Plex Mono',monospace;">{_hr_range(cheap_h)} · {_fmt_fi(cheap_h["price_snt_kwh_vat"] if cheap_h else None,2)}</b></span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:13.5px;color:#3A382F;min-width:0;"><span style="width:6px;height:6px;border-radius:50%;background:#B03A2E;flex:0 0 auto;"></span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;">Kallein tunti: <b style="font-family:'IBM Plex Mono',monospace;">{_hr_range(exp_h)} · {_fmt_fi(exp_h["price_snt_kwh_vat"] if exp_h else None,2)}</b></span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:13.5px;color:#3A382F;min-width:0;"><span style="width:6px;height:6px;border-radius:50%;background:#0B4F49;opacity:0.5;flex:0 0 auto;"></span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;">Halvin 3 h: <b style="font-family:'IBM Plex Mono',monospace;">{html.escape(_3h_line(cheap3))}</b></span></div>
          <div style="display:flex;align-items:center;gap:6px;font-size:13.5px;color:#3A382F;min-width:0;"><span style="width:6px;height:6px;border-radius:50%;background:#B03A2E;opacity:0.5;flex:0 0 auto;"></span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;">Kallein 3 h: <b style="font-family:'IBM Plex Mono',monospace;">{html.escape(_3h_line(exp3))}</b></span></div>
        </div>
        {table_html}
      </div>''')
        else:
            pub_cards.append(f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:18px;padding:26px;">
        <div style="font-size:15px;font-weight:700;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;">{html.escape(dlabel)}</div>
        <div style="font-size:14px;color:#8A8577;margin-top:2px;margin-bottom:18px;">{_weekday_fi(x["date"])}</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:22px;color:#8A8577;">Ei vielä julkaistu</div>
        <div style="font-size:14px;color:#8A8577;margin-top:8px;">FI day-ahead -hintaa ei ole vielä tietokannassa.</div>
      </div>''')

    days=p.get("days",[])
    p10s=[d["p10_snt_kwh_vat"] for d in days if d.get("p10_snt_kwh_vat") is not None]
    p90s=[d["p90_snt_kwh_vat"] for d in days if d.get("p90_snt_kwh_vat") is not None]
    gmin=min(p10s) if p10s else 0.0
    gmax=max(p90s) if p90s else 1.0
    gspan=(gmax-gmin) or 1.0
    BAR_W=160.0
    def _pos(v):
        if v is None: return 0.0
        return max(0.0,min(BAR_W,(float(v)-gmin)/gspan*BAR_W))

    rows=[]; mobile=[]
    for d in days:
        p10=d.get("p10_snt_kwh_vat"); p50=d.get("p50_snt_kwh_vat"); p90=d.get("p90_snt_kwh_vat")
        left=_pos(p10); right=_pos(p90); width=max(2.0,right-left); marker=_pos(p50)
        ch=d.get("change_from_previous"); delta=float(ch["delta"]) if ch and ch.get("delta") is not None else None
        arrow,arrow_color=_change_arrow(delta)
        change=_fmt_fi_signed(delta,2)
        risk_pill=_risk_pill(d.get("risk"))
        rows.append(f'''<tr><td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);"><b>D+{d["d_plus"]}</b><br><span style="color:#8A8577;font-size:13.5px;">{_weekday_fi(d["date"])}</span></td>
      <td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);"><div style="position:relative;width:{BAR_W:.0f}px;height:16px;"><div style="position:absolute;left:1px;top:6px;width:{BAR_W-2:.0f}px;height:4px;background:rgba(28,27,23,0.07);border-radius:2px;"></div><div style="position:absolute;left:{left:.1f}px;top:6px;width:{width:.1f}px;height:4px;background:rgba(11,79,73,0.35);border-radius:2px;"></div><div style="position:absolute;left:{marker:.1f}px;top:2px;width:3px;height:12px;background:#0B4F49;border-radius:2px;"></div></div><span style="font-family:'IBM Plex Mono',monospace;font-weight:600;">{_fmt_fi(p50,2)}</span></td>
      <td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="color:{arrow_color};font-weight:700;">{arrow}</span> <span style="font-family:'IBM Plex Mono',monospace;">{change}</span></td>
      <td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);">{risk_pill}</td></tr>''')
        mobile.append(f'''<div style="min-width:180px;background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:14px;padding:14px;flex:0 0 auto;"><b style="font-size:16px;">D+{d["d_plus"]}</b><br><span style="color:#8A8577;font-size:14px;">{_weekday_fi(d["date"])}</span><div style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:28px;margin:8px 0;">{_fmt_fi(p50,2)}</div>{risk_pill}</div>''')

    # Data for the shared "Tämän hetken pörssihinta" banner: the full native-
    # resolution price series for every *published* day (today, and tomorrow
    # once it's out), tagged with each point's settlement length. Rendered
    # client-side (see _sw_script) for the same reason the hourly chart's
    # "nyt" marker is - this static page is built once per issue slot but can
    # be viewed hours later, so "now" can only be resolved correctly in the
    # visitor's own browser at view time, never baked in here at build time.
    now_price_points=[]
    for x in p.get("published_day_ahead",[]):
        if not x.get("published"): continue
        res_min=x.get("price_resolution_minutes") or 60
        for pt in x.get("resolution_prices") or []:
            if pt.get("price_snt_kwh_vat") is None: continue
            now_price_points.append({"t":pt["valid_time"],"v":pt["price_snt_kwh_vat"],"r":res_min})
    now_price_data_json=json.dumps(now_price_points,ensure_ascii=False)

    para1,para2=_narrative_paragraphs(p)
    narrative_html=f'<p style="font-size:17px;line-height:1.65;color:#3A382F;margin:0 0 10px;">{html.escape(para1)}</p>'
    if para2:
        narrative_html+=f'<p style="font-size:17px;line-height:1.65;color:#3A382F;margin:0;">{html.escape(para2)}</p>'

    forecast_days=p.get("days",[])
    if forecast_days:
        hmin=min(int(d["d_plus"]) for d in forecast_days); hmax=max(int(d["d_plus"]) for d in forecast_days)
        forecast_heading=f"D+{hmin} – D+{hmax} ennuste"
    else:
        forecast_heading="Ennuste"

    return f'''{_page_head("Sähköennuste")}
<style>{_SHARED_STYLE}
  .desktop-table{{display:block;}}
  .mobile-forecast{{display:none;}}
  @media (max-width:760px){{
    .price-grid{{grid-template-columns:1fr !important;}}
    .desktop-table{{display:none !important;}}
    .mobile-forecast{{display:flex !important;}}
    .chart-scroll{{overflow-x:auto;}}
    .price-chart{{min-width:720px;}}
  }}
</style></head><body>
<div style="width:100%;min-height:100vh;box-sizing:border-box;font-family:'IBM Plex Sans',sans-serif;color:#1C1B17;">
  <div style="width:100%;background:{accent};color:#F7F4EC;box-sizing:border-box;padding:18px 40px;display:flex;align-items:center;justify-content:space-between;gap:24px;">
    <div style="display:flex;align-items:center;gap:14px;">
      <span style="width:40px;height:40px;border-radius:10px;background:rgba(247,244,236,0.14);display:flex;align-items:center;justify-content:center;flex:0 0 auto;">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#F7F4EC" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13.2 2 5 13h6l-.8 9L19 10h-6.2L13.2 2Z"></path></svg>
      </span>
      <div>
        <div style="font-family:'Fraunces',serif;font-weight:700;font-size:23px;letter-spacing:-0.01em;line-height:1.1;">Sähköennuste</div>
        <div style="font-size:14px;opacity:0.75;margin-top:2px;">Suomen pörssisähkö</div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:20px;">
      <div style="text-align:right;font-size:13px;opacity:0.75;line-height:1.4;">
        <div>Päivitetty</div>
        <div id="updated-local" data-utc="{html.escape(str(p["forecast_issue_time"]))}" style="font-family:'IBM Plex Mono',monospace;">{_format_helsinki_time(p["forecast_issue_time"])}</div>
      </div>
      <div style="display:flex;gap:3px;background:rgba(247,244,236,0.14);padding:4px;border-radius:999px;">
        <span style="padding:9px 17px;border-radius:999px;font-size:15px;font-weight:700;background:#F7F4EC;color:{accent};">Kuluttaja</span>
        <a href="diagnostics.html" style="padding:9px 17px;border-radius:999px;font-size:15px;font-weight:600;color:rgba(247,244,236,0.82);">Diagnostiikka</a>
      </div>
    </div>
  </div>

  <div style="max-width:1040px;margin:0 auto;padding:36px 24px 72px;">

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">Julkaistut day-ahead-hinnat</div>
    <h1 style="font-family:'Fraunces',serif;font-weight:600;font-size:27px;margin:0 0 18px;color:#1C1B17;">Sähkön hinta juuri nyt</h1>

    <div id="now-price-banner" style="background:{accent};color:#F7F4EC;border-radius:16px;padding:22px 26px;margin-bottom:22px;">
      <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;opacity:0.82;font-weight:700;margin-bottom:6px;">Tämän hetken pörssihinta</div>
      <div style="font-family:'Fraunces',serif;font-weight:600;font-size:44px;line-height:1;">
        <span id="now-price-value">—</span><span style="font-family:'IBM Plex Sans',sans-serif;font-size:16px;font-weight:500;opacity:0.85;margin-left:6px;">snt/kWh</span>
      </div>
      <div id="now-price-window" style="font-size:13.5px;opacity:0.82;margin-top:6px;">&nbsp;</div>
    </div>
    <script type="application/json" id="now-price-data">{now_price_data_json}</script>

    <div class="price-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:36px;">{"".join(pub_cards)}</div>

    <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:18px;padding:26px 28px;margin-bottom:36px;">
      <h2 style="font-family:'Fraunces',serif;font-weight:600;font-size:21px;margin:0 0 12px;">Mitä muuttui ja miksi</h2>
      {narrative_html}
      <a href="diagnostics.html" style="display:inline-flex;align-items:center;gap:6px;margin-top:16px;font-size:15.5px;font-weight:600;">
        Näytä mallin tarkkuus ja tausta-analytiikka
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>
      </a>
    </div>

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">{html.escape(forecast_heading)}</div>
    <h2 style="font-family:'Fraunces',serif;font-weight:600;font-size:22px;margin:0 0 14px;">Seuraavat päivät</h2>
    <div class="desktop-table" style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:18px;padding:8px 16px;margin-bottom:36px;overflow-x:auto;">
      <table style="width:100%;min-width:680px;"><thead><tr>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">Päivä</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">Hinta-arvio (snt/kWh)</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">Muutos</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">Vaihtelu</th>
      </tr></thead><tbody style="font-size:15.5px;">{"".join(rows)}</tbody></table>
    </div>
    <div class="mobile-forecast" style="gap:10px;overflow-x:auto;margin-bottom:36px;padding-bottom:6px;">{"".join(mobile)}</div>

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">Hintakehitys</div>
    <h2 style="font-family:'Fraunces',serif;font-weight:600;font-size:22px;margin:0 0 14px;">Hinta-arvion kehitys</h2>
    <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:18px;padding:20px 16px;margin-bottom:8px;">
      <div style="display:flex;gap:18px;font-size:14.5px;color:#6B6558;margin-bottom:8px;">
        <span style="display:flex;align-items:center;gap:6px;"><span style="width:20px;height:2.5px;background:#0B4F49;display:inline-block;"></span>P50 (mediaani)</span>
        <span style="display:flex;align-items:center;gap:6px;"><span style="width:20px;height:9px;background:#DCEDEA;display:inline-block;"></span>P10–P90 (epävarmuus)</span>
      </div>
      <div class="chart-scroll">{_chart_svg(p)}</div>
    </div>

    <div style="text-align:center;color:#8A8577;font-size:13.5px;padding:22px 0 4px;">
      Forecast run: {html.escape(p["forecast_run_id"])} · Electricity Forecaster v1.4.1 ·
      <a href="diagnostics.html" style="font-weight:600;">Diagnostiikka →</a>
    </div>
  </div>
</div>
{_sw_script()}
</body></html>'''

def _render_diagnostics_html(p):
    """Diagnostics page ('Diagnostiikka'): model quality, Champion/Challenger status,
    readiness gates, raw background factors and upstream data freshness — kept separate
    from the consumer page so day-to-day users aren't shown ML-readiness internals."""
    accent="#0B4F49"
    ms=p.get("model_status",{}) or {}
    ev=ms.get("evaluation",{}) or {}
    champ=ms.get("champion",{}) or {}
    ready=ms.get("challenger_training_ready")
    fq=p.get("forecast_quality",{}) or {}
    qo=fq.get("overall",{}) or {}
    scored_hours=int(fq.get("scored_hours",0) or 0)
    scored_runs=int(fq.get("scored_forecast_runs",0) or 0)
    train_hours_pct=min(100,round(scored_hours/1000*100)) if scored_hours>=0 else 0
    train_runs_pct=min(100,round(scored_runs/20*100)) if scored_runs>=0 else 0
    train_pct=min(train_hours_pct,train_runs_pct)
    wf_hours_pct=min(100,round(scored_hours/1500*100)) if scored_hours>=0 else 0
    wf_runs_pct=min(100,round(scored_runs/30*100)) if scored_runs>=0 else 0
    wf_pct=min(wf_hours_pct,wf_runs_pct)
    cov="—" if qo.get("p10_p90_coverage") is None else f"{qo['p10_p90_coverage']*100:.0f} %"

    quality_kpis=f'''<div class="quality-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:36px;">
      <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-top:3px solid {accent};border-radius:14px;padding:16px;">
        <div style="font-size:14px;color:#8A8577;margin-bottom:6px;">MAE</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:28px;">{_fmt_fi(qo.get("mae_eur_mwh"),2)}</div><div style="font-size:13px;color:#8A8577;margin-top:2px;">EUR/MWh</div>
      </div>
      <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-top:3px solid {accent};border-radius:14px;padding:16px;">
        <div style="font-size:14px;color:#8A8577;margin-bottom:6px;">Bias</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:28px;">{_fmt_fi(qo.get("bias_eur_mwh"),2)}</div><div style="font-size:13px;color:#8A8577;margin-top:2px;">EUR/MWh</div>
      </div>
      <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-top:3px solid {accent};border-radius:14px;padding:16px;">
        <div style="font-size:14px;color:#8A8577;margin-bottom:6px;">P10–P90 peitto</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:28px;">{cov}</div><div style="font-size:13px;color:#8A8577;margin-top:2px;">toteutuneista</div>
      </div>
      <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-top:3px solid {accent};border-radius:14px;padding:16px;">
        <div style="font-size:14px;color:#8A8577;margin-bottom:6px;">Pisteytetty</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:28px;">{_fmt_int_fi(scored_hours)}</div><div style="font-size:13px;color:#8A8577;margin-top:2px;">tuntia</div>
      </div>
    </div>'''

    qrows=[]
    for h,m in fq.get("by_horizon",{}).items():
        if m.get("n",0):
            hc="—" if m.get("p10_p90_coverage") is None else f"{m['p10_p90_coverage']*100:.0f} %"
            qrows.append(f'<tr><td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);font-family:\'IBM Plex Sans\',sans-serif;font-weight:700;">D+{h}</td><td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);">{_fmt_int_fi(m["n"])}</td><td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);">{_fmt_fi(m.get("mae_eur_mwh"),2)}</td><td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);">{_fmt_fi(m.get("bias_eur_mwh"),2)}</td><td style="padding:11px 10px;border-bottom:1px solid rgba(28,27,23,0.06);">{hc}</td></tr>')
    quality_table=f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:18px;padding:8px 16px;margin-bottom:36px;overflow-x:auto;">
      <table style="width:100%;min-width:560px;"><thead><tr>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">Horisontti</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">n</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">MAE</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">Bias</th>
        <th style="text-align:left;font-size:13px;color:#8A8577;text-transform:uppercase;letter-spacing:0.03em;padding:12px 10px;border-bottom:1px solid rgba(28,27,23,0.08);">P10–P90</th>
      </tr></thead><tbody style="font-family:'IBM Plex Mono',monospace;font-size:15.5px;">{"".join(qrows)}</tbody></table>
    </div>'''

    readiness_html=f'''<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:36px;" class="readiness-grid">
      <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:16px;padding:20px;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:15px;color:#6B6558;margin-bottom:10px;"><span>Challenger-koulutusvalmius</span><b style="font-family:'IBM Plex Mono',monospace;color:#1C1B17;font-size:18px;">{train_pct} %</b></div>
        <div style="height:9px;background:rgba(28,27,23,0.07);border-radius:999px;overflow:hidden;"><div style="height:100%;width:{train_pct}%;background:{accent};border-radius:999px;"></div></div>
        <div style="font-size:13.5px;color:#8A8577;margin-top:8px;">{_fmt_int_fi(scored_hours)}/1 000 tuntia · {scored_runs}/20 ajoa</div>
      </div>
      <div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:16px;padding:20px;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:15px;color:#6B6558;margin-bottom:10px;"><span>Walk-forward-valmius</span><b style="font-family:'IBM Plex Mono',monospace;color:#1C1B17;font-size:18px;">{wf_pct} %</b></div>
        <div style="height:9px;background:rgba(28,27,23,0.07);border-radius:999px;overflow:hidden;"><div style="height:100%;width:{wf_pct}%;background:{accent};border-radius:999px;"></div></div>
        <div style="font-size:13.5px;color:#8A8577;margin-top:8px;">{_fmt_int_fi(scored_hours)}/1 500 tuntia · {scored_runs}/30 ajoa</div>
      </div>
    </div>'''

    ready_pill=(f'<span style="display:inline-flex;align-items:center;gap:6px;background:#E4F2EF;color:#0B4F49;padding:5px 11px;border-radius:999px;font-size:14px;font-weight:700;">'
                f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#0B4F49" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4 10-10"></path></svg>Valmis</span>'
                if ready else
                '<span style="display:inline-flex;align-items:center;gap:6px;background:#F1EFE9;color:#6B6558;padding:5px 11px;border-radius:999px;font-size:14px;font-weight:700;">Ei vielä</span>')
    model_html=f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:16px;padding:6px 22px;margin-bottom:36px;">
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="font-size:15.5px;color:#3A382F;flex:1;">Champion</span><b style="font-family:'IBM Plex Mono',monospace;font-size:15.5px;">{html.escape(str(champ.get("name","—")))} {html.escape(str(champ.get("version","")))}</b></div>
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="font-size:15.5px;color:#3A382F;flex:1;">Koulutettu ML-malli</span><span style="display:inline-flex;align-items:center;gap:6px;background:#F1EFE9;color:#6B6558;padding:5px 11px;border-radius:999px;font-size:14px;font-weight:700;">{"Kyllä" if champ.get("trained_ml") else "Ei vielä"}</span></div>
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="font-size:15.5px;color:#3A382F;flex:1;">Pisteytettyjä tunteja</span><b style="font-family:'IBM Plex Mono',monospace;font-size:15.5px;">{_fmt_int_fi(ev.get("scored_hours",0))}</b></div>
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;"><span style="font-size:15.5px;color:#3A382F;flex:1;">Challenger-koulutus</span>{ready_pill}</div>
    </div>'''

    chall=ms.get("challenger") or {}
    if chall:
        c_n=chall.get("walk_forward_n")
        c_skill=chall.get("walk_forward_mae_skill_pct")
        c_champ_mae=chall.get("walk_forward_champion_mae_eur_mwh")
        c_chall_mae=chall.get("walk_forward_challenger_mae_eur_mwh")
        c_thin=chall.get("sample_is_thin")
        c_better=chall.get("outperforms_champion")
        if c_better and not c_thin:
            v_bg,v_fg,v_text="#E4F2EF","#0B4F49","Parempi kuin Champion — harkitaan jatkoarviointia"
        elif c_skill is not None and c_skill < 0:
            v_bg,v_fg,v_text="#FBECEA","#8C2E22",f"{abs(c_skill):.0f} % huonompi kuin Champion — ei suositella tuotantoon"
        else:
            v_bg,v_fg,v_text="#F1EFE9","#6B6558","Ei vielä riittävästi näyttöä"
        c_range=""
        if chall.get("walk_forward_issue_start") and chall.get("walk_forward_issue_end"):
            c_range=f' ({str(chall["walk_forward_issue_start"])[:10]}–{str(chall["walk_forward_issue_end"])[:10]})'
        challenger_html=f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:16px;padding:6px 22px;margin-bottom:36px;">
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="font-size:15.5px;color:#3A382F;flex:1;">Challenger-malli</span><b style="font-family:'IBM Plex Mono',monospace;font-size:15.5px;">{html.escape(str(chall.get("name","—")))} {html.escape(str(chall.get("version","")))}</b></div>
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="font-size:15.5px;color:#3A382F;flex:1;">Walk-forward-otos</span><b style="font-family:'IBM Plex Mono',monospace;font-size:15.5px;">{c_n if c_n is not None else "—"} tuntia{html.escape(c_range)}</b></div>
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid rgba(28,27,23,0.06);"><span style="font-size:15.5px;color:#3A382F;flex:1;">MAE Champion / Challenger</span><b style="font-family:'IBM Plex Mono',monospace;font-size:15.5px;">{_fmt_fi(c_champ_mae,2)} / {_fmt_fi(c_chall_mae,2)} EUR/MWh</b></div>
      <div style="display:flex;align-items:center;gap:12px;padding:15px 0;{'border-bottom:1px solid rgba(28,27,23,0.06);' if c_thin else ''}"><span style="font-size:15.5px;color:#3A382F;flex:1;">Tila</span><span style="display:inline-flex;align-items:center;gap:6px;background:{v_bg};color:{v_fg};padding:5px 11px;border-radius:999px;font-size:14px;font-weight:700;">{html.escape(v_text)}</span></div>
      {f'<div style="padding:6px 0 15px;font-size:13.5px;color:#8A8577;">Otos on vielä pieni ({c_n} tuntia) — tulos ei ole tilastollisesti luotettava. Lukua tarkennetaan sitä mukaa kun uutta pisteytettyä dataa kertyy.</div>' if c_thin else ""}
    </div>'''
    else:
        challenger_html='''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:16px;padding:20px 22px;margin-bottom:36px;font-size:15px;color:#6B6558;">
      Ei koulutettua Challenger-mallia rekisteröitynä.
    </div>'''

    dg=p["days"][0].get("diagnostics",{}) if p.get("days") else {}
    factor_specs=[("Kulutus","consumption_forecast","MW"),("Tuuli","wind_forecast","MW"),("Aurinko","solar_forecast","MW"),("Residual load","residual_load","MW"),("Lämpötila","temperature","°C")]
    factors=[]
    for title,key,unit in factor_specs:
        _,v,u=_factor_value(dg,key,unit)
        factors.append(f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:14px;padding:14px;">
        <div style="font-size:13.5px;color:#8A8577;margin-bottom:6px;">{html.escape(title)}</div><div style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:19px;">{v} <span style="font-size:13px;font-weight:500;color:#8A8577;">{html.escape(u)}</span></div>
      </div>''')
    factor_html=f'<div class="factor-grid" style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:36px;">{"".join(factors)}</div>'

    labels={"fresh":"Tuore","aging":"Ikääntyvä","stale":"Vanhentunut","unknown":"Ei tietoa"}
    source_colors={"fresh":"#0B6E63","aging":"#D98A3D","stale":"#B03A2E","unknown":"#8A8577"}
    source_text={"fresh":"#0B4F49","aging":"#8A4B12","stale":"#8C2E22","unknown":"#6B6558"}
    sources=[]
    for x in p.get("freshness",{}).get("sources",[]):
        st=x.get("state","unknown")
        sources.append(f'''<div style="background:#FFFFFF;border:1px solid rgba(28,27,23,0.09);border-radius:14px;padding:14px;">
        <div style="font-size:15px;font-weight:600;margin-bottom:6px;">{html.escape(x.get("source",""))}</div>
        <div style="display:flex;align-items:center;gap:6px;font-size:13.5px;color:{source_text.get(st,"#6B6558")};"><span style="width:6px;height:6px;border-radius:50%;background:{source_colors.get(st,"#8A8577")};"></span>{labels.get(st,"Ei tietoa")}</div>
      </div>''')
    source_html=f'<div class="source-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px;">{"".join(sources)}</div>'

    return f'''{_page_head("Sähköennuste — Diagnostiikka")}
<style>{_SHARED_STYLE}
  @media (max-width:760px){{
    .factor-grid{{grid-template-columns:1fr 1fr !important;}}
    .quality-grid{{grid-template-columns:1fr 1fr !important;}}
    .readiness-grid{{grid-template-columns:1fr !important;}}
    .source-grid{{grid-template-columns:1fr 1fr !important;}}
  }}
</style></head><body>
<div style="width:100%;min-height:100vh;box-sizing:border-box;font-family:'IBM Plex Sans',sans-serif;color:#1C1B17;">
  <div style="width:100%;background:#1C1B17;color:#F7F4EC;box-sizing:border-box;padding:18px 40px;display:flex;align-items:center;justify-content:space-between;gap:24px;">
    <div style="display:flex;align-items:center;gap:14px;">
      <span style="width:40px;height:40px;border-radius:10px;background:rgba(247,244,236,0.10);display:flex;align-items:center;justify-content:center;flex:0 0 auto;">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#F7F4EC" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13.2 2 5 13h6l-.8 9L19 10h-6.2L13.2 2Z"></path></svg>
      </span>
      <div>
        <div style="font-family:'Fraunces',serif;font-weight:700;font-size:23px;letter-spacing:-0.01em;line-height:1.1;">Sähköennuste</div>
        <div style="font-size:14px;opacity:0.65;margin-top:2px;">Diagnostiikka &amp; mallin seuranta</div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:20px;">
      <div style="text-align:right;font-size:13px;opacity:0.65;line-height:1.4;">
        <div>Ajo</div>
        <div style="font-family:'IBM Plex Mono',monospace;">{html.escape(p["forecast_run_id"][:8])}</div>
      </div>
      <div style="display:flex;gap:3px;background:rgba(247,244,236,0.10);padding:4px;border-radius:999px;">
        <a href="index.html" style="padding:9px 17px;border-radius:999px;font-size:15px;font-weight:600;color:rgba(247,244,236,0.72);">Kuluttaja</a>
        <span style="padding:9px 17px;border-radius:999px;font-size:15px;font-weight:700;background:#F7F4EC;color:#1C1B17;">Diagnostiikka</span>
      </div>
    </div>
  </div>

  <div style="max-width:1040px;margin:0 auto;padding:36px 24px 72px;">
    <a href="index.html" style="display:inline-flex;align-items:center;gap:6px;font-size:15px;font-weight:600;color:#6B6558;margin-bottom:18px;">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 18l-6-6 6-6"></path></svg>
      Takaisin kuluttajanäkymään
    </a>

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">Ennusteen laatu</div>
    <h1 style="font-family:'Fraunces',serif;font-weight:600;font-size:27px;margin:0 0 18px;">Mallin tarkkuus</h1>
    {quality_kpis}
    {quality_table}
    {readiness_html}

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">Mallin tila</div>
    <h2 style="font-family:'Fraunces',serif;font-weight:600;font-size:22px;margin:0 0 14px;">Champion &amp; Challenger</h2>
    {model_html}
    {challenger_html}

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">Ennusteen taustatekijät</div>
    <h2 style="font-family:'Fraunces',serif;font-weight:600;font-size:22px;margin:0 0 14px;">Mittarit juuri nyt</h2>
    {factor_html}

    <div style="font-size:13px;letter-spacing:0.06em;text-transform:uppercase;color:#8A8577;font-weight:700;margin-bottom:7px;">Tietolähteiden tuoreus</div>
    <h2 style="font-family:'Fraunces',serif;font-weight:600;font-size:22px;margin:0 0 14px;">Syötteet</h2>
    {source_html}

    <div style="text-align:center;color:#8A8577;font-size:13.5px;padding:22px 0 4px;">
      Forecast run: {html.escape(p["forecast_run_id"])} · Electricity Forecaster v1.4.1 ·
      <a href="index.html" style="font-weight:600;">Kuluttajanäkymä →</a>
    </div>
  </div>
</div>
</body></html>'''
