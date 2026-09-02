from _bootstrap import *
from electricity_forecaster.forecast_engine import latest_daily_forecast, eur_mwh_to_ct_kwh_vat
meta,rows=latest_daily_forecast()
if not meta:
    print('Ennusteita ei ole viela. Aja 14_TEE_ENNUSTE.bat')
    raise SystemExit(1)
print('=== VIIMEISIN D+2...D+12 HINTAENNUSTE v0.7 ===')
print('Ajo:',meta['issue_time'])
print('Malli:',meta['model_name'],meta['model_version'])
print('HUOM: tama on fundamentaalinen baseline, EI viela koulutettu ML/Champion-malli.')
print()
print(f"{'Paiva':10} {'D+':>3} {'P10':>8} {'P50':>8} {'P90':>8} {'halvin 3h':>11} {'kallein 3h':>12} {'riski':>10}")
print(' '*15+'snt/kWh sis. ALV 25,5 %')
for r in rows:
    print(f"{r['target_date']:10} {r['horizon']:>3} {eur_mwh_to_ct_kwh_vat(r['p10']):8.2f} {eur_mwh_to_ct_kwh_vat(r['p50']):8.2f} {eur_mwh_to_ct_kwh_vat(r['p90']):8.2f} {r['cheap']:>11} {r['expensive']:>12} {r['risk']:>10}")
print('\nBaseline = yksinkertainen julkaistun day-ahead-hinnan tuntiprofiili ilman tulevien fundamenttien korjausta.')
