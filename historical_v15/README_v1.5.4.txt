Sähköennuste v1.5.4 — ENTSO-E A03 variable-block hotfix

Korvaa projektissa:
  historical_v15\entsoe.py

Miksi korjaus tarvitaan:
ENTSO-E A44 -hintadatan CurveType A03 ei julkaise jokaista 15 minuutin
pistettä. Se julkaisee vain kohdat, joissa hintablokki muuttuu.
Edellinen hinta jatkuu seuraavaan muutospisteeseen asti.

Vanha parseri tulkitsi julkaisemattomat positiot puuttuvaksi dataksi.
v1.5.4 laajentaa A03-blokit takaisin täydelle 15 min / 60 min aikajanalle.

Testaa uudelleen:
.\.venv\Scripts\python.exe run_v1_5_historical.py --start 2026-08-01 --end 2026-09-01

Odotus elokuulle 2026:
- ENTSO-E raw rows noin 2 976 (31*24*4)
- hourly rows 744
- price_rows 744
- price_lag_24h missing 24
- price_lag_48h missing 48
- price_lag_168h missing 168
