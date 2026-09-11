"""De Shopify-app, stap 1: installeren en de verplichte webhooks.

Hier zit de beveiliging van het hele verhaal. Wat er fout kan gaan zonder dat
je het merkt:

- Een handtekening die niet gecontroleerd wordt. Dan kan iedereen ons namens
  een willekeurige winkel opdrachten geven, en dan zakt de app bovendien voor
  de beoordeling van Shopify.
- Een winkeladres dat we klakkeloos overnemen. Dan geven we onze sleutel af aan
  de server van iemand anders.
- Een shop/redact die niet echt alles wist. Dat is een wettelijke verplichting.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["SHOPIFY_API_KEY"] = "test-client-id"
os.environ["SHOPIFY_API_SECRET"] = "test-geheim"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


nep = types.ModuleType("payments")
nep.AUDIT_PRICE = nep.MONITORING_PRICE = nep.UITVOERING_PRICE = {"currency": "EUR", "value": "1"}
for naam in ("create_audit_payment", "create_monitoring_signup", "create_uitvoering_payment"):
    setattr(nep, naam, lambda *a, **k: {"error": "niet in deze test"})
nep.get_payment_status = lambda pid: None
nep.create_subscription = lambda cid: {}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {"ok": True}
sys.modules["payments"] = nep

import db
import shopify_app
import app as krillo

# Niets echt naar Shopify sturen.
shopify_app.winkelgegevens = lambda winkel, sleutel: {
    "naam": "Testwinkel", "email": "eigenaar@testwinkel.nl", "domein": "testwinkel.nl"}
aangemeld = []
shopify_app.meld_webhooks_aan = lambda winkel, sleutel, basis: (
    aangemeld.append(winkel) or {"gelukt": [w for w, _ in shopify_app.WEBHOOKS], "mislukt": []})
shopify_app.haal_toegangssleutel = lambda winkel, code: (
    {"gelukt": True, "sleutel": "shpat_testsleutel", "rechten": shopify_app.SCOPES}
    if code == "goede-code" else {"gelukt": False, "fout": "code deugt niet"})

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

client = krillo.app.test_client()
WINKEL = "testwinkel.myshopify.com"
GEHEIM = "test-geheim"


def query_handtekening(waarden):
    bericht = "&".join(f"{k}={waarden[k]}" for k in sorted(waarden))
    return hmac.new(GEHEIM.encode(), bericht.encode(), hashlib.sha256).hexdigest()


def webhook_handtekening(body):
    return base64.b64encode(
        hmac.new(GEHEIM.encode(), body, hashlib.sha256).digest()).decode()


print("\n== welke winkeladressen we vertrouwen ==")
for adres, mag in [
    ("testwinkel.myshopify.com", True),
    ("mijn-winkel-123.myshopify.com", True),
    ("TESTWINKEL.myshopify.com", True),
    ("kwaadaardig.nl", False),
    ("testwinkel.myshopify.com.kwaadaardig.nl", False),
    ("evil.com/testwinkel.myshopify.com", False),
    ("testwinkel.myshopify.com:8080", False),
    ("-begintmetstreepje.myshopify.com", False),
    ("", False), (None, False), (12345, False),
    ("../../etc/passwd", False),
]:
    zo(f"winkeladres {adres!r}", shopify_app.geldige_winkel(adres), mag)

print("\n== de handtekening op de terugkeerlink ==")
goed = {"shop": WINKEL, "code": "goede-code", "state": "abc", "timestamp": "123"}
goed["hmac"] = query_handtekening({k: v for k, v in goed.items()})
zo("goede handtekening", shopify_app.klopt_query_handtekening(goed), True)
kapot = dict(goed, shop="anderewinkel.myshopify.com")
zo("gewijzigde winkel valt door de mand", shopify_app.klopt_query_handtekening(kapot), False)
zo("zonder handtekening", shopify_app.klopt_query_handtekening({"shop": WINKEL}), False)
zo("lege handtekening", shopify_app.klopt_query_handtekening({"shop": WINKEL, "hmac": ""}), False)

print("\n== de handtekening op een webhook ==")
body = json.dumps({"shop_domain": WINKEL}).encode()
zo("goede handtekening", shopify_app.klopt_webhook_handtekening(body, webhook_handtekening(body)), True)
zo("verkeerde handtekening", shopify_app.klopt_webhook_handtekening(body, "onzin"), False)
zo("geen handtekening", shopify_app.klopt_webhook_handtekening(body, None), False)
zo("andere body", shopify_app.klopt_webhook_handtekening(b'{"x":1}', webhook_handtekening(body)), False)

print("\n== de installatielink ==")
link = shopify_app.installatielink(WINKEL, "https://www.krillo.nl")
zo("wijst naar de winkel zelf", link.startswith(f"https://{WINKEL}/admin/oauth/authorize?"), True)
zo("met onze client id", "client_id=test-client-id" in link, True)
zo("met een terugkeeradres", "redirect_uri=https%3A%2F%2Fwww.krillo.nl%2Fshopify%2Fcallback" in link, True)
zo("en een eenmalig kenmerk", "state=" in link, True)
zo("geen link voor een vals adres", shopify_app.installatielink("kwaadaardig.nl", "https://x"), None)

kenmerk = link.split("state=")[1].split("&")[0]
zo("het kenmerk is van ons", shopify_app.kenmerk_klopt(kenmerk), True)
zo("en werkt maar een keer", shopify_app.kenmerk_klopt(kenmerk), False)
zo("een verzonnen kenmerk niet", shopify_app.kenmerk_klopt("zelfbedacht"), False)

print("\n== de startpagina ==")
zo("zonder winkel geen doorverwijzing", client.get("/shopify").status_code, 400)
zo("met een vals adres ook niet", client.get("/shopify?shop=kwaadaardig.nl").status_code, 400)
# Een winkel die de app nog NIET heeft, moet naar het toestemmingsscherm. Maar
# niet met een gewone doorverwijzing: Shopify weigert zijn eigen
# toestemmingspagina in een venster binnen het beheerscherm, en dan ziet de
# winkelier een lege bladzijde. Daarom een pagina die het BOVENSTE venster
# verplaatst.
r = client.get(f"/shopify?shop={WINKEL}")
zo("met een echt adres krijg je een pagina", r.status_code, 200)
p = r.get_data(as_text=True)
zo("met de link naar Shopify erin", f"https://{WINKEL}/admin/oauth" in p, True)
zo("die het bovenste venster verplaatst", "window.top" in p, True)
zo("en een link voor als dat niet lukt", 'target="_top"' in p, True)
p = client.get("/shopify?shop=kwaadaardig.nl").get_data(as_text=True)
zo("het opgegeven adres komt niet op de pagina", "kwaadaardig.nl" in p, False)

print("\n== de terugkeerlink ==")
r = client.get(f"/shopify?shop={WINKEL}")
# Het eenmalige kenmerk staat nu in de link op de pagina in plaats van in
# een doorverwijzingskop.
kenmerk = r.get_data(as_text=True).split("state=")[1].split("&")[0].split('"')[0]
waarden = {"shop": WINKEL, "code": "goede-code", "state": kenmerk, "timestamp": "123"}
waarden["hmac"] = query_handtekening({k: v for k, v in waarden.items()})

kapot = dict(waarden, hmac="onzin")
zo("foute handtekening wordt geweigerd",
   client.get("/shopify/callback", query_string=kapot).status_code, 401)
zo("en de winkel staat nog nergens", db.get_shopify_winkel(WINKEL), None)

# Let op bij het bouwen van deze test: de handtekening wordt berekend over
# alles BEHALVE de handtekening zelf. Reken je hem uit over een lijst waar de
# vorige hmac nog in staat, dan klopt hij niet en test je iets anders dan je
# denkt. Dat had ik hier eerst fout.
zonder = {k: v for k, v in waarden.items() if k not in ("state", "hmac")}
zonder["state"] = "verzonnen"
zonder["hmac"] = query_handtekening({k: v for k, v in zonder.items()})
zo("een verzonnen kenmerk wordt geweigerd",
   client.get("/shopify/callback", query_string=zonder).status_code, 400)

r = client.get("/shopify/callback", query_string=waarden)
zo("de goede link installeert", r.status_code, 302)
# Naar het SCHERM VAN DE APP, niet naar de lijst met alle apps. "Redirect to
# the app UI after installation" staat letterlijk in de eisen van Shopify.
#
# Dit adres loopt via de winkel zelf, met ons klantnummer bij Shopify erin.
# Bewust niet via admin.shopify.com met de naam van de app erachter: die naam
# kennen wij niet met zekerheid, en klopt hij niet, dan belandt de winkelier op
# een 404 op precies het moment dat hij net akkoord ging met 39 dollar.
zo("en stuurt naar het scherm van de app in de winkel",
   r.headers["Location"], "https://testwinkel.myshopify.com/admin/apps/test-client-id")
w = db.get_shopify_winkel(WINKEL)
zo("de winkel staat er nu", w is not None, True)
zo("met de sleutel", w["toegangssleutel"], "shpat_testsleutel")
zo("en het gewone webadres", w["webshop_url"], "https://testwinkel.nl")
zo("en het mailadres", w["email"], "eigenaar@testwinkel.nl")
zo("de winkel is actief", w["actief"], True)

import time
for _ in range(30):
    if aangemeld:
        break
    time.sleep(0.1)
zo("de webhooks zijn aangemeld", WINKEL in aangemeld, True)

print("\n== dezelfde terugkeerlink nog eens ==")
zo("werkt niet nog een keer",
   client.get("/shopify/callback", query_string=waarden).status_code, 400)

print("\n== de webhooks ==")
paden = ["/shopify/webhooks/klantgegevens", "/shopify/webhooks/klant-wissen",
         "/shopify/webhooks/winkel-wissen", "/shopify/webhooks/verwijderd"]
for pad in paden:
    r = client.post(pad, data=b'{"x":1}',
                    headers={"X-Shopify-Hmac-Sha256": "onzin",
                             "X-Shopify-Shop-Domain": WINKEL,
                             "Content-Type": "application/json"})
    zo(f"{pad} weigert een foute handtekening met 401", r.status_code, 401)

for pad in paden[:2]:
    body = json.dumps({"shop_domain": WINKEL}).encode()
    r = client.post(pad, data=body,
                    headers={"X-Shopify-Hmac-Sha256": webhook_handtekening(body),
                             "X-Shopify-Shop-Domain": WINKEL,
                             "Content-Type": "application/json"})
    zo(f"{pad} accepteert een goede handtekening", r.status_code, 200)

print("\n== de app wordt verwijderd ==")
body = json.dumps({"shop_domain": WINKEL}).encode()
r = client.post("/shopify/webhooks/verwijderd", data=body,
                headers={"X-Shopify-Hmac-Sha256": webhook_handtekening(body),
                         "X-Shopify-Shop-Domain": WINKEL,
                         "Content-Type": "application/json"})
zo("netjes beantwoord", r.status_code, 200)
w = db.get_shopify_winkel(WINKEL)
zo("de winkel staat op verwijderd", w["actief"], False)
zo("de sleutel is gewist", w["toegangssleutel"], None)
zo("maar de rij bestaat nog", w is not None, True)

print("\n== opnieuw installeren na verwijderen ==")
r = client.get(f"/shopify?shop={WINKEL}")
# Het eenmalige kenmerk staat nu in de link op de pagina in plaats van in
# een doorverwijzingskop.
kenmerk = r.get_data(as_text=True).split("state=")[1].split("&")[0].split('"')[0]
opnieuw = {"shop": WINKEL, "code": "goede-code", "state": kenmerk, "timestamp": "999"}
opnieuw["hmac"] = query_handtekening({k: v for k, v in opnieuw.items()})
client.get("/shopify/callback", query_string=opnieuw)
w = db.get_shopify_winkel(WINKEL)
zo("weer actief", w["actief"], True)
zo("met een nieuwe sleutel", w["toegangssleutel"], "shpat_testsleutel")
zo("en zonder verwijderdatum", w["verwijderd_op"], None)

print("\n== shop/redact wist echt alles ==")
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO gratis_scans (webshop_url, score, gelukt)
                       VALUES ('https://testwinkel.nl', 60, true)""")
