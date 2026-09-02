
# Electricity Forecaster v1.1

Uutta:
- D0 ja D+1 julkaistut FI day-ahead -hinnat omana osionaan.
- Päiväkeskiarvo, min/max sekä halvin/kallein 3 h.
- D+2...D+12 P50:n muutos edelliseen onnistuneeseen ennusteajoon.
- Datalähteiden tuoreusindikaattori: Fingrid, Nord Pool, sää, ENTSO-E.
- Champion/Challenger-mallirekisteri ja koulutusvalmiuden mittari.
- `32_NAYTA_MALLITILA.bat`.

v1.1 ei vielä kouluta uutta ML-Challengeria. Baseline pysyy Championina kunnes
riittävä pisteytetty historia on kertynyt ja uusi malli läpäisee walk-forward-testin.
