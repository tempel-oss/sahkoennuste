# Residual Challenger v1

Ensimmäinen oppiva Challenger-malli sähköennusteeseen.

## Mitä se tekee

- käyttää nykyisen tuotanto-Championin pisteytettyjä tuntiennusteita
- target = `actual_eur_mwh - p50_eur_mwh`
- Challenger = `Champion P50 + ML:n ennustama residual`
- malli: `HistGradientBoostingRegressor`
- arviointi: kronologinen, purged walk-forward
- EI muuta tuotanto-Championia
- EI muuta ennustetta tai julkaisua
- tallentaa mallin ja raportit vain `data/ml/challenger_residual_hgb_v1/`

Purged-sääntö estää tulevan toteutuneen hinnan vuotamisen:
train-rivin `issue_time` ja `target_time` täytyy olla ennen testijakson ensimmäistä issue-hetkeä.

## Miksi 879k historiallisen datasetin rivejä ei käytetä vielä residual-targettiin

`data/processed/v1_5_8/horizon_asof_dual_d2_d12.parquet` on leakage-safe ja erittäin hyödyllinen.
Se ei kuitenkaan sisällä tuotannossa käytetyn `fundamental_baseline 0.7.1` -mallin historiallista P50-arvoa
jokaiselle issue-hetkelle. Siksi siitä ei voi laskea täsmällistä targetia:

`actual - production_champion_p50`

Ensimmäinen residual-Challenger koulutetaan siksi tuotannon omasta pisteytetystä training matrixista.
Historiallinen 879k aineisto säilyy seuraavaa vaihetta varten.

## Asennus

Riippuvuudet ovat nyt `requirements-v1.5.txt`/`requirements-challenger-v1.txt`:ssa lattia+kattoversioina
(ks. `VERSIONING.md`), ei enää suoraan tässä READMEssä. Helpoin tapa on ajaa juuresta:

```
37_PAIVITA_ML_RIIPPUVUUDET.bat
```

joka asentaa/päivittää molemmat requirements-tiedostot `.venv`:iin ja kirjoittaa heti perään
`requirements-v1.5.lock.txt`:n asennetuista *tarkoista* versioista (`scripts/freeze_requirements.py`).
Committaa päivitetty lock-tiedosto, jos versiot muuttuivat — se on ainoa tapa toistaa täsmälleen
sama ympäristö toisella koneella, koska requirements-tiedostojen `>=`/`<`-rajat sallivat eri
patch-versioiden resolvoitumisen eri ajankohtina.

Manuaalisesti sama komentoriviltä:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-v1.5.txt -r requirements-challenger-v1.txt
.\.venv\Scripts\python.exe scripts\freeze_requirements.py
```

## Ajo

Projektin juuressa:

```powershell
.\.venv\Scripts\python.exe .\train_residual_challenger_v1.py
```

Ajo rakentaa ensin nykyisen `data/ml/training_matrix.csv`-aineiston uudelleen tietokannasta.

## Tulokset

`data/ml/challenger_residual_hgb_v1/`

- `model.joblib`
- `metadata.json`
- `report.json`
- `report.html`
- `walk_forward_predictions.csv`

Avaa raportti:

```powershell
Start-Process .\data\ml\challenger_residual_hgb_v1\report.html
```
