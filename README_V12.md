
# Electricity Forecaster v1.2 — Visual Dashboard

Tässä versiossa ennustelogiiikka pysyy v1.1:n mukaisena ja käyttöliittymä uudistuu.

Uutta:
- moderni sininen sovellusotsake
- visuaaliset datalähteiden tuoreuskortit
- isot D0/D+1-hintakortit
- desktop-taulukko ja mobiilin vaakasuuntaiset D+2...D+12-kortit
- P50 + P10–P90 SVG-hintakaavio ilman ulkoisia kirjastoja
- automaattinen "Mitä muuttui" -yhteenveto
- visuaalinen Mallin tila -kortti
- fundamenttien minikortit
- service worker -välimuisti päivitetty versioon v12

Päivitys:
1. Pura v1.2 uuteen kansioon.
2. Kopioi `.env` ja koko `data`-kansio v1.1:stä.
3. Aja `21_AJA_KAIKKI.bat`.
4. Tarkista `output\latest_forecast.html`.
5. Yhdistä/päivitä sama GitHub-repository ja julkaise `30_AJA_JA_JULKAISE.bat`:lla.
