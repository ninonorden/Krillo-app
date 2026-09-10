"""Betalen in de Shopify-app.

Waar geld in het spel is, is de vraag niet of het werkt maar wat er gebeurt als
het niet werkt. Daar gaat deze test over:

- Twee abonnementen naast elkaar. Dan betaalt iemand twee keer.
- Zeggen dat iemand betaalt terwijl wij het niet zeker weten. Bij twijfel
  behandelen wij hem als niet-betalend, nooit andersom.
- Een testabonnement dat per ongeluk live staat. Dat levert geen geld op en je
  merkt het pas op je rekening.
- Een opzegging die niet kan.
"""
import json
import os
import sys
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["SHOPIFY_API_KEY"] = "testklant"
os.environ["SHOPIFY_API_SECRET"] = "testgeheim"
os.environ["BASE_URL"] = "https://www.krillo.nl"
os.environ.pop("SHOPIFY_BILLING_TEST", None)
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

import shopify_billing

WINKEL = "testwinkel.myshopify.com"
SLEUTEL = "shpat_test"

# ------------------------------------------------------ een nagemaakte Shopify

class NepShopify:
    def __init__(self):
        self.abonnementen = []
        self.laatste_variabelen = None
        self.faalt = False
        self.klachten = []


shop = NepShopify()


def nep_graphql(winkel, sleutel, vraag, variabelen=None):
    shop.laatste_variabelen = variabelen
    if shop.faalt:
        return {"gelukt": False, "fout": "Shopify gaf 500: kapot"}
    if "currentAppInstallation" in vraag:
        return {"gelukt": True, "gegevens": {
            "currentAppInstallation": {"activeSubscriptions": shop.abonnementen}}}
    if "appSubscriptionCreate" in vraag:
        if shop.klachten:
            return {"gelukt": True, "gegevens": {"appSubscriptionCreate": {
                "userErrors": shop.klachten, "confirmationUrl": None,
                "appSubscription": None}}}
        nieuw = {"id": "gid://shopify/AppSubscription/1", "status": "PENDING"}
        return {"gelukt": True, "gegevens": {"appSubscriptionCreate": {
            "userErrors": [],
            "confirmationUrl": "https://testwinkel.myshopify.com/admin/charges/1/confirm",
            "appSubscription": nieuw}}}
    if "appSubscriptionCancel" in vraag:
        shop.abonnementen = []
        return {"gelukt": True, "gegevens": {"appSubscriptionCancel": {
            "userErrors": [], "appSubscription": {"id": variabelen["id"],
                                                  "status": "CANCELLED"}}}}
    return {"gelukt": False, "fout": "onbekende vraag"}


shopify_billing._graphql = nep_graphql

# ------------------------------------------------------------------ de stand

print("\n== de stand van het abonnement ==")
stand = shopify_billing.huidig_abonnement(WINKEL, SLEUTEL)
zo("zonder abonnement niet actief", stand["actief"], False)
zo("en geen abonnement erbij", stand["abonnement"], None)

shop.abonnementen = [{"id": "gid://1", "name": "Krillo monitoring", "status": "ACTIVE",
                      "test": False, "trialDays": 7}]
stand = shopify_billing.huidig_abonnement(WINKEL, SLEUTEL)
zo("met abonnement wel actief", stand["actief"], True)
zo("met de gegevens erbij", stand["abonnement"]["name"], "Krillo monitoring")

shop.abonnementen = [{"id": "gid://1", "name": "Krillo monitoring", "status": "PENDING",
                      "test": False}]
stand = shopify_billing.huidig_abonnement(WINKEL, SLEUTEL)
zo("een abonnement dat nog niet bevestigd is telt niet", stand["actief"], False)

shop.abonnementen = [{"id": "gid://1", "name": "x", "status": "CANCELLED"}]
zo("een opgezegd abonnement telt niet",
   shopify_billing.huidig_abonnement(WINKEL, SLEUTEL)["actief"], False)

print("\n== bij twijfel niet betalend ==")
shop.faalt = True
stand = shopify_billing.huidig_abonnement(WINKEL, SLEUTEL)
zo("een storing maakt niemand betalend", stand["actief"], False)
zo("met de reden erbij", bool(stand["fout"]), True)
shop.faalt = False
shop.abonnementen = []

