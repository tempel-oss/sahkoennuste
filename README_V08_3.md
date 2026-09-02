
# v0.8.3

Korjaa v0.8.2:n `.env`-latauksen. v0.7.1:ssa oikea moduuli on
`electricity_forecaster.config.load_env_file`, ei `electricity_forecaster.env`.

v0.8.3 on rakennettu suoraan toimivan v0.7.1:n päälle ja säilyttää sen db.py:n,
config.py:n sekä ennustetaulujen todellisen skeeman.

Päivitys:
1. pura uuteen kansioon
2. aja 00_PAIVITA_VANHASTA.bat ja osoita nykyiseen v0.8.2/v0.8.1 kansioon
3. aja 00_ASENNA.bat
4. aja 20_TARKISTA_YHTEENSOPIVUUS.bat
5. aja 14_TEE_ENNUSTE.bat
6. aja 18_NAYTA_DIAGNOSTIIKKA.bat
