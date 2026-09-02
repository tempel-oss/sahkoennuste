from __future__ import annotations
import json, math, re, statistics, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .config import ROOT, RAW_DIR

LOCATIONS = json.loads((ROOT/'config'/'weather_locations.json').read_text(encoding='utf-8'))['locations']

UA='ElectricityForecaster/0.5 (+personal research)'

def _get(url: str, timeout=45) -> tuple[bytes, dict]:
    req=urllib.request.Request(url, headers={'User-Agent':UA,'Accept':'application/json, application/xml, text/xml;q=0.9, */*;q=0.5'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)

def _archive(provider: str, run_id: str, name: str, body: bytes, ext: str):
    p=RAW_DIR/provider/run_id; p.mkdir(parents=True, exist_ok=True)
    (p/f'{name}.{ext}').write_bytes(body)


def fetch_ecmwf_deterministic(run_id: str, forecast_days=15):
    rows=[]
    hourly='temperature_2m,wind_speed_100m,cloud_cover,shortwave_radiation,precipitation'
    for loc in LOCATIONS:
        q=urllib.parse.urlencode({
            'latitude':loc['lat'],'longitude':loc['lon'],'hourly':hourly,
            'models':'ecmwf_ifs','forecast_days':forecast_days,'timezone':'UTC','wind_speed_unit':'ms'
        })
        url='https://api.open-meteo.com/v1/forecast?'+q
        body,_=_get(url); _archive('ecmwf_openmeteo',run_id,loc['name'].lower(),body,'json')
        data=json.loads(body)
        h=data.get('hourly',{}); times=h.get('time',[])
        for i,t in enumerate(times):
            for key,metric,unit in [
                ('temperature_2m','temperature_2m_c','C'),('wind_speed_100m','wind_speed_100m_ms','m/s'),
                ('cloud_cover','cloud_cover_pct','%'),('shortwave_radiation','shortwave_radiation_wm2','W/m2'),
                ('precipitation','precipitation_mm','mm')]:
                vals=h.get(key,[])
                if i < len(vals) and vals[i] is not None:
                    rows.append((loc['name'],t,metric,float(vals[i]),unit,'ecmwf_ifs_openmeteo'))
    return rows


def fetch_ecmwf_ensemble(run_id: str, forecast_days=15):
    # Open-Meteo model ids have changed occasionally. Try known/current candidates safely.
    candidates=['ecmwf_ifs025','ecmwf_ifs025_ensemble','ecmwf_ifs']
    chosen=None; all_rows=[]; errors=[]
    # keep ensemble load moderate: representative north/west/south points
    names={'Helsinki','Vaasa','Oulu'}
    locs=[x for x in LOCATIONS if x['name'] in names]
    for model in candidates:
        try:
            temp=[]
            for loc in locs:
                q=urllib.parse.urlencode({'latitude':loc['lat'],'longitude':loc['lon'],
                    'hourly':'temperature_2m,wind_speed_100m','models':model,
                    'forecast_days':forecast_days,'timezone':'UTC','wind_speed_unit':'ms'})
                body,_=_get('https://ensemble-api.open-meteo.com/v1/ensemble?'+q,timeout=60)
                d=json.loads(body); h=d.get('hourly',{}); times=h.get('time',[])
                if not times: raise RuntimeError('no hourly times')
                # Keys are variable_memberXX; summarize all numeric member series by timestamp.
                for base,metric,unit in [('temperature_2m','temperature_2m_c','C'),('wind_speed_100m','wind_speed_100m_ms','m/s')]:
                    keys=[k for k in h if k==base or k.startswith(base+'_member')]
                    if len(keys)<2: raise RuntimeError(f'ensemble members missing for {base}; keys={keys[:5]}')
                    for i,t in enumerate(times):
                        vals=[]
                        for k in keys:
                            a=h.get(k,[])
                            if i<len(a) and a[i] is not None: vals.append(float(a[i]))
                        if vals:
                            vals.sort()
                            def qtile(p):
                                j=(len(vals)-1)*p; lo=int(math.floor(j)); hi=int(math.ceil(j))
                                return vals[lo] if lo==hi else vals[lo]*(hi-j)+vals[hi]*(j-lo)
                            temp.extend([(loc['name'],t,metric+'_p10',qtile(.10),unit,model),
                                         (loc['name'],t,metric+'_p50',qtile(.50),unit,model),
                                         (loc['name'],t,metric+'_p90',qtile(.90),unit,model),
                                         (loc['name'],t,metric+'_spread80',qtile(.90)-qtile(.10),unit,model)])
                _archive('ecmwf_ensemble_openmeteo',run_id,loc['name'].lower()+'_'+model,body,'json')
            all_rows=temp; chosen=model; break
        except Exception as e:
            errors.append(f'{model}: {e}')
    return all_rows, chosen, errors


def fetch_fmi_harmonie(run_id: str):
    rows=[]; errors=[]
    # FMI short-range point forecasts. Parsing timevaluepair avoids external packages.
    for loc in LOCATIONS:
        try:
            params='temperature,windspeedms,totalcloudcover,radiationglobal'
            q=urllib.parse.urlencode({'service':'WFS','version':'2.0.0','request':'getFeature',
                'storedquery_id':'fmi::forecast::harmonie::surface::point::timevaluepair',
                'place':loc['name'],'parameters':params})
            body,_=_get('https://opendata.fmi.fi/wfs?'+q)
            _archive('fmi_harmonie',run_id,loc['name'].lower(),body,'xml')
            root=ET.fromstring(body)
            # Generic parser: each MeasurementTimeseries has id/observedProperty-ish text and Time/Value pairs.
            for ts in root.iter():
                if not ts.tag.endswith('MeasurementTimeseries'): continue
                ident=' '.join(str(v) for v in ts.attrib.values())
                text=' '.join((x.text or '') for x in ts.iter() if x.text)
                hay=(ident+' '+text[:500]).lower()
                if 'temperature' in hay: metric,unit='temperature_2m_c','C'
                elif 'windspeed' in hay or 'wind speed' in hay: metric,unit='wind_speed_10m_ms','m/s'
                elif 'cloud' in hay: metric,unit='cloud_cover_pct','%'
                elif 'radiation' in hay: metric,unit='shortwave_radiation_wm2','W/m2'
                else: continue
                times=[]; vals=[]
                for x in ts.iter():
                    if x.tag.endswith('time') and x.text: times.append(x.text.strip())
                    elif x.tag.endswith('value') and x.text:
                        try: vals.append(float(x.text.strip()))
                        except: pass
                for t,v in zip(times,vals): rows.append((loc['name'],t,metric,v,unit,'fmi_harmonie'))
        except Exception as e: errors.append(f"{loc['name']}: {e}")
    return rows, errors
