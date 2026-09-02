## v0.7.1 hotfix

Windows/Python 3.14: Europe/Helsinki-aikavyohyke toimii nyt ilman erillista tzdata-pakettia.

# Electricity Forecaster v0.4.1 – Windows Native

Tama versio korjaa ENTSO-E-yhteystestin ja tekee API-yhteydesta hairionsietoisemman.
Dockeria, PostgreSQL:aa, virtuaaliymparistoa tai pip-asennuksia ei tarvita taman vaiheen datankeruuseen.

## Paivitys v0.4:sta

1. Pura v0.4.1 uuteen kansioon.
2. Kopioi vanhasta v0.4-kansiosta `.env` uuden version `electricity_forecaster`-kansioon.
3. Aja `00_ASENNA.bat`. Olemassa olevaa `.env`-tiedostoa ei ylikirjoiteta.
4. Aja `05_TESTAA_ENTSOE.bat`.

## ENTSO-E-testin parannukset

v0.4.1:

- erottaa autentikointivirheen, kyselyvirheen, HTTP 429:n, 5xx-palveluhairion, aikakatkaisun ja verkkovirheen
- ei tulosta pitkaa HTML-virhesivua
- tekee automaattisia uudelleenyrityksia tilapaisissa hairioissa
- kokeilee palveluhairiossa kahta ENTSO-E:n dokumentoitua tuotanto-API-osoitetta
- tekee DNS-tarkistuksen ennen varsinaista API-tulkintaa
- testaa edellisen kokonaisen vuorokauden Suomen A44 day-ahead-hinnoilla, jotta julkaisemattoman datan puuttuminen ei sotke token-testiä
- ei koskaan tulosta tokenin sisaltoa; vain sen pituuden

### Tulosten tulkinta

`OK - ENTSO-E API-token ja API-yhteys toimivat.`
: kaikki kunnossa.

`Luokka: service_unavailable`, `service_html`, `network`, `timeout` tai `rate_limit`
: tokenia ei ole todettu vaaraksi; kyse voi olla ENTSO-E:n tai verkkoyhteyden tilapaisesta hairiosta.

`Luokka: auth`
: palvelu hylkasi kayttooikeuden. Tarkista Web API Security Token ja Restful API access.

`Luokka: request`
: API-yhteys syntyi, mutta kysely hylattiin. Token voi olla kunnossa; virheilmoitus kannattaa analysoida erikseen.

## Avaimet

`.env`-tiedostossa:

    FINGRID_API_KEY=oma_fingrid_avain
    ENTSOE_API_TOKEN=oma_entsoe_token

Avaimia ei kirjoiteta Python-koodiin.

## Datan keruu

Kun `05_TESTAA_ENTSOE.bat` onnistuu, aja `06_HAE_ENTSOE_DATA.bat`.
Fingrid: `03_HAE_FINGRID_DATA.bat`.
Tilanne: `04_NAYTA_TILANNE.bat`.

Tietokanta: `data\electricity_forecaster.sqlite3`

## v0.4.2: ENTSO-E-yhteysdiagnostiikka

`05_TESTAA_ENTSOE.bat` testaa nyt erikseen molemmat ENTSO-E:n tuotantoon dokumentoidut Web API -osoitteet:

1. `https://web-api.tp.entsoe.eu/api` (ensisijainen)
2. `https://transparency.entsoe.eu/api` (legacy/varayhteys)

Testi nayttaa kummallekin endpointille DNS-tuloksen, HTTP-statuskoodin, Content-Type-otsakkeen, vastauksen koon ja sen, saatiinko oikeaa XML/TimeSeries-dataa vai HTML-verkkosivu. Tokenia ei tulosteta ruudulle.

Jos vain toinen endpoint toimii, tuotantokerain voi jatkaa toimivalla endpointilla. Jos kumpikin palauttaa HTML:aa tai palveluvirheen, tokenia ei taman perusteella todeta vaaraksi.

# v0.5 – säädata, ENTSO-E-valvonta ja yhdistetyt featuret