conn.close()
db.bewaar_wijziging("https://testwinkel.nl", "faq", "Iets", oude_waarde="oud")
db.zet_platform("https://testwinkel.nl", "Shopify")
zo("er staat iets voor deze winkel", len(db.get_wijzigingen("https://testwinkel.nl")), 1)

body = json.dumps({"shop_domain": WINKEL}).encode()
r = client.post("/shopify/webhooks/winkel-wissen", data=body,
                headers={"X-Shopify-Hmac-Sha256": webhook_handtekening(body),
                         "X-Shopify-Shop-Domain": WINKEL,
                         "Content-Type": "application/json"})
zo("netjes beantwoord", r.status_code, 200)
zo("de winkel is weg", db.get_shopify_winkel(WINKEL), None)
zo("de wijzigingen zijn weg", db.get_wijzigingen("https://testwinkel.nl"), [])
zo("het winkelprofiel is weg",
   (db.get_winkelprofiel("https://testwinkel.nl") or {}).get("platform"), None)
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM gratis_scans WHERE webshop_url = 'https://testwinkel.nl'")
        zo("de scans zijn weg", cur.fetchone()[0], 0)
conn.close()

print("\n== de boekhouding blijft staan, maar zonder de winkelnaam ==")
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM kostengebeurtenissen")
        cur.execute("""INSERT INTO kostengebeurtenissen
                           (gebeurtenis_id, soort, webshop_url, kosten)
                       VALUES ('test-1', 'test', 'https://tweede.nl', 0.02)""")
