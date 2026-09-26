# v3.1 whitespace hotfix

v3:n `_published_prices`-hakumallin lopussa oli `\s*`. Se nieli myös
rivinvaihdon ja seuraavan rivin sisennyksen, jolloin `raw=con.execute(...)`
liimautui `wanted=...`-rivin jatkoksi.

v3.1 vaihtaa tämän kohtaan `[ \t]*`, joka sallii vain rivin lopun välilyönnit
ja tabit mutta ei syö rivinvaihtoa.

Aiempi epäonnistunut ajo palautti alkuperäiset tiedostot automaattisesti.

Aja:

```powershell
.\.venv\Scripts\python.exe .\apply_issue_slot_display_patch_v3_1.py
```
