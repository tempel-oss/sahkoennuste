# Sähköennuste – Colorful UI v1

Muuttaa vain `production_output.py`-tiedoston visuaalista HTML/CSS-ilmettä.

- värikkäämpi otsake ja tausta
- hintatason mukaiset värikorostukset
- vahvemmat riskivärit
- värikoodatut taustatekijät
- värikkäämmät laatukortit
- ei muutoksia ennustelogiikkaan, JSON-arvoihin, ajastukseen tai issue-slot-logiikkaan

Hintavärit:
- alle 4 snt/kWh: vihreä
- 4–7: turkoosi
- 7–12: sininen
- 12–20: oranssi
- yli 20: punainen

Asennus projektin juuressa:

```powershell
.\.venv\Scripts\python.exe .\apply_colorful_ui_v1.py
```
