# Electricity Forecaster v1.4.1 — aamu/iltapäivä-tyyppikorjaus

Tämä paketti on tehty julkisen GitHub-repon `tempel-oss/sahkoennuste`
nykyisen `main`-haaran rakenteen perusteella. Koko projektin ZIPiä ei tarvitse
lähettää ChatGPT:lle.

## Tavoitelogiikka

**06:15 morning**
- D0 = `day_ahead` / **Julkaistu**
- D+1...D+11 = `forecast` / **Ennuste**
- D-1 ei näy

**16:15 afternoon**
- D0 = `day_ahead` / **Julkaistu**
- D+1 = `day_ahead` / **Julkaistu**
- D+2...D+12 = `forecast` / **Ennuste**

JSON:
- top-level `issue_slot`
- `published_day_ahead[*].value_type = "day_ahead"`
- `days[*].value_type = "forecast"`

HTML näyttää **Julkaistu / Ennuste** -merkinnät ja otsikoi ennustehorisontin
issue-slotin mukaan.

## Asennus

Pura nämä tiedostot projektin juureen ja aja:

```powershell
.\.venv\Scripts\python.exe .\apply_issue_slot_display_patch.py
```

Patcher:
- tekee varmuuskopion `patch_backups`-hakemistoon
- muuttaa vain tarvittavat lähdetiedostot
- ajaa Python-syntaksitarkistukset
- ajaa `git diff --check`
- palauttaa alkuperäiset tiedostot automaattisesti, jos patch epäonnistuu

## Tarkistus

```powershell
git status
git diff --check
```

Paikallisen iltapäiväajon jälkeen:

```powershell
.\verify_issue_slot_output.ps1 -ExpectedSlot afternoon
```

Aamun logiikan käsitesti:

```powershell
$env:FORECAST_ISSUE_SLOT="morning"
.\30_AJA_JA_JULKAISE.bat
Remove-Item Env:\FORECAST_ISSUE_SLOT
.\verify_issue_slot_output.ps1 -ExpectedSlot morning
```

Huomaa: morning-käsitesti tuottaa oikean uuden paikallisen ennusteajon.

## v2-korjaus

Ensimmäisen paketin import-tarkistus oli liian tarkka ja odotti `import math`-rivin
olevan suoraan `import statistics`-rivin edellä. Nykyisessä `main`-versiossa niiden
välissä/ympärillä on myös muita importteja. v2 lisää `import os`-rivin rakenteesta
riippumattomammin. Jos ensimmäinen ajo epäonnistui, sen automaattinen rollback
palautti alkuperäiset tiedostot, joten v2 voidaan ajaa suoraan uudelleen.
