SÄHKÖENNUSTE v1.5.9 — 06:15 / 16:15 SNAPSHOT-ARKISTO

Paketissa:
  archive_forecast_snapshot.py
  36_AJA_JA_ARKISTOI.bat

Kopioi molemmat projektin juureen:
  C:\Users\Teemu\ChatGPT\v1.4.1\electricity_forecaster

Wrapper ajaa ensin:
  30_AJA_JA_JULKAISE.bat

Vain jos tuotantoajo päättyy exit-koodiin 0, ennuste arkistoidaan.
Näin Scheduled Taskin LastTaskResult ei peitä mahdollista tuotantovirhettä.

Arkisto:
  data\forecast_archive\YYYY\MM\DD\
    forecast_YYYYMMDD_0615_morning.json
    forecast_YYYYMMDD_0615_morning.html
    forecast_YYYYMMDD_0615_morning.meta.json
    forecast_YYYYMMDD_1615_afternoon.json
    ...

Indeksi:
  data\forecast_archive\index.csv
