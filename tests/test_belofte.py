"""Kloppen de beloftes op de prijskaart van de Shopify-app?

Op die kaart staat wat iemand voor 39 dollar per maand koopt. Elke regel
daarvan hoort in de code te staan, en niet alleen op het scherm. Dit bestand
loopt ze een voor een langs.

De regel die hier eerder NIET waar was: "nieuwe producten worden opgepakt en
ingevuld". Er draaide niets dat uit zichzelf aanpaste, er gebeurde alleen iets
als iemand zelf op de knop drukte. Iemand die daarvoor betaalde kreeg het dus
niet. Deze test bestaat om dat nooit meer stil te laten gebeuren.
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["SHOPIFY_API_KEY"] = "testklant"
os.environ["SHOPIFY_API_SECRET"] = "testgeheim"
os.environ["SHOPIFY_APP_HANDLE"] = "krillo"
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
import emailing
import shopify_werk
import shopify_billing
import app as krillo

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

WINKEL = "testwinkel.myshopify.com"
SLEUTEL = "shpat_test"
KLANT = "https://testwinkel.nl"

db.bewaar_shopify_winkel(WINKEL, SLEUTEL, geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url=KLANT,
                         email="eigenaar@testwinkel.nl", naam="Testwinkel")

verstuurd = []
emailing.send_email = lambda to, onderwerp, html, koppen=None: (
    verstuurd.append({"to": to, "onderwerp": onderwerp, "html": html}) or True)

gezet = []


def nep_voorstellen(winkel, sleutel, markt=None):
    return {"gebreken": {}, "fouten": [],
            "aantallen": {"zonder_alt": 0, "dunne_tekst": 4, "faq_ontbreekt": False,
                          "producten_bekeken": 12, "nog_te_gaan": 0},
            "voorstellen": [
                {"id": f"shopify:tekst:{i}", "soort": "tekst", "wat": "Product description",
                 "waar": f"New product {i}", "nieuw": f"Beschrijving voor product {i}",
                 "nieuw_html": f"<p>Beschrijving voor product {i}</p>", "product_id": i}
                for i in range(1, 5)]}


def nep_pas_toe(winkel, sleutel, voorstel, klant_url):
    gezet.append(voorstel["id"])
    db.bewaar_wijziging(webshop_url=klant_url, taak_id=voorstel["id"],
                        wat=voorstel["wat"], waar=voorstel["waar"],
                        oude_waarde="", nieuwe_waarde=voorstel["nieuw"])
    return {"gelukt": True, "id": voorstel["id"]}


shopify_werk.maak_voorstellen = nep_voorstellen
shopify_werk.pas_toe = nep_pas_toe

# ---------------------------------------------------------------------------
print("\n== de belofte: nieuwe producten worden uit onszelf ingevuld ==")
gedaan = krillo._shopify_automatisch_aanvullen(WINKEL, "https://www.krillo.nl")
zo("er is echt aangevuld", len(gedaan or []), 4)
zo("en het is echt weggeschreven", len(gezet), 4)
zo("het staat in het overzicht van wijzigingen",
   len([w for w in db.get_wijzigingen(KLANT)
        if (w.get("taak_id") or "").startswith("shopify:")]), 4)

print("\n== en hij hoort er bericht van te krijgen ==")
zo("er is een mail verstuurd", len(verstuurd), 1)
zo("naar de eigenaar", verstuurd[0]["to"], "eigenaar@testwinkel.nl")
h = verstuurd[0]["html"]
zo("met wat er veranderd is erin", "New product 1" in h, True)
zo("en met de nieuwe tekst erbij", "Beschrijving voor product 1" in h, True)
zo("en hoe je het terugdraait", "terugzetten" in h.lower() or "undo" in h.lower(), True)
zo("en dat je het uit kunt zetten", "uitzetten" in h.lower() or "switch this off" in h.lower(),
   True)

print("\n== niet twee keer in dezelfde week ==")
# Draait de cron door een storing twee keer, dan zou hetzelfde werk dubbel
# gedaan worden. Dat kost twee keer geld bij het model voor niets.
gezet.clear()
verstuurd.clear()
nogmaals = krillo._shopify_automatisch_aanvullen(WINKEL, "https://www.krillo.nl")
zo("er gebeurt niets", nogmaals, None)
zo("en er wordt niets geschreven", len(gezet), 0)
zo("en er gaat geen tweede mail uit", len(verstuurd), 0)

print("\n== de schakelaar zet het echt uit ==")
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("UPDATE shopify_winkels SET automatisch_op = %s WHERE winkel = %s",
                    (datetime.now(timezone.utc) - timedelta(days=8), WINKEL))
conn.close()
zo("standaard staat hij aan", db.get_shopify_winkel(WINKEL)["automatisch"], True)
zo("uitzetten lukt", db.zet_shopify_automatisch(WINKEL, False), True)
zo("en dat is bewaard", db.get_shopify_winkel(WINKEL)["automatisch"], False)

gezet.clear()
zo("er gebeurt nu niets", krillo._shopify_automatisch_aanvullen(WINKEL, "https://k.nl"), None)
zo("en er wordt niets geschreven", len(gezet), 0)

db.zet_shopify_automatisch(WINKEL, True)
zo("weer aanzetten lukt ook", db.get_shopify_winkel(WINKEL)["automatisch"], True)

print("\n== de schakelaar via de app ==")
client = krillo.app.test_client()
zo("zonder kaartje niet", client.get("/shopify/api/automatisch").status_code, 401)
krillo._shopify_uit_kop = lambda: (WINKEL, db.get_shopify_winkel(WINKEL))
zo("met kaartje wel", client.get("/shopify/api/automatisch").get_json()["aan"], True)
zo("en uitzetten werkt",
   client.post("/shopify/api/automatisch", json={"aan": False}).get_json()["aan"], False)
zo("het is ook echt bewaard", db.get_shopify_winkel(WINKEL)["automatisch"], False)
client.post("/shopify/api/automatisch", json={"aan": True})

print("\n== een winkel zonder abonnement zit niet in de wekelijkse ronde ==")
nep_graphql_leeg = lambda w, s, v, var=None: {
    "gelukt": True, "gegevens": {"currentAppInstallation": {"activeSubscriptions": []}}}
shopify_billing._graphql = nep_graphql_leeg
zo("niet meegenomen", krillo._shopify_abonnees(), [])

shopify_billing._graphql = lambda w, s, v, var=None: {
    "gelukt": True, "gegevens": {"currentAppInstallation": {"activeSubscriptions": [
        {"id": "gid://1", "name": "Krillo monitoring", "status": "ACTIVE"}]}}}
mee = krillo._shopify_abonnees()
zo("met abonnement wel", len(mee), 1)
zo("met het winkeladres erbij zodat de ronde kan aanvullen",
   mee[0].get("winkel"), WINKEL)
zo("en het echte mailadres", mee[0]["email"], "eigenaar@testwinkel.nl")

print("\n== zonder mailadres gaat er geen post naar een verzonnen adres ==")
# Hier stond eerder shopify@<winkel>. Dat ziet eruit als "we hebben hem bericht"
# terwijl de mail nergens aankomt, en op het scherm staat dat hij een
# waarschuwing krijgt als er iets verandert.
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("UPDATE shopify_winkels SET email = NULL WHERE winkel = %s", (WINKEL,))
conn.close()
zo("hij valt uit de ronde", krillo._shopify_abonnees(), [])

print("\n== de labels volgen de taal van de winkel ==")
zo("nederlands", shopify_werk._label({"is_nederlands": True}, "tekst"), "Producttekst")
zo("engels", shopify_werk._label({"is_nederlands": False}, "tekst"), "Product description")
zo("onbekend wordt nederlands", shopify_werk._label(None, "tekst"), "Producttekst")
zo("ook de foto", shopify_werk._label({"is_nederlands": False}, "alt"),
   "Description on a product image")
zo("en de pagina", shopify_werk._label({"is_nederlands": False}, "faq_waar"),
   "Online Store, Pages")

print("\n== de mail in het engels ==")
verstuurd.clear()
emailing.send_shopify_bijgewerkt(
    "a@b.nl", "https://shop.com",
    [{"wat": "Product description", "waar": "Blue jacket", "nieuw": "A warm jacket."}],
    "https://admin.shopify.com/store/x/apps/krillo", taal="en")
h = verstuurd[0]["html"]
zo("is engels", "filled in" in h, True)
zo("zonder gedachtestreepjes", "—" in h, False)
zo("zonder nederlandse woorden", "veranderd" in h, False)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