conn.close()
db.bewaar_shopify_winkel("tweede.myshopify.com", "shpat_x",
                         geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://tweede.nl")
body = json.dumps({"shop_domain": "tweede.myshopify.com"}).encode()
client.post("/shopify/webhooks/winkel-wissen", data=body,
            headers={"X-Shopify-Hmac-Sha256": webhook_handtekening(body),
                     "X-Shopify-Shop-Domain": "tweede.myshopify.com",
                     "Content-Type": "application/json"})
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(webshop_url) FROM kostengebeurtenissen")
        aantal, met_url = cur.fetchone()
conn.close()
zo("de kostenregel staat er nog", aantal, 1)
zo("maar zonder winkelnaam", met_url, 0)

print("\n== zonder sleutels in Render doet de app niets ==")
os.environ.pop("SHOPIFY_API_SECRET")
zo("niet beschikbaar", shopify_app.beschikbaar(), False)
zo("met uitleg", "SHOPIFY_API_SECRET" in shopify_app.waarom_niet(), True)
zo("geen handtekening te controleren", shopify_app.klopt_query_handtekening(goed), False)
zo("startpagina meldt het netjes", client.get(f"/shopify?shop={WINKEL}").status_code, 503)
os.environ["SHOPIFY_API_SECRET"] = GEHEIM

print("\n== de beheerpagina ==")
# Sinds de beheerpagina's achter een inlogscherm zitten is 302 (doorsturen naar
# /admin/inloggen) het goede antwoord, en geen 404 meer. En let op: een client
# die eerder MET sleutel binnenkwam blijft ingelogd, dus voor de dichte kant
# hoort een VERSE bezoeker gebruikt te worden.
zo("zonder sleutel dicht",
   krillo.app.test_client().get("/admin/shopify").status_code, 302)
zo("met sleutel open",
   krillo.app.test_client().get("/admin/shopify?key=testsleutel",
                                follow_redirects=True).status_code, 200)

print("\n== het ene adres voor de drie verplichte privacy-webhooks ==")
# Dit is het adres dat in shopify.app.toml komt te staan. Alle drie de
# onderwerpen komen hier binnen en worden op de kop X-Shopify-Topic uit elkaar
# gehaald. Op dit punt wordt de app afgekeurd als het niet klopt, dus hier
# wordt streng op getoetst.
import hmac as _hmac, hashlib as _hashlib, base64 as _base64, json as _json


def teken(body):
    return _base64.b64encode(
        _hmac.new(os.environ["SHOPIFY_API_SECRET"].encode(), body,
                  _hashlib.sha256).digest()).decode()


def stuur(onderwerp, winkel="testwinkel.myshopify.com", handtekening=None, body=None):
    body = body if body is not None else _json.dumps({"shop_domain": winkel}).encode()
    return client.post("/shopify/webhooks/naleving", data=body,
                       headers={"X-Shopify-Hmac-Sha256": handtekening or teken(body),
                                "X-Shopify-Topic": onderwerp,
                                "X-Shopify-Shop-Domain": winkel,
                                "Content-Type": "application/json"})


for onderwerp in ("customers/data_request", "customers/redact", "shop/redact"):
    zo(f"{onderwerp} wordt aangenomen", stuur(onderwerp).status_code, 200)

zo("een verkeerde handtekening geeft 401",
   stuur("shop/redact", handtekening="ditkloptniet").status_code, 401)
zo("geen handtekening geeft 401",
   client.post("/shopify/webhooks/naleving", data=b"{}",
               headers={"X-Shopify-Topic": "shop/redact"}).status_code, 401)
zo("een lege body met de juiste handtekening mag wel",
   stuur("customers/redact", body=b"").status_code, 200)
zo("een onbekend onderwerp geeft geen foutmelding terug",
   stuur("iets/anders").status_code, 200)

# En het echte werk: shop/redact moet alles van die winkel wissen.
db.bewaar_shopify_winkel("wiswinkel.myshopify.com", "shpat_z",
                         geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://wiswinkel.nl")
zo("de winkel staat erin", bool(db.get_shopify_winkel("wiswinkel.myshopify.com")), True)
zo("shop/redact wordt aangenomen",
   stuur("shop/redact", winkel="wiswinkel.myshopify.com").status_code, 200)
rij = db.get_shopify_winkel("wiswinkel.myshopify.com")
zo("en de winkel is echt weg", rij, None)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
