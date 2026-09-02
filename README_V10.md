
# Electricity Forecaster v1.0 — PWA + GitHub Pages

1. Pura v1.0 uuteen kansioon.
2. Aja `00_PAIVITA_V09STA.bat`.
3. Aja `00_ASENNA.bat`.
4. Aja `21_AJA_KAIKKI.bat`.
5. Aja `27_VALMISTELE_GITHUB_PAGES.bat`.
6. Luo GitHubissa uusi tyhjä repository, esimerkiksi `sahkoennuste`.
7. Aja `28_YHDISTA_GITHUB_REPOON.bat` ja syötä repositoryn HTTPS-osoite.
8. GitHubissa: Settings > Pages > Source = GitHub Actions.
9. GitHub Actions julkaisee `output`-kansion HTTPS-sivuksi.
10. Androidissa avaa Pages-osoite Chromessa ja valitse "Asenna sovellus" tai "Lisää aloitusnäyttöön".
11. Jatkossa `30_AJA_JA_JULKAISE.bat` tekee ennusteen ja julkaisee sen.
12. `31_ASENNA_PAIVITTAINEN_PILVIJULKAISU.bat` automatisoi tämän.

API-avaimia, `.env`-tiedostoa ja SQLite-tietokantaa ei julkaista GitHubiin.
