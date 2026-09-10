"""De hele keten van klik tot factuur, met een nagemaakte Mollie.

Dit is de test die ertoe doet. De losse stukken werken allang; de vraag is of
het label dat de bezoeker meebrengt echt aan de andere kant uit de webhook komt
en in de factuur belandt. Gaat dat ergens onderweg stuk, dan zie je dat nergens
aan een foutmelding, alleen aan een lege kolom over drie weken.
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


# Een nagemaakte Mollie die onthoudt wat hij binnenkreeg en dat teruggeeft
# zoals de echte doet: metadata komt ongewijzigd terug bij de webhook.
nep = types.ModuleType("payments")
nep.betalingen = {}
nep.AUDIT_PRICE = {"currency": "EUR", "value": "79.00"}
nep.MONITORING_PRICE = {"currency": "EUR", "value": "39.00"}


def _create_audit_payment(base_url, webshop_url, email, bedrijfsnaam=None, bron=None):
    pid = f"tr_audit_{len(nep.betalingen)}"
    nep.betalingen[pid] = {"type": "audit", "webshop_url": webshop_url, "email": email,
                           "bedrijfsnaam": bedrijfsnaam, "bron": bron}
    return {"checkout_url": "https://mollie.test/" + pid, "payment_id": pid}


def _create_monitoring_signup(base_url, email, webshop_url, bedrijfsnaam=None, bron=None):
    pid = f"tr_mon_{len(nep.betalingen)}"
    nep.betalingen[pid] = {"type": "monitoring_first_payment", "webshop_url": webshop_url,
                           "email": email, "bedrijfsnaam": bedrijfsnaam,
                           "customer_id": "cst_1", "bron": bron}
    return {"checkout_url": "https://mollie.test/" + pid, "payment_id": pid, "customer_id": "cst_1"}


def _get_payment_status(payment_id):
    md = nep.betalingen.get(payment_id)
    if md is None:
        return None
    return {"status": "paid", "is_paid": True, "metadata": md,
            "created_at": None, "bedrag": 79.00}


nep.create_audit_payment = _create_audit_payment
nep.create_monitoring_signup = _create_monitoring_signup
nep.get_payment_status = _get_payment_status
nep.create_subscription = lambda cid: {"subscription_id": "sub_1"}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {"ok": True}
sys.modules["payments"] = nep

import db
import app as krillo

# Niets echt scannen, niets echt mailen, niets echt schrijven met een AI.
krillo.run_scan = lambda url: {"error": "in de test niet gescand"}
krillo.emailing.send_factuur_email = lambda *a, **k: True

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

client = krillo.app.test_client()


def bestel(bron_in_body, extra_url="", verwijzer=None):
    body = {"url": "voorbeeldwinkel.nl", "email": "eigenaar@voorbeeldwinkel.nl",
            "bedrijfsnaam": "Voorbeeld BV", "voorwaarden_akkoord": True,
            "directe_uitvoering_akkoord": True}
    if bron_in_body is not None:
        body["herkomst"] = bron_in_body
    kop = {"Referer": verwijzer} if verwijzer else {}
    r = client.post("/api/checkout/audit" + extra_url, json=body, headers=kop)
    return r.get_json()


print("\n== het label uit de browser komt in de metadata van Mollie ==")
uit = bestel("webwinkelkeur")
zo("betaling aangemaakt", "payment_id" in uit, True)
zo("bron staat in de metadata", nep.betalingen[uit["payment_id"]]["bron"], "webwinkelkeur")

print("\n== rommel in het label wordt opgeruimd, niet doorgegeven ==")
uit = bestel("<script>alert(1)</script>" + "x" * 500)
bron = nep.betalingen[uit["payment_id"]]["bron"]
zo("geen haakjes meer", "<" in bron, False)
zo("niet langer dan zestig tekens", len(bron) <= 60, True)

print("\n== geen label in de body, dan kijkt de server zelf ==")
uit = bestel(None, extra_url="?utm_source=Becom")
zo("utm_source uit de link", nep.betalingen[uit["payment_id"]]["bron"], "becom")

uit = bestel(None, verwijzer="https://www.higherlevel.nl/forum/draadje")
zo("anders het domein van de vorige pagina",
   nep.betalingen[uit["payment_id"]]["bron"], "higherlevel.nl")

uit = bestel(None)
zo("en anders niets, geen verzonnen bron", nep.betalingen[uit["payment_id"]]["bron"], None)

print("\n== de webhook schrijft de bron in de factuur ==")
uit = bestel("webwinkelkeur")
pid = uit["payment_id"]
r = client.post("/webhooks/mollie", data={"id": pid})
zo("webhook geeft netjes antwoord", r.status_code, 200)


def wacht_op_factuur(payment_id, seconden=10):
    """De webhook doet het werk op een achtergronddraad, dus even wachten.

    Zonder dit is de test een wedloop: soms was de factuur er al, soms nog niet,
    en dan lijkt de code stuk terwijl alleen de test te vroeg keek."""
    import time
    c = db._get_connection()
    try:
        for _ in range(int(seconden * 10)):
            with c:
                with c.cursor() as cur:
                    cur.execute("SELECT bron, bedrag FROM facturen WHERE payment_id = %s",
                                (payment_id,))
                    gevonden = cur.fetchone()
            if gevonden:
                return gevonden
            time.sleep(0.1)
    finally:
        c.close()
    return None


rij = wacht_op_factuur(pid)
conn = db._get_connection()
zo("er staat een factuur", rij is not None, True)
zo("met de juiste bron", rij[0], "webwinkelkeur")

print("\n== een betaling van voor deze wijziging, zonder bron in de metadata ==")
nep.betalingen["tr_oud"] = {"type": "audit", "webshop_url": "https://oud.nl",
                            "email": "oud@shop.nl", "bedrijfsnaam": None}
krillo._verwerk_betaling("tr_oud", "https://www.krillo.nl")
rij = wacht_op_factuur("tr_oud")
zo("factuur is er gewoon", rij is not None, True)
zo("bron blijft leeg in plaats van een gok", rij[0] if rij else "geen factuur", None)

print("\n== hetzelfde voor monitoring ==")
r = client.post("/api/checkout/monitoring", json={
    "url": "voorbeeldwinkel.nl", "email": "eigenaar@voorbeeldwinkel.nl",
    "voorwaarden_akkoord": True, "herkomst": "becom"})
pid = r.get_json()["payment_id"]
zo("bron in de metadata", nep.betalingen[pid]["bron"], "becom")

print("\n== de beheerpagina laadt en toont de omzet per bron ==")
with conn:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO gratis_scans (webshop_url, score, gelukt, herkomst)
                       VALUES ('https://x.nl', 60, true, 'webwinkelkeur')""")
conn.close()
r = client.get("/admin/bezoekers?key=testsleutel")
zo("pagina laadt", r.status_code, 200)
pagina = r.get_data(as_text=True)
zo("de bron staat erop", "webwinkelkeur" in pagina, True)
zo("de omzet staat erop", "79.00" in pagina, True)

print("\n== zonder sleutel blijft de pagina dicht ==")
zo("geen sleutel", client.get("/admin/bezoekers").status_code, 404)
zo("verkeerde sleutel", client.get("/admin/bezoekers?key=fout").status_code, 404)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
