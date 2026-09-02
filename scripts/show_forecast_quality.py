from _bootstrap import *
from electricity_forecaster.db import connect,init_db
init_db()
with connect() as c:
    rows=c.execute("""SELECT horizon_days,COUNT(*),AVG(abs_error_eur_mwh),AVG(baseline_abs_error_eur_mwh),AVG(inside_p10_p90)
                      FROM price_forecast_scores GROUP BY horizon_days ORDER BY horizon_days""").fetchall()
print('=== ENNUSTELAATU v0.7 ===')
if not rows:
    print('Ei viela pisteytettyja hintatoteumia. Tama on normaalia ensimmaisina paivina.')
else:
    print(f"{'D+':>3} {'N':>5} {'MAE malli':>12} {'MAE baseline':>14} {'P10-P90 osuus':>15}")
    for h,n,mae,bmae,cov in rows:
        print(f'{h:>3} {n:>5} {mae:12.2f} {bmae:14.2f} {100*cov:14.1f}%')
