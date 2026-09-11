"""De keten van "wij doen het": betalen, op de werklijst, toegang vragen, opleveren.

Wat hier fout kan gaan zonder foutmelding is het ergste wat er in dit product
kan gebeuren: iemand betaalt 149 euro en zijn opdracht staat nergens. Daarom
test deze test vooral dat de opdracht op de werklijst belandt, ook als de mail
mislukt, en dat een dubbele melding van Mollie geen dubbele opdracht oplevert.
"""
import os
import sys
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
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
nep.betalingen = {}
nep.AUDIT_PRICE = {"currency": "EUR", "value": "79.00"}
nep.MONITORING_PRICE = {"currency": "EUR", "value": "39.00"}
nep.UITVOERING_PRICE = {"currency": "EUR", "value": "149.00"}


def _uitvoering(base_url, webshop_url, email, bedrijfsnaam=None, bron=None, platform=None):
    pid = f"tr_uit_{len(nep.betalingen)}"
    nep.betalingen[pid] = {"type": "uitvoering", "webshop_url": webshop_url, "email": email,
                           "bedrijfsnaam": bedrijfsnaam, "bron": bron, "platform": platform}
    return {"checkout_url": "https://mollie.test/" + pid, "payment_id": pid}


def _status(payment_id):
    md = nep.betalingen.get(payment_id)
    if md is None:
        return None
    return {"status": "paid", "is_paid": True, "metadata": md, "created_at": None,
            "bedrag": 149.00}


nep.create_uitvoering_payment = _uitvoering
nep.create_audit_payment = lambda *a, **k: {"error": "niet in deze test"}
nep.create_monitoring_signup = lambda *a, **k: {"error": "niet in deze test"}
nep.get_payment_status = _status
nep.create_subscription = lambda cid: {}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {"ok": True}
sys.modules["payments"] = nep

import db
import app as krillo

verstuurd = []
krillo.run_scan = lambda url: {"error": "in de test niet gescand"}
krillo.emailing.send_factuur_email = lambda *a, **k: True
krillo.emailing.send_uitvoering_welkom = lambda to, url, platform=None, mon=None: (
    verstuurd.append({"to": to, "url": url, "platform": platform}) or True)

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

client = krillo.app.test_client()

print("\n== de kassa weigert wat hij moet weigeren ==")
r = client.post("/api/checkout/uitvoering", json={"url": "winkel.nl"})
zo("zonder e-mail geweigerd", r.status_code, 400)
r = client.post("/api/checkout/uitvoering", json={"url": "winkel.nl", "email": "a@b.nl"})
zo("zonder akkoord voorwaarden geweigerd", r.status_code, 400)
r = client.post("/api/checkout/uitvoering", json={"url": "winkel.nl", "email": "a@b.nl",
                                                  "voorwaarden_akkoord": True})
zo("zonder akkoord direct beginnen geweigerd", r.status_code, 400)

print("\n== het platform uit een eerdere scan gaat mee ==")
db.zet_platform("https://winkel.nl", "WooCommerce")
r = client.post("/api/checkout/uitvoering", json={
    "url": "winkel.nl", "email": "eigenaar@winkel.nl", "bedrijfsnaam": "Winkel BV",
    "voorwaarden_akkoord": True, "directe_uitvoering_akkoord": True,
    "herkomst": "webwinkelkeur"})
uit = r.get_json()
zo("betaling aangemaakt", "payment_id" in uit, True)
pid = uit["payment_id"]
zo("platform in de metadata", nep.betalingen[pid]["platform"], "WooCommerce")
zo("bron in de metadata", nep.betalingen[pid]["bron"], "webwinkelkeur")
zo("adres genormaliseerd", nep.betalingen[pid]["webshop_url"], "https://winkel.nl")

print("\n== toestemming is vastgelegd voordat er betaald wordt ==")
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT type, directe_uitvoering_akkoord FROM toestemmingen WHERE payment_id = %s", (pid,))
        rij = cur.fetchone()
zo("toestemming staat er", rij is not None, True)
zo("met het juiste soort", rij[0], "uitvoering")
zo("en het akkoord om direct te beginnen", rij[1], True)

print("\n== na de betaling staat de opdracht op de werklijst ==")
krillo._verwerk_betaling(pid, "https://www.krillo.nl")
lijst = db.get_uitvoeringen()
zo("een opdracht op de lijst", len(lijst), 1)
zo("met de juiste winkel", lijst[0]["webshop_url"], "https://winkel.nl")
zo("beginstand is wacht op toegang", lijst[0]["stand"], "wacht_op_toegang")
zo("platform bewaard", lijst[0]["platform"], "WooCommerce")
zo("de toegangsmail is verstuurd", len(verstuurd), 1)
zo("met de platformuitleg erbij", verstuurd[0]["platform"], "WooCommerce")

