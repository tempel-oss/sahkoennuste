Sähköennuste v1.5.8.1 — read-only NumPy hotfix

Korvaa projektissa:
  historical_v15\asof.py

Virheen syy:
pandas palautti price.reindex(...).to_numpy()-kutsusta joissakin versioissa
read-only NumPy-taulukon. Koodi yritti tämän jälkeen kirjoittaa siihen NaN-arvoja:

  vals[~safe] = np.nan

v1.5.8.1 tekee taulukosta eksplisiittisen kirjoitettavan kopion ennen muutosta.

Aja korjauksen jälkeen:
.\.venv\Scripts\python.exe build_horizon_v1_5_8.py
