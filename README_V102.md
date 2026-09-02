
# Electricity Forecaster v1.0.2

Korjaukset:
- Fingrid HTTP 429 / 5xx: automaattinen retry + backoff (enintään 6 yritystä).
- `INPUT_ERROR_SCORING`: poistettu SQLite-virheen aiheuttanut `f.valid_time`
  korreloidun ORDER BY:n sisältä; käytetään Fingrid-sarjojen täsmällistä timestamp-joinia.
- Tuotantorunner palauttaa virhekoodin, jos data quality, ennuste tai julkaisu epäonnistuu.
- Vanhaa ennustetta ei julkaista uutena epäonnistuneen ajon jälkeen.
- `30_AJA_JA_JULKAISE.bat` on non-interactive ja soveltuu Task Scheduleriin.
- `29_JULKAISE_GITHUBIIN.bat` ei enää ilmoita virheellisesti onnistumisesta Git-virheen jälkeen.
- stdout/lokituksen sulkeminen korjattu.

Päivitys:
1. Pura v1.0.2 uuteen kansioon.
2. Kopioi `.env` ja `data\electricity_forecaster.sqlite3` toimivasta v1.0.1-kansiosta
   (tai käytä `00_PAIVITA_V09STA.bat` v0.9-kansiosta).
3. GitHub-yhteys voidaan siirtää helpoimmin käyttämällä samaa repositorya ja
   alustamalla Git tässä kansiossa, tai jatkaa nykyisessä v1.0.1-kansiossa
   korvaamalla v1.0.2:n muuttuneet tiedostot.
4. Testaa ensin `21_AJA_KAIKKI.bat`.
5. Vasta kun YHTEENVETO sisältää DATA_QUALITY, PRICE_FORECAST ja PUBLISH_OUTPUT = ok,
   käytä `30_AJA_JA_JULKAISE.bat`.
