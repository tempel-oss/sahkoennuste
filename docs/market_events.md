# Markkinatapahtumat ennusteen selityksissä (kehitysvaihe 1)

Ennusteen HTML- ja JSON-julkaisu osaa lukea valinnaisen tiedoston
`data/market_events.json`. Tiedosto ei sisälly julkaisuun automaattisesti:
erillinen tapahtumakeräin on seuraava toteutusvaihe.

Syöte on olio, jonka `events`-kenttä sisältää tapahtumalistan:

```json
{
  "events": [{
    "title": "Esimerkki: voimalan tehorajoitus",
    "description": "Esimerkkitapahtuma, ei todellinen häiriö.",
    "source_url": "https://example.org/notice",
    "source_name": "Esimerkkilähde",
    "verification": "confirmed",
    "observed_at_utc": "2026-11-02T13:00:00Z",
    "start_utc": "2026-11-02T12:00:00Z",
    "end_utc": "2026-11-03T10:00:00Z",
    "price_direction": "up"
  }]
}
```

Tämä on skeemaesimerkki, **ei** todennettu markkinatapahtuma.

Näkyviin pääsevät vain tapahtumat, joissa on HTTPS-lähde ja
`verification=confirmed`. Havainto ei saa olla ennusteajon jälkeinen tai
yli 72 tuntia vanha; tapahtuma ei saa olla päättynyt ennen ennusteajoa,
eikä se saa alkaa yli 12 päivää myöhemmin. Enintään viisi viimeisintä
näytetään. Hintavaikutus on laadullinen eikä ilmaise toteutunutta
kausaalivaikutusta. Tuetut suunnat: `up`, `down`, `mixed`, `unknown`.

Jos vahvistettuja tapahtumia ei löydy, sivu kertoo, ettei aineistosta
voitu vahvistaa poikkeamia. Se ei väitä, ettei poikkeamia ole.

## Seuraavat toteutustyöt

- Automaattinen tapahtumakeräin ensisijaisesti virallisista lähteistä;
  aikaleimat, yksikkö/MW, alkamis- ja päättymisajat sekä peruutukset.
- Historiatallennus ja tapahtumapäivitysten versiointi.
- Tapahtuman ajallinen yhdistäminen D+2–D+12 hintamuutoksiin;
  määrälliset hintavaikutukset vain, jos ne voidaan perustella.
- Syötteen päivityksen ajastaminen pilviajossa ja julkaisun integrointitesti.

## Automaattinen keräys (vaihe 2)

`scripts/collect_market_events.py` hakee ENTSO-E Transparency APIsta
Suomen tarjousalueen ilmoitukset dokumenttityypeillä A80 ja A77.
Sama `ENTSOE_API_TOKEN`-salaisuus, jota muu ennustemoottori käyttää,
riittää keräimeen, mikäli rajapinnan käyttöoikeus kattaa nämä tiedot.

`scripts/production_runner.py` suorittaa keruun ennen HTML-julkaisua
ei-kriittisenä työvaiheena. Jos tunnus puuttuu, rajapintakysely epäonnistuu
tai vastaus on virheellinen, ennusteen laskenta jatkuu ja käyttöliittymä
kertoo, ettei poikkeamia ole vahvistettu aineistosta. Vain kummankin
kyselyn onnistuttua tiedosto kirjoitetaan atomisesti.

**Rajaukset:** Ensimmäinen automaattikeräin kattaa tuotantoyksiköiden
käytettävyysilmoitukset, ei vielä siirtoyhteyksien A78-ilmoituksia.
MW-määräisen poistuman laskentaa, hintavaikutuksen määrällistä mallia,
virallisen ilmoituksen muuttumishistoriaa tai datalähteen kattavuuden
varmistusta tuotannon CI-ajosta ei ole vielä toteutettu. ENTSO-E:n
julkaisema ilmoitus ei yksin todista hinnanmuutoksen syy-seuraussuhdetta.

Huomaa, että automaattinen keräin kirjoittaa ajantasaiset havainnot
`data/market_events.json`-tiedostoon; tiedostoa ei tallenneta
pitkäaikaiseen historiavarastoon tällä toteutuksella.

## Siirtoyhteydet ja hintamuutoksen ajallinen osuma (vaihe 3)

Keräin hakee lisäksi A78-siirtoinfrastruktuurin käytettävyysilmoitukset
Suomen ja SE1:n, SE3:n sekä Viron tarjousalueiden väliltä molempiin
suuntiin. Lähdekyselyjen onnistumismäärä näytetään ennustesivulla.
Osittainen onnistuminen ei tarkoita kattavaa markkinatilannekuvaa.

Jokaiselle vahvistetulle tapahtumalle lasketaan leikkaus ennusteen
D+2–D+12-päiviin Suomen aikavyöhykkeessä. Ajallinen päällekkäisyys on
**havainto**, ei tilastollinen syy-seurauspäätelmä tai arvio
hintavaikutuksen suuruudesta. A78-ilmoituksesta ei myöskään suoraan
päätellä kuinka monta megawattia siirtokapasiteetti väheni.

Tapahtuma-aineiston tuoreus ilmoitetaan erikseen, eikä vanhentuneen
syötteen puuttuvia havaintoja esitetä todisteena häiriöttömyydestä.

**Ennen tuotantoon vientiä:** varmistetaan ENTSO-E:n todellisten
A78/A80/A77-vastausten muodot ja rajapintaoikeudet, siirtoyhteyksien
vastavuoroisten kyselyjen kattavuus, peruttujen ilmoitusten tulkinta
sekä arkistoitavan tiedon vaatimukset. Pilviajon integraatiotesti
ja julkaisun luotettavuus arvioidaan erikseen.