# ------------------------------------------------------------- afsluiten

print("\n== een abonnement starten ==")
uit = shopify_billing.start_abonnement(WINKEL, SLEUTEL, "https://www.krillo.nl/shopify")
zo("gelukt", uit["gelukt"], True)
zo("met een bevestigingslink", uit["link"].startswith("https://"), True)
v = shop.laatste_variabelen
zo("de prijs klopt", v["bedrag"], "39.00")
zo("de valuta klopt", v["valuta"], "USD")
zo("de proefperiode klopt", v["proefdagen"], 7)
zo("het terugkeeradres is meegegeven", v["terugUrl"], "https://www.krillo.nl/shopify")

print("\n== testmodus staat standaard uit ==")
zo("niet in testmodus", shopify_billing.testmodus(), False)
zo("en dat gaat ook zo naar Shopify", v["test"], False)

os.environ["SHOPIFY_BILLING_TEST"] = "ja"
shopify_billing.start_abonnement(WINKEL, SLEUTEL, "https://www.krillo.nl/shopify")
zo("met de schakelaar aan wel", shop.laatste_variabelen["test"], True)
os.environ["SHOPIFY_BILLING_TEST"] = "nee"
zo("en 'nee' is ook uit", shopify_billing.testmodus(), False)
os.environ.pop("SHOPIFY_BILLING_TEST", None)

print("\n== als Shopify het weigert ==")
shop.klachten = [{"field": ["name"], "message": "Plan already exists"}]
uit = shopify_billing.start_abonnement(WINKEL, SLEUTEL, "https://www.krillo.nl/shopify")
zo("het mislukt netjes", uit["gelukt"], False)
zo("met de melding van Shopify", "already exists" in uit["fout"], True)
zo("en zonder link", uit.get("link"), None)
shop.klachten = []

zo("zonder terugkeeradres beginnen wij er niet aan",
   shopify_billing.start_abonnement(WINKEL, SLEUTEL, "")["gelukt"], False)

# ------------------------------------------------------------- opzeggen

print("\n== opzeggen ==")
shop.abonnementen = [{"id": "gid://1", "name": "Krillo monitoring", "status": "ACTIVE"}]
uit = shopify_billing.zeg_op(WINKEL, SLEUTEL, "gid://1")
zo("gelukt", uit["gelukt"], True)
zo("hij is weg", shopify_billing.huidig_abonnement(WINKEL, SLEUTEL)["actief"], False)
zo("zonder kenmerk zeggen wij niets op",
   shopify_billing.zeg_op(WINKEL, SLEUTEL, None)["gelukt"], False)

# ------------------------------------------------------------- de routes

print("\n== de routes ==")
import db
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

import app as krillo
krillo.shopify_billing._graphql = nep_graphql
client = krillo.app.test_client()

zo("zonder kaartje geen stand",
   client.get("/shopify/api/abonnement").status_code, 401)
zo("zonder kaartje niet abonneren",
   client.post("/shopify/api/abonneren").status_code, 401)
zo("zonder kaartje niet opzeggen",
   client.post("/shopify/api/opzeggen").status_code, 401)

db.bewaar_shopify_winkel(WINKEL, SLEUTEL, geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://testwinkel.nl",
                         email="eigenaar@testwinkel.nl")
krillo._shopify_uit_kop = lambda: (WINKEL, db.get_shopify_winkel(WINKEL))

shop.abonnementen = []
r = client.get("/shopify/api/abonnement")
zo("de stand komt door", r.status_code, 200)
zo("nog niet actief", r.get_json()["actief"], False)
zo("met de prijs erbij", r.get_json()["prijs"], "39.00")

r = client.post("/shopify/api/abonneren")
zo("abonneren geeft een link", r.status_code, 200)
zo("en die link is van Shopify",
   "myshopify.com" in r.get_json()["link"], True)

shop.abonnementen = [{"id": "gid://1", "name": "Krillo monitoring", "status": "ACTIVE"}]
r = client.post("/shopify/api/abonneren")
zo("een tweede abonnement wordt geweigerd", r.status_code, 409)
zo("met uitleg", "al een lopend" in r.get_json()["error"], True)

