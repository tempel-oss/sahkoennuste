# v3 structural patch

v1/v2 olivat liian riippuvaisia täsmälleen samoista kokonaisista koodiriveistä.
v3 käyttää rakenteellisia ankkureita ja tulostaa jokaisen onnistuneen
muutosvaiheen erikseen.

Aja projektin juuressa:

```powershell
.\.venv\Scripts\python.exe .\apply_issue_slot_display_patch_v3.py
```

Jos jokin vaihe ei vastaa paikallista koodia, kaikki lähdetiedostomuutokset
palautetaan automaattisesti ja virhe kertoo täsmällisen kohdan.
