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
