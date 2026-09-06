
# Electricity Forecaster v1.4 — ML Readiness + Forecast Quality

Uutta:
- MAE, bias, RMSE, P10–P90-peitto ja skill vs baseline.
- D+2...D+12 horizon-kohtainen ennustelaatu.
- `data/ml/training_matrix.csv` rakentuu vain issue-time-tiedoista + targetista.
- `data/ml/walk_forward_baseline.json` kronologisena validointirunkona.
- ML-valmiusportit: 1000 tuntia/20 ajoa koulutukseen, 1500 tuntia/30 ajoa walk-forwardiin.
- `34_NAYTA_ENNUSTELAATU.bat`
- `35_RAKENNA_ML_AINEISTO.bat`
- Pilvi- ja Windows-tuotantoajo rakentavat ML-aineiston automaattisesti.
- Päivitysaika muunnetaan selaimessa `Europe/Helsinki`-aikaan; tämä korjaa pilven UTC-näytön.

v1.4 ei vielä kouluta tai promotoi ML-Challengeria. Se rakentaa ensin auditoitavan
arviointi- ja koulutuspohjan.
