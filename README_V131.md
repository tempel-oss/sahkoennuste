
# Electricity Forecaster v1.3.1

Aikavyöhykekorjaus:
- Dashboardin `Päivitetty`-aika muunnetaan UTC-ajasta `Europe/Helsinki`-aikaan.
- Kesäaika (UTC+3) ja talviaika (UTC+2) huomioidaan automaattisesti.
- Tietokantaan tallennettava issue_time säilyy UTC-aikana, mikä on oikea tapa
  sisäiseen laskentaan ja historiatietoon.
