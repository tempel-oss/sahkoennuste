from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import socket
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electricity_forecaster.config import get_secret, ENTSOE_API_BASES
from electricity_forecaster.entsoe_ingest import load_areas

print("ENTSO-E API -yhteystesti v0.4.2")
print("================================")

try:
    token = get_secret("ENTSOE_API_TOKEN")
except Exception as exc:
    print("\nTESTI EPAONNISTUI: tokenia ei voitu lukea.")
    print(exc)
    sys.exit(1)

print(f"Token loytyi .env-tiedostosta (pituus {len(token)} merkkia).")
print("Tokenia ei nayteta ruudulla.\n")

fi = load_areas()["FI"]
now = datetime.now(timezone.utc)
end = now.replace(hour=0, minute=0, second=0, microsecond=0)
start = end - timedelta(days=1)

params = {
    "securityToken": token,
    "documentType": "A44",
    "in_Domain": fi,
    "out_Domain": fi,
    "periodStart": start.strftime("%Y%m%d%H%M"),
    "periodEnd": end.strftime("%Y%m%d%H%M"),
}


def looks_html(raw: bytes) -> bool:
    head = raw[:1000].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head


def xml_summary(raw: bytes):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return False, "Vastaus ei ole kelvollista XML:aa."
    local = lambda tag: tag.rsplit("}", 1)[-1]
    ts = [x for x in root.iter() if local(x.tag) == "TimeSeries"]
    reasons = [x.text.strip() for x in root.iter() if local(x.tag) == "text" and x.text and x.text.strip()]
    if ts:
        return True, f"XML kunnossa, TimeSeries-sarjoja: {len(ts)}"
    if reasons:
        return False, "ENTSO-E API-vastaus: " + " | ".join(reasons[:3])
    return False, "XML saatiin, mutta TimeSeries-dataa ei loytynyt."


def test_endpoint(endpoint: str):
    host = endpoint.split("//", 1)[-1].split("/", 1)[0]
    print(f"\nEndpoint: {endpoint}")
    try:
        ips = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        print("DNS:", ", ".join(ips[:4]) if ips else "ei osoitetta")
    except OSError as exc:
        print("DNS VIRHE:", exc)
        return {"endpoint": endpoint, "ok": False, "kind": "dns", "status": None, "ctype": ""}

    url = endpoint + "?" + urlencode(params)
    req = Request(url, headers={
        "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1",
        "User-Agent": "electricity-forecaster/0.4.2-windows-native",
        "Cache-Control": "no-cache",
    })
    try:
        with urlopen(req, timeout=45) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200)
            ctype = (resp.headers.get("Content-Type") or "").strip()
            print("HTTP:", status)
            print("Content-Type:", ctype or "(puuttuu)")
            print("Vastauksen koko:", len(raw), "tavua")
            if looks_html(raw):
                print("TULOS: HTML-vastaus API/XML-datan sijasta.")
                return {"endpoint": endpoint, "ok": False, "kind": "html", "status": status, "ctype": ctype}
            ok, msg = xml_summary(raw)
            print("TULOS:", msg)
            return {"endpoint": endpoint, "ok": ok, "kind": "xml_ok" if ok else "xml_error", "status": status, "ctype": ctype}
    except HTTPError as exc:
        raw = exc.read()
        ctype = (exc.headers.get("Content-Type") or "").strip() if exc.headers else ""
        print("HTTP:", exc.code)
        print("Content-Type:", ctype or "(puuttuu)")
        if looks_html(raw):
            print("TULOS: HTTP-virhe + HTML-vastaus.")
            kind = "html_http"
        else:
            ok, msg = xml_summary(raw)
            print("TULOS:", msg)
            kind = "auth" if exc.code in (401, 403) else "http_error"
        return {"endpoint": endpoint, "ok": False, "kind": kind, "status": exc.code, "ctype": ctype}
    except URLError as exc:
        print("VERKKOVIRHE:", exc.reason)
        return {"endpoint": endpoint, "ok": False, "kind": "network", "status": None, "ctype": ""}
    except TimeoutError:
        print("AIKAKATKAISU")
        return {"endpoint": endpoint, "ok": False, "kind": "timeout", "status": None, "ctype": ""}
    except Exception as exc:
        print("ODOTTAMATON VIRHE:", type(exc).__name__, exc)
        return {"endpoint": endpoint, "ok": False, "kind": "unknown", "status": None, "ctype": ""}


print("Testikysely: Suomen edellisen kokonaisen UTC-vuorokauden A44 day-ahead-hinnat")
print(f"Jakso UTC: {start:%Y-%m-%d %H:%M} - {end:%Y-%m-%d %H:%M}")
print("Molemmat dokumentoidut tuotanto-endpointit testataan ERIKSEEN, jotta varayhteys ei peita tulosta.")

results = [test_endpoint(ep) for ep in ENTSOE_API_BASES]

print("\n================================")
print("YHTEENVETO")
print("================================")
for r in results:
    print(f"{r['endpoint']}: ok={r['ok']}, tyyppi={r['kind']}, HTTP={r['status']}, Content-Type={r['ctype'] or '-'}")

working = [r for r in results if r["ok"]]
if working:
    print("\nOK - vahintaan yksi ENTSO-E Web API -endpoint toimii oikealla XML-datalla.")
    print("Ensisijainen toimiva endpoint:", working[0]["endpoint"])
    sys.exit(0)

if any(r["kind"] == "auth" for r in results):
    print("\nJOHTOPAATOS: palvelin hylkasi kayttooikeuden ainakin yhdessa endpointissa (HTTP 401/403).")
    print("Tarkista Web API Security Token ja RESTful API access -oikeus ENTSO-E-tililta.")
    sys.exit(3)

if all(r["kind"] in {"html", "html_http", "network", "timeout", "dns"} for r in results):
    print("\nJOHTOPAATOS: kumpikaan endpoint ei palauttanut kelvollista API/XML-dataa.")
    print("Tokenia ei talla tuloksella voida todeta vaaraksi. Todennakoisin syy on palvelu/reititys/verkkoyhteys.")
    sys.exit(2)

print("\nJOHTOPAATOS: ENTSO-E vastasi, mutta kelvollista TimeSeries-dataa ei saatu.")
print("Laheta tama lyhyt yhteenveto jatkoanalyysiin; token ei valttamatta ole vaarin.")
sys.exit(4)
