# Sähköennuste v1.5.7 — Dual Forecast Origins

Tämä versio muuttaa järjestelmän kahteen päivittäiseen ennustehetkeen:

- **06:15 Europe/Helsinki**
- **16:15 Europe/Helsinki**

Muutoksessa on kaksi erillistä osaa:

1. historiallisen ML-aineiston `issue_time`-rakenne tukee molempia ajoja
2. Windowsin nykyinen tuotantoajo voidaan klo 16:15 -tehtävän pohjalta
   kopioida myös klo 06:15 -ajoksi

## 1. Kopioi tiedostot nykyiseen projektiin

Projektin juuri on tällä hetkellä esimerkiksi:

```text
C:\Users\Teemu\ChatGPT\v1.4.1\electricity_forecaster
```

Paketista:

```text
historical_v15\asof.py
build_horizon_v1_5_7.py
archive_forecast_snapshot.py
find_forecast_tasks.ps1
setup_dual_daily_schedule.ps1
```

`historical_v15\asof.py` korvaa v1.5.6:n version.

## 2. Rakenna kaksiaikainen ML-aineisto

```powershell
.\.venv\Scripts\python.exe build_horizon_v1_5_7.py
```

Oletus on:

```text
06:15
16:15
D+2 ... D+12
Europe/Helsinki
```

Tulos:

```text
data\processed\v1_5_7\
  horizon_asof_dual_d2_d12.parquet
  dual_origin_feature_coverage.csv
  dual_origin_row_counts.csv
  dual_origin_manifest.json
```

Täysi CSV on suuri, joten sitä ei tehdä oletuksena. Tarvittaessa:

```powershell
.\.venv\Scripts\python.exe build_horizon_v1_5_7.py --write-csv
```

## 3. Mikä muuttuu ML-aineistossa?

Sama target-tunti saa kaksi erillistä forecast-origin-riviä.

Esimerkiksi:

```text
issue 06:15 -> target 3 vrk myöhemmin klo 18
issue 16:15 -> sama target 3 vrk myöhemmin klo 18
```

Niiden `horizon_hours` on eri ja issue-timeen ankkuroidut historiatiedot
lasketaan erikseen. Iltapäivän rivi saa siis käyttää päivän aikana
06:15:n jälkeen kertynyttä tietoa, mutta aamurivi ei.

Uudet kentät:

```text
issue_slot          morning / afternoon
issue_time_code     0615 / 1615
issue_hour_local
issue_minute_local
issue_hour_sin
issue_hour_cos
```

## 4. Tuotantoennusteen kaksi päivittäistä ajoa

Koska nykyisen Windows Scheduled Task -tehtävän tarkkaa nimeä ei ollut
paketissa tiedossa, sitä ei arvata.

Etsi ensin nykyinen tehtävä:

```powershell
.\find_forecast_tasks.ps1
```

Kun tuloksessa näkyy nykyisen klo 16:15 ennustetehtävän `TaskName`,
asenna kaksiajo esimerkiksi:

```powershell
.\setup_dual_daily_schedule.ps1 -ExistingTaskName "TEHTÄVÄN OIKEA NIMI"
```

Jos PowerShell ilmoittaa käyttöoikeusvirheestä, avaa PowerShell
järjestelmänvalvojana ja aja komento uudelleen.

Asennus:

- pitää nykyisen tehtävän klo **16:15**
- luo siitä saman tuotantoajon klo **06:15**
- lisää molempien ajojen jälkeen forecast-snapshotin arkistoinnin

## 5. Ennusteiden arkisto

Molempien ajojen jälkeen:

```text
output\latest_forecast.json
```

kopioidaan automaattisesti esimerkiksi:

```text
data\forecast_archive\2026\09\06\
  forecast_20260906_0615xx_morning.json
  forecast_20260906_0615xx_morning.meta.json
  forecast_20260906_1615xx_afternoon.json
  forecast_20260906_1615xx_afternoon.meta.json
```

Lisäksi:

```text
data\forecast_archive\index.csv
```

kerää kaikki issue-timet ja snapshotit.

Tämä on tärkeää, jotta myöhemmin voidaan mitata:

- aamun ennusteen MAE
- iltapäivän ennusteen MAE
- kuinka paljon 16:15 ennuste parani 06:15 ennusteesta
- D+2 ... D+12 suorituskyky erikseen
- aamun ja iltapäivän bias / RMSE / skill / spike performance

## 6. Huomio

Tämä paketti ei muuta varsinaisen v1.4.1-ennustemoottorin laskentakaavaa.
Se ajaa saman tuotantomoottorin kahdesti päivässä ja säilyttää molemmat
ennusteet erillisinä forecast origineina.

Seuraava ML-vaihe voi käyttää `issue_slot`-kenttää ja testata myöhemmin,
onko yksi yhteinen malli parempi vai erilliset morning/afternoon-mallit.
