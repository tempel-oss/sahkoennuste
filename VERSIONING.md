# Versiointi tässä projektissa

Projektissa on useita rinnakkaisia numerointeja, jotka tarkoittavat eri asioita. Tämä tiedosto on ainoa paikka joka selittää mikä numero tarkoittaa mitäkin — se ei muuta mitään olemassa olevaa versionumeroa (osa niistä luetaan ohjelmallisesti), vaan kokoaa ne yhteen.

## 1. Projektin/paketin versio — `VERSION.txt`

Nykyinen arvo: **1.4.1**

Tämä on koko `electricity_forecaster`-paketin (koodi + dashboard) yleisversio. Sitä kasvatetaan kun mikä tahansa osa projektista muuttuu merkittävästi (uusi ominaisuus, iso korjaus). Näkyy mm. `production_output.py`:n generoiman dashboardin footerissa ("Electricity Forecaster v1.4.1 ML Readiness") ja `scripts/production_runner.py`:n tulosteessa.

## 2. Tuotantomallin versio — `forecast_engine.MODEL_NAME` / `MODEL_VERSION`

Nykyinen arvo: **`fundamental_baseline` 0.7.1**

Tämä on itse hintaennustemallin (ei koko paketin) versio. Se on tallennettu jokaiseen `price_forecast_runs`-riviin ja `model_registry`-tauluun, ja sitä käytetään ohjelmallisesti (esim. `production_output.py`:n "Koulutettu ML: Kyllä/Ei vielä" -tunnisteessa, joka vertaa `model_name`-arvoa merkkijonoon `"fundamental_baseline"`). **Tätä ei pidä muuttaa vapaamuotoisesti** — versio ja nimi ovat osa tietokantaskeeman semantiikkaa (champion-tunnistus `model_registry.py`:ssä).

Erillinen `train_residual_challenger_v1.py` seuraa omaa mallikohtaista versiotaan (`MODEL_NAME="residual_hgb"`, `MODEL_VERSION="0.1"`) — se on Challenger, ei koskaan Champion, eikä siksi liity `VERSION.txt`:hen millään tavalla.

## 3. "v1.5.x" — historiallinen ML-oppimisen haara

Tiedostot `README_v1.5*.md`, `README_v1.5.9*.txt`, `requirements-v1.5.txt`, `build_horizon_v1_5_*.py`, `train_residual_challenger_v1.py` ym. viittaavat erilliseen kehityslinjaan, jossa rakennettiin leakage-safe historiallinen ML-aineisto (`data/processed/v1_5_8/...`) ja ensimmäinen Residual Challenger -malli. Numero "1.5" **ei ole sama asia kuin projektin versio 1.4.1** — se on tämän erillisen ML-työn oma juokseva numerointi, joka kasvoi 1.5:stä 1.5.9.1:een. Käytännössä: jos näet "v1.5.x", kyse on ML/data-putken kehityksestä, ei koko sovelluksen julkaisuversiosta.

## 4. "v3.x" — dashboardin issue-slot-näyttöpatchit

`apply_issue_slot_display_patch*.py` ja niiden README:t (`README_v3.md`, `README_v3_1.md`, `README_v3_2.md`) käyttävät omaa "v1 → v3 → v3.1 → v3.2" -numerointia. Tämä on yhden kertaluonteisen korjaussarjan (aamu/iltapäivä-issue-slotin näyttölogiikka) sisäinen versiohistoria, ei projektin eikä minkään moduulin versio. **Vain v3.2 on ajettu onnistuneesti ja leivottu lähdekoodiin.** Versiot v1, v3 ja v3.1 sisälsivät kukin oman bugin (ks. kunkin README), ja niiden `main()`-funktiot on nyt suojattu niin, että ne kieltäytyvät ajamasta ja ohjaavat v3.2:een — ks. `apply_issue_slot_display_patch.py`, `_v3.py`, `_v3_1.py`.

`apply_colorful_ui_v1.py` on oma, erillinen kertapatch (dashboardin väritys), jo sovellettu ja jo idempotentti (tarkistaa `COLORFUL_UI_V1`-merkin ja ei tee mitään jos patch on jo asennettu).

## Yhteenveto: mistä tiedän mikä versio oikeasti pyörii?

- **Koko sovellus / dashboard**: `VERSION.txt` (1.4.1).
- **Tuotannossa oleva hintaennustemalli**: `model_registry`-taulun `champion`-rivi tai dashboardin "Mallin tila" -kortti (`fundamental_baseline 0.7.1`).
- **ML-kehitystyö (Challenger, historia-aineisto)**: oma dokumentaationsa `README_residual_challenger_v1.md` ja `README_v1.5*`-tiedostoissa, ei liity `VERSION.txt`:hen.
- **Jo ajetut kertapatchit** (`apply_*_patch*.py`): historiallinen viite, ei ohjelman versio. Vain uusin (`apply_issue_slot_display_patch_v3_2.py`, `apply_colorful_ui_v1.py`) on turvallinen ajaa, ja senkin tarvitsee ajaa vain kerran (molemmat tunnistavat jo-asennetun tilan).
