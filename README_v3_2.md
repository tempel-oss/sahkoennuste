# v3.2 cloud_validate hotfix

v3.1 pääsi kaikki varsinaiset lähdekoodimuutokset läpi, mutta
`cloud_validate.py`-korvaus käytti vielä regexiä, joka saattoi sotkea
sisennyksen.

v3.2 vaihtaa tämän yhden muutoksen rivipohjaiseksi:
- se etsii vanhan kahden rivin D+2...D+12-validoinnin
- säilyttää funktion alkuperäisen sisennystason
- korvaa vain nuo kaksi riviä uudella morning/afternoon-validoinnilla

Aiempi epäonnistunut ajo palautti alkuperäiset tiedostot automaattisesti.

Aja projektin juuressa:

```powershell
.\.venv\Scripts\python.exe .\apply_issue_slot_display_patch_v3_2.py
```
