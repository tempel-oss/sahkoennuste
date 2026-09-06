
# Electricity Forecaster v1.4.1

Muutokset:
- Dashboardiin Challenger-koulutusvalmiuden etenemispalkki.
- Dashboardiin walk-forward-valmiuden etenemispalkki.
- Palkit huomioivat sekä pisteytetyt tunnit että ennusteajojen määrän.
- Kellonaikakorjausta vahvistettu:
  - issue_time käsitellään UTC-aikana, jos offset puuttuu.
  - selain muuntaa ajan aina Europe/Helsinki-aikavyöhykkeeseen.
  - kesä- ja talviaika vaihtuvat automaattisesti.
  - dashboardissa näkyy lisäksi "Suomen aika".
- Service Worker cache päivitetty v1.4.1:een.