with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT omschrijving, bedrag, bron FROM facturen WHERE payment_id = %s", (pid,))
        f = cur.fetchone()
zo("er is een factuur", f is not None, True)
zo("met de juiste omschrijving", "verbeteringen uit" in (f[0] or ""), True)
zo("het juiste bedrag", float(f[1]), 149.00)
zo("en de bron", f[2], "webwinkelkeur")

print("\n== Mollie meldt dezelfde betaling nog eens ==")
krillo._verwerk_betaling(pid, "https://www.krillo.nl")
zo("nog steeds één opdracht", len(db.get_uitvoeringen()), 1)
zo("en geen tweede mail", len(verstuurd), 1)

print("\n== de standen op de werklijst ==")
uid = db.get_uitvoeringen()[0]["id"]
zo("onbekende stand wordt geweigerd", db.zet_uitvoering_stand(uid, "bezigg"), False)
zo("stand staat nog op wacht", db.get_uitvoeringen()[0]["stand"], "wacht_op_toegang")
zo("bezig zetten lukt", db.zet_uitvoering_stand(uid, "bezig"), True)
u = db.get_uitvoeringen()[0]
zo("toegangsdatum is vastgelegd", u["toegang_op"] is not None, True)
zo("nog niet opgeleverd", u["opgeleverd_op"], None)
zo("opleveren lukt", db.zet_uitvoering_stand(uid, "opgeleverd", "FAQ en alt-teksten gedaan"), True)
u = db.get_uitvoeringen()[0]
zo("opleverdatum is vastgelegd", u["opgeleverd_op"] is not None, True)
zo("notitie bewaard", u["notitie"], "FAQ en alt-teksten gedaan")
zo("een lege notitie wist de oude niet", (db.zet_uitvoering_stand(uid, "opgeleverd", None) and
                                          db.get_uitvoeringen()[0]["notitie"]),
   "FAQ en alt-teksten gedaan")
zo("een onbekend id verandert niets", db.zet_uitvoering_stand(999999, "bezig"), False)

print("\n== zonder platform gaat er algemene uitleg mee, geen gok ==")
r = client.post("/api/checkout/uitvoering", json={
    "url": "onbekendplatform.nl", "email": "b@b.nl",
    "voorwaarden_akkoord": True, "directe_uitvoering_akkoord": True})
pid2 = r.get_json()["payment_id"]
zo("geen platform in de metadata", nep.betalingen[pid2]["platform"], None)
krillo._verwerk_betaling(pid2, "https://www.krillo.nl")
zo("tweede opdracht staat op de lijst", len(db.get_uitvoeringen()), 2)
zo("mail zonder platform", verstuurd[-1]["platform"], None)

print("\n== de beheerpagina ==")
r = client.get("/admin/uitvoeringen?key=testsleutel", follow_redirects=True)
zo("laadt", r.status_code, 200)
pagina = r.get_data(as_text=True)
zo("de wachtende opdracht staat erop", "onbekendplatform.nl" in pagina, True)
zo("de opgeleverde ook", "winkel.nl" in pagina, True)
# Sinds de beheerpagina's achter een inlogscherm zitten is 302 (doorsturen naar
# /admin/inloggen) het goede antwoord, en geen 404 meer. En let op: een client
# die eerder MET sleutel binnenkwam blijft ingelogd, dus voor de dichte kant
# hoort een VERSE bezoeker gebruikt te worden.
zo("zonder sleutel dicht",
   krillo.app.test_client().get("/admin/uitvoeringen").status_code, 302)

r = client.post("/admin/uitvoeringen?key=testsleutel",
                data={"id": str(uid), "stand": "bezig", "notitie": "toch nog iets"})
zo("stand aanpassen via de pagina", r.status_code, 200)
zo("de stand is echt veranderd", db.get_uitvoeringen(  )[0]["stand"] if
   db.get_uitvoeringen()[0]["id"] == uid else
   [x for x in db.get_uitvoeringen() if x["id"] == uid][0]["stand"], "bezig")

print("\n== de klantpagina toont de juiste stand ==")
zo("nieuwste opdracht wordt gekozen",
   krillo._laatste_uitvoering("https://winkel.nl")["id"], uid)
db.zet_uitvoering_stand(uid, "afgebroken")
zo("een afgebroken opdracht laten we weg",
   krillo._laatste_uitvoering("https://winkel.nl"), None)
zo("een winkel zonder opdracht geeft niets",
   krillo._laatste_uitvoering("https://bestaatniet.nl"), None)

print("\n== de bedankpagina per soort ==")
for soort, moet in [("uitvoering", "toegang"), ("audit", "audit"), ("monitoring", "meting")]:
    tekst = client.get(f"/bedankt?type={soort}").get_data(as_text=True)
    zo(f"bedankt voor {soort}", moet in tekst, True)

conn.close()
print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
