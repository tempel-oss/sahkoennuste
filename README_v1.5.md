# Sähköennuste v1.5 — Historical Learning Dataset

Tämä on v1.4.2:n rinnalle tarkoitettu **historiallisen oppimisaineiston putki**.
Se ei muuta nykyistä tuotantoennustetta eikä ota ML-mallia vielä käyttöön.

## Tavoite

Rakentaa tuntitasoinen, uudelleen tuotettava aineisto, jolla voidaan:

1. kouluttaa ensimmäinen residual-ML-challenger
2. tehdä walk-forward-backtest
3. verrata ML-mallia v1.4.2-baselineen
4. havaita data leakage ennen mallikoulutusta

## Mukana olevat Fingrid-aineistot

- 124 — Suomen sähkönkulutus, toteuma
- 74 — Suomen sähköntuotanto, toteuma
- 165 — kulutusennuste, kerran päivässä
- 242 — tuotantoennuste / alustava päivän ennuste
- 75 — tuulivoiman tuotanto
- 246 — tuulivoimaennuste, kerran päivässä
- 268 — tuulivoimaennusteen käyttämä kapasiteetti
- 24 — SE1 -> FI day-ahead siirtokapasiteetti
- 26 — FI -> SE1 day-ahead siirtokapasiteetti
- 115 — FI -> EE day-ahead siirtokapasiteetti

Hintalähde on ENTSO-E A44, FI bidding zone. Jos ENTSO-E on tilapäisesti
poissa käytöstä, raakadata voidaan tuoda myöhemmin CSV:nä; datasetin
rakennus ei hävitä jo ladattuja Fingrid-aineistoja.

## Asennus nykyiseen v1.4.2-projektiin

Pura paketti projektin juureen.

PowerShell:

```powershell
cd C:\polku\sahkoennuste
.\.venv\Scripts\Activate.ps1
pip install -r requirements-v1.5.txt
Copy-Item .env.example .env -ErrorAction SilentlyContinue
```

Älä korvaa nykyistä `.env`-tiedostoa, jos siinä ovat jo avaimet.
Varmista että siinä ovat:

```text
FINGRID_API_KEY=...
ENTSOE_TOKEN=...
```

## Ensimmäinen ajo

Suosittelen ensin lyhyttä testiä:

```powershell
python run_v1_5_historical.py --start 2026-08-01 --end 2026-09-01
```

Jos se toimii:

```powershell
python run_v1_5_historical.py --start 2022-01-01 --end 2026-09-01
```

Fingrid rajoittaa API-kutsuja ja edellyttää vähintään noin kahden sekunnin
väliä kyselyille. Moduuli huomioi tämän automaattisesti.

## Tulokset

```text
data/
  raw/
    fingrid_*.parquet
    entsoe_fi_day_ahead_price.parquet
  processed/
    historical_features_hourly.parquet
    historical_features_hourly.csv
  reports/
    build_summary.json
    coverage.csv
    missing_hours.csv
    leakage_guard.txt
```

## Data leakage -periaate

Seuraavia saman hetken toteumia EI käytetä mallin syötteinä:

- target price
- toteutunut kulutus
- toteutunut tuotanto
- toteutunut tuulituotanto
- ennustevirheet

Ne ovat arviointi-/target-muuttujia. Mallille käytetään ennustehetkellä
saatavilla olleita day-ahead-ennusteita sekä turvallisia lag-muuttujia.

## Seuraava vaihe (v1.5.1)

Kun aineisto on ladattu ja coverage-raportti on kunnossa:

- lisätään v1.4.2:n historiallinen baseline-ennuste joka tunnille
- target = toteutunut hinta - v1.4.2 baseline
- koulutetaan ensimmäinen residual-challenger
- tehdään 12 kk walk-forward
- raportoidaan MAE, RMSE, bias, skill score ja hintapiikkien suorituskyky

## Huomio Fingrid-adapterista

Koska nykyisen v1.4.2-projektin toimivaa Fingrid-adapteria ei ollut tässä
keskustelussa tiedostona saatavilla, v1.5 sisältää puolustavan itsenäisen
adapterin. Jos nykyisessä projektissasi oleva Fingrid-kutsu käyttää eri
gateway-polkuja, helpoin ja turvallisin integraatio on korvata vain
`historical_v15/fingrid.py`-tiedoston `fetch_dataset()` nykyisellä
toimivalla hakumekanismilla. Muu v1.5-putki ei muutu.