r = client.post("/shopify/api/opzeggen")
zo("opzeggen lukt", r.status_code, 200)
r = client.post("/shopify/api/opzeggen")
zo("twee keer opzeggen wordt gemeld", r.status_code, 400)

print("\n== de wekelijkse ronde neemt betalende Shopify-winkels mee ==")
shop.abonnementen = []
zo("zonder abonnement niet in de ronde", krillo._shopify_abonnees(), [])

shop.abonnementen = [{"id": "gid://1", "name": "Krillo monitoring", "status": "ACTIVE"}]
mee = krillo._shopify_abonnees()
zo("met abonnement wel in de ronde", len(mee), 1)
zo("met het gewone webadres", mee[0]["webshop_url"], "https://testwinkel.nl")
zo("en het mailadres van de winkel", mee[0]["email"], "eigenaar@testwinkel.nl")

db.shopify_verwijderd(WINKEL)
zo("een verwijderde app telt niet meer mee", krillo._shopify_abonnees(), [])

print("\n== de eerste drie wijzigingen zijn gratis, daarna niet ==")
# Dit is de grens waar de omzet aan hangt. Gaat hij lek, dan doet Krillo al het
# werk voor niets. Staat hij te streng, dan voelt niemand ooit het verschil en
# betaalt er ook niemand.
import shopify_werk
zo("de grens staat op drie", shopify_werk.GRATIS_WIJZIGINGEN, 3)

# De winkel opnieuw aanmelden: het blok hierboven heeft hem verwijderd om te
# toetsen dat een verwijderde app niet meer meetelt in de wekelijkse ronde.
db.bewaar_shopify_winkel(WINKEL, SLEUTEL, geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://testwinkel.nl",
                         email="eigenaar@testwinkel.nl")
shop.abonnementen = []
krillo._shopify_voorstellen[WINKEL] = {
    f"shopify:tekst:{i}": {"id": f"shopify:tekst:{i}", "soort": "tekst",
                           "wat": "Producttekst", "waar": f"Product {i}",
                           "nieuw": "Een nieuwe tekst", "nieuw_html": "<p>Een nieuwe tekst</p>",
                           "product_id": i}
    for i in range(1, 7)}

gezet = []


def nep_pas_toe(w, s, v, k):
    """Doet alsof het schrijven gelukt is, en legt de wijziging echt vast.

    Dat vastleggen moet, want de rem telt hoeveel er al in de winkel staan."""
    gezet.append(v["id"])
    db.bewaar_wijziging(webshop_url=k, taak_id=v["id"], wat=v["wat"],
                        waar=v["waar"], oude_waarde="", nieuwe_waarde=v["nieuw"])
    return {"gelukt": True, "id": v["id"]}


krillo.shopify_werk.pas_toe = nep_pas_toe

r = client.post("/shopify/api/toepassen",
                json={"ids": [f"shopify:tekst:{i}" for i in range(1, 7)]})
d = r.get_json()
zo("er gaan er precies drie in", len(d.get("gedaan") or []), 3)
zo("en drie worden tegengehouden", len(d["geblokkeerd"]), 3)
zo("het tegoed is op", d["gratis_over"], 0)
zo("er is echt maar drie keer geschreven", len(gezet), 3)

r = client.post("/shopify/api/toepassen", json={"ids": ["shopify:tekst:4"]})
zo("nog een poging levert niets op", len(r.get_json()["gedaan"]), 0)
zo("en schrijft ook niets", len(gezet), 3)

print("\n== met een abonnement mag alles ==")
shop.abonnementen = [{"id": "gid://1", "name": "Krillo monitoring", "status": "ACTIVE"}]
r = client.post("/shopify/api/toepassen",
                json={"ids": [f"shopify:tekst:{i}" for i in range(4, 7)]})
d = r.get_json()
zo("de rest gaat er alsnog in", len(d["gedaan"]), 3)
zo("niets tegengehouden", len(d["geblokkeerd"]), 0)
zo("en het scherm weet dat hij betaalt", d["betaalt"], True)
zo("er is nu zes keer geschreven", len(gezet), 6)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