## Uutta
- ENTSO-E-häiriö ei pysäytä muuta keruuta. Päivittäinen keruu merkitsee palvelun `degraded`-tilaan ja jatkaa Fingridiin, säähän ja featureihin.
- FMI HARMONIE -piste-ennusteita kerätään lyhyelle horisontille.
- ECMWF IFS 15 vrk sääennuste kerätään Open-Meteon JSON-välityksen kautta. Tämä välttää GRIB-kirjastojen asennuksen Windowsiin.
- ECMWF ensemblea yritetään hakea 3 edustuspisteelle; jos ensemble-mallin tunniste/palvelu ei ole käytettävissä, deterministinen sääkeruu jatkuu normaalisti ja puute kirjataan.
- Sääennusteet arkistoidaan snapshotteina `data/raw/` alle.
- `features_hourly` yhdistää uusimman Fingrid-snapshotin ja säätekijät tuntitasolle.

## Uudet käynnistimet
- `07_HAE_SAADATA.bat` – hakee FMI + ECMWF säädatan.
- `08_RAKENNA_FEATURET.bat` – rakentaa yhdistetyn feature-snapshotin.
- `09_PAIVITTAINEN_KERUU.bat` – suositeltu normaali ajo: Fingrid -> ENTSO-E (best effort) -> sää -> featuret.

## Ensimmäinen ajo
1. Varmista että `.env` sisältää toimivan Fingrid-avaimen ja ENTSO-E-tokenin.
2. Aja `07_HAE_SAADATA.bat`.
3. Aja `08_RAKENNA_FEATURET.bat`.
4. Jos nämä toimivat, käytä jatkossa `09_PAIVITTAINEN_KERUU.bat`.

## Featuret v0.5
- väestö-/kulutusproxyllä painotettu lämpötila
- tuulivoima-alueproxyllä painotettu 100 m tuuli
- pilvisyys ja lyhytaaltosäteily
- tuulivoiman kapasiteettikerroinproxy
- ensemble P10/P50/P90 ja P90-P10-tuulihajonta, jos ensemble saadaan
- Fingrid kulutus-, tuuli-, aurinko- ja tuotantoennusteiden tuntikeskiarvot
- residual load tuulen ja aurinkosähkön jälkeen
- ennustettu nettotuontitarve

Painot ovat v0.5:ssa engineering-proxyja. Ne eivät ole virallisia väestö- tai tuulivoimakapasiteettiosuuksia. Kun toteumahistoriaa kertyy, painot ja muunnokset kalibroidaan datasta.

## v0.6 - Data Completeness

Uutta:
- Nord Poolin julkinen day-ahead hintakeruu ENTSO-E:n rinnalle (`11_HAE_HINTADATA.bat`).
- Fingrid-varasarjat: kulutusennuste 165, reaaliaikainen tuuli 181 ja tuotanto 192, tuulikapasiteetti 268.
- `10_TARKISTA_DATA.bat` toimii laatuporttina ennen ML-mallia.
- `12_PISTEYTA_ENNUSTEVIRHEET.bat` vertaa vanhoja Fingrid-ennusteita toteumiin.
- Featureihin lisataan FI/SE/EE/NO/DK-hintoja silloin kun ne on jo julkaistu, FI-SE3 hintaspread ja kalenterimuuttujat.
- Residual load kayttaa ensisijaisesti 72 h Fingrid-ennusteita ja tarvittaessa paivittaisia varasarjoja.

### Suositeltu v0.6 ensiajo
1. Kopioi vanha `.env` v0.6-kansioon.
2. Aja `00_ASENNA.bat`.
3. Aja `03_HAE_FINGRID_DATA.bat`.
4. Aja `11_HAE_HINTADATA.bat`.
5. Aja `07_HAE_SAADATA.bat`.
6. Aja `08_RAKENNA_FEATURET.bat`.
7. Aja `10_TARKISTA_DATA.bat`.

Jos viimeinen vaihe ilmoittaa `OK`, data on rakenteellisesti valmis ensimmaisen mallin rakentamiseen. Jos jokin kriittinen sarja puuttuu, laatuportti nimeaa sen suoraan.

