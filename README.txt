Korjaus: vain _fold_blocks-funktion return-lause muuttui. NumPy jakaa rivipaikat, pandas iloc palauttaa DataFrame-kopiot. Muu skripti tarkistettu identtiseksi alkuperaisen kanssa.

Korvaa projektisi train_residual_challenger_v1.py paketin samannimisella tiedostolla.
Aja projektin juuressa:
.\.venv\Scripts\python.exe .\train_residual_challenger_v1.py

Testattu 2026-09-17: NumPy 2.5.2, pandas 3.0.5, scikit-learn 1.9.1.
PASS: py_compile-syntaksitarkistus.
PASS: DataFrame-tyyppi, sarakkeet, dtypet, aikajarjestys, epatasaiset jaot, ylimaaraiset foldit, kopioiden riippumattomuus ja alkuperaiset virhetarkistukset.
PASS: synteettinen komentoriviajo, 2016 rivia, 21 ennusteajoa, 5 foldia, 1056 testiennustetta.
PASS: purge-saannon mukaiset koulutusrivimaarat, ennusteiden residual-kaava, JSON/HTML/CSV-raportit, metadata, mallin tallennus ja uudelleenlataus.
Synteettinen aineisto sisalsi vakion +8 EUR/MWh residualin. Testin MAE 8 -> 0 on ohjelman toimivuustesti, ei osoitus tuotantoennusteiden tarkkuudesta.
Testi kaytti --no-rebuild-matrix-valintaa ja erillista synteettista CSV:ta. Tuotannon matriisin uudelleenrakennusta ei testattu.

Mukana test_synthetic.py testin toistamista varten.
