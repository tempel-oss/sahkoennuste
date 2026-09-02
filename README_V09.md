
# Electricity Forecaster v0.9 — Production Runner & Mobile Output

v0.9 perustuu toimivaan v0.8.3-versioon.

## Uutta
- `21_AJA_KAIKKI.bat`: koko päivittäinen ketju yhdellä ajolla
- lokit `logs\production_YYYYMMDD_HHMMSS.log`
- `output\latest_forecast.json`
- mobiiliystävällinen `output\latest_forecast.html` ja `output\index.html`
- `24_ASENNA_PAIVITTAINEN_AJO.bat`: Windows Task Scheduler
- `23_KAYNNISTA_PUHELINNAKYMA.bat`: valinnainen paikallinen web-palvelin samassa Wi-Fi-verkossa
- ennusteen muutos edelliseen ajoon HTML-raportissa
- v0.8-diagnostiikka mukana raportissa

## Päivitys v0.8.3:sta
1. Pura v0.9 uuteen kansioon.
2. Aja `00_PAIVITA_V08_3STA.bat` ja anna v0.8.3-kansion polku.
3. Aja `00_ASENNA.bat`.
4. Testaa `21_AJA_KAIKKI.bat`.
5. Avaa `22_AVAA_VIIMEISIN_ENNUSTE.bat`.
6. Kun manuaalinen ajo toimii, aja `24_ASENNA_PAIVITTAINEN_AJO.bat`.

## Puhelinnäkymä lähiverkossa
Aja `23_KAYNNISTA_PUHELINNAKYMA.bat`.
Ikkuna näyttää osoitteen, esimerkiksi:
`http://192.168.1.25:8765/`

Avaa osoite Android-puhelimen Chromessa, kun puhelin ja tietokone ovat samassa Wi-Fi-verkossa.
Jos Windowsin palomuuri kysyy lupaa Pythonille, salli pääsy vain yksityisissä verkoissa.

Tämä lähiverkkopalvelu EI julkaise sivua internetiin. Se toimii vain niin kauan kuin BAT-ikkuna on auki ja tietokone on tavoitettavissa.

## Android-pikakuvake
Kun sivu on auki Chromessa:
- valitse Chromen valikko
- "Lisää aloitusnäyttöön" / "Add to Home screen"

Varsinainen pilvipohjainen PWA voidaan tehdä myöhemmässä versiossa.

## Huomio
v0.9 käyttää edelleen `fundamental_baseline`-ennustetta. Se ei vielä ole koulutettu ML/Champion-malli.