Huom: Nord Poolin Data Portal -rajapinta on julkinen ja ilman autentikointia toimiva taustarajapinta, mutta se ei ole sama kuin Nord Poolin maksullinen, SLA-tuettu Market Data API. Siksi ENTSO-E pidetaan edelleen virallisempana rinnakkaislahteena, kun sen yhteys toimii.

## v0.6.1 korjaus

- Datan taydellisyystarkistus valitsee nyt viimeisimman Fingrid-ajon nimenomaan `source='fingrid'` perusteella.
- Feature-rakentaja kayttaa samaa source-aware valintaa, joten myohemmin ajettu ENTSO-E-run ei voi peittaa Fingridin 166/245-ennusteita.
- Uusi `13_DIAGNOSOI_FINGRID.bat` nayttaa datasetien 166 ja 245 viimeisimman ingestion-lokin, rivimaaran ja aikavalin.

# v0.7 - ensimmainen arkistoitava D+2...D+12 hintaennuste

v0.7 tuottaa ensimmaisen varsinaisen hintaennusteen ja tallentaa sen pysyvasti tietokantaan. Tama versio EI ole viela koulutettu ML/Champion-malli. Se on tarkoituksella lapi nakyva fundamentaalinen baseline, jonka ennusteita aletaan nyt verrata toteutuneisiin hintoihin.

## Paivitys v0.6.1:sta

Suositus: aja `00_PAIVITA_VANHASTA.bat` ja anna vanhan v0.6.1 `electricity_forecaster`-kansion polku. Skripti kopioi `.env`-tiedoston ja SQLite-tietokannan, jotta datamuisti sailyy. Vaihtoehtoisesti kopioi kasin:

- vanha `.env` -> v0.7 `electricity_forecaster\.env`
- vanha `data\electricity_forecaster.sqlite3` -> v0.7 `data\electricity_forecaster.sqlite3`

Aja taman jalkeen `00_ASENNA.bat`, joka paivittaa tietokantaan v0.7-taulut tuhoamatta vanhaa dataa.

## Uudet komennot

- `14_TEE_ENNUSTE.bat` - tekee ja arkistoi D+2...D+12 fundamenttiennusteen.
- `15_NAYTA_ENNUSTE.bat` - nayttaa viimeisimman ennusteen snt/kWh sis. ALV 25,5 %.
- `16_PISTEYTA_HINTAENNUSTEET.bat` - vertaa vanhoja tuntiennusteita julkaistuihin FI day-ahead -hintoihin ja nayttaa laatumittarit.
- `17_NAYTA_ENNUSTELAATU.bat` - nayttaa kertyneen MAE:n, baseline-MAE:n ja P10-P90-kattavuuden horisonteittain.

`09_PAIVITTAINEN_KERUU.bat` tekee v0.7:ssa koko ketjun: Fingrid -> Nord Pool -> ENTSO-E best effort -> saa -> featuret -> syotedatan virhepisteytys -> laatuportti -> hintaennuste -> vanhojen hintaennusteiden pisteytys.

## Ennustemenetelma v0.7

D+2/D+3 käyttää suoraan Fingridin kulutus-, tuuli- ja aurinkoennusteita, kun ne ovat saatavilla. Pidemmalle horisontille kulutusta jatketaan lampotilan, vuorokaudenajan ja viikonlopun perusteella kalibroidulla mallilla. Tuulituotantoa jatketaan ECMWF 100 m tuulesta Fingridin lahiennusteeseen kalibroidulla tuulivoimaproxylla. Aurinkotuotantoa jatketaan sateilyn perusteella.

Hintarunko ankkuroidaan viimeisimpaan julkaistuun FI day-ahead -hintaan ja sen tuntiprofiiliin. Sita korjataan net load / residual load -muutoksella ja lahialueiden julkaistulla markkinakontekstilla. P10-P90 levenee ennustehorisontin ja ECMWF-ensemble-tuulihajonnan kasvaessa.

Kertoimet ovat v0.7:ssa engineering-prioreita, eivat historiasta koulutettuja parametreja. Jokainen ennuste arkistoidaan, jotta Champion/Challenger-oppiminen voidaan aloittaa, kun toteumahistoriaa on kertynyt.
