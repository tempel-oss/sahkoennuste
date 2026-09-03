
# Electricity Forecaster v1.3 — Cloud Runner

Tavoite: ennuste päivittyy ilman että oma Windows-tietokone on päällä.

## GitHub Secrets
Repository -> Settings -> Secrets and variables -> Actions -> New repository secret

Lisää:
- FINGRID_API_KEY
- ENTSOE_API_TOKEN

Älä koskaan lisää `.env`-tiedostoa GitHubiin.

## Pilviajo
Workflow: `.github/workflows/cloud_forecast.yml`

Se:
1. käynnistyy päivittäin klo 16:15 Europe/Helsinki
2. palauttaa edellisen SQLite-tietokannan GitHub Actions cache -välimuistista
3. ajaa saman tuotantoketjun kuin Windows-versio
4. tallentaa päivitetyn SQLite-tietokannan uuteen cache-versioon
5. julkaisee `output`-kansion suoraan GitHub Pagesiin

GitHub cron käyttää UTC-aikaa. Workflowssa on 13:15 ja 14:15 UTC -ajot.
`cloud_gate.py` päästää läpi vain sen, joka vastaa Suomen klo 16:15 aikaa.

## Käyttöönotto
1. Päivitä v1.3 samaan `tempel-oss/sahkoennuste` repositoryyn.
2. Lisää GitHub Secrets.
3. Repository -> Settings -> Pages -> Source = GitHub Actions.
4. Actions -> Cloud Electricity Forecast -> Run workflow.
5. Tarkista että forecast-job ja Deploy to GitHub Pages onnistuvat.
6. Tarkista `https://tempel-oss.github.io/sahkoennuste/`.
7. Pidä Windows-ajastus vielä muutama päivä varalla.

## Huomio SQLite-historiasta
Ensimmäinen cloud-run voi aloittaa tyhjästä, jos Actions-cachessa ei ole tietokantaa.
Sen jälkeen historia säilyy ajosta toiseen cachen kautta. Windowsissa oleva vanha
historia ei katoa. Myöhemmässä ML-vaiheessa kannattaa siirtyä oikeaan pilvitietokantaan.

GitHub Pagesiin ei julkaista `.env`:iä, API-avaimia, SQLite-tietokantaa eikä raw-dataa.
