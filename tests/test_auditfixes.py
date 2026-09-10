"""De reparaties uit de drie audits.

Elke controle hieronder hoort bij een fout die er echt in zat. De omschrijving
zegt daarom niet alleen wat er moet gebeuren, maar ook wat er misging toen het
nog niet zo was. Zonder dat weet niemand over een half jaar waarom deze regel
er staat, en dan wordt hij weggehaald.
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["CRON_KEY"] = "cronsleutel"
os.environ["SHOPIFY_API_KEY"] = "testklant"
os.environ["SHOPIFY_API_SECRET"] = "testgeheim"
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
import scan_engine
import beoordeling
import app as krillo

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()
client = krillo.app.test_client()

# ---------------------------------------------------------------------------
print("\n== scannen van onze eigen server is dichtgezet ==")
# Was: /api/scan en /api/voorproef haalden elk adres op dat iemand intypte, dus
# ook http://127.0.0.1:5000/admin/... vanaf de binnenkant van het netwerk.
for adres in ("http://127.0.0.1:5000/admin", "http://localhost", "https://192.168.1.5",
              "http://169.254.169.254/latest/meta-data", "file:///etc/passwd",
              "https://metadata.google.internal", "https://[::1]/", "https://server"):
    zo(f"geweigerd: {adres[:40]}", scan_engine.is_intern_adres(adres), True)
for adres in ("https://winkel.nl", "https://www.bol.com/nl", "http://mamazoet.be"):
    zo(f"toegestaan: {adres}", scan_engine.is_intern_adres(adres), False)
zo("run_scan weigert het ook zelf",
   "error" in scan_engine.run_scan("http://127.0.0.1:5000/admin"), True)
r = client.post("/api/scan", json={"url": "http://127.0.0.1:5000/admin"})
zo("en de route geeft geen uitslag", r.status_code >= 400 or "error" in (r.get_json() or {}), True)

# ---------------------------------------------------------------------------
print("\n== de winkelnaam wordt niet meer geraden ==")
# Was: de omschrijving werd op " is " gesplitst. Bij "Deze webshop is
# gespecialiseerd in servies" werd de naam "Deze webshop", en met die naam telde
# elke pagina waar die twee woorden staan als vermelding.
for naam in ("Deze webshop", "deze winkel", "de webshop voor servies", "Onze webshop",
             "Webshop voor honden", "Bo", "", "   ", "x" * 70):
    zo(f"geweigerd: {naam[:28]!r}", scan_engine.bruikbare_winkelnaam(naam), None)
for naam in ("Dille & Kamille", "Het Kaashuis", "De Bijenkorf", "fonQ", "MamaZoet"):
    zo(f"toegestaan: {naam}", scan_engine.bruikbare_winkelnaam(naam), naam)

print("\n== een concurrent wordt niet meer voor de eigen winkel aangezien ==")
# Was: "kern in plat or plat in kern". De klant tuin.nl kreeg daardoor
# Tuincentrum Overvecht als zichzelf aangemerkt, en zag zijn grootste
# concurrent dus nergens meer.
gevallen = [
    ("https://tuin.nl", "Tuincentrum Overvecht", False),
    ("https://tuin.nl", "Tuin.nl", True),
    ("https://sport.nl", "Sportshop Jansen", False),
    ("https://koffie.nl", "Koffiebranderij De Zon", False),
    ("https://bol.com", "Bol.com", True),
    ("https://bol.com", "Bolder Sport", False),
    ("https://dille-kamille.nl", "Dille & Kamille", True),
    ("https://dille-kamille.nl", "Dille en Kamille", True),
    ("https://mamazoet.be", "MamaZoet", True),
    ("https://plantje.nl", "Plantje.nl", True),
    ("https://plantje.nl", "Plantenwinkel", False),
]
for url, naam, verwacht in gevallen:
    zo(f"{url.replace('https://', ''):20} tegen {naam}",
       scan_engine.is_eigen_winkel(url, naam), verwacht)

# ---------------------------------------------------------------------------
print("\n== concurrenten worden niet meer per schrijfwijze dubbel geteld ==")
# Was: "fonQ" en "FonQ" werden twee losse regels met elk 1 keer genoemd, in
# plaats van een regel met 1. De aanbeveling hing dan aan maar een van de twee.
beoordelingen = [
    {"vraag": "waar koop ik een lamp", "winkel_kon_genoemd": True,
     "winkels": [{"naam": "fonQ"}], "aanbevolen_winkels": ["fonQ"], "model": "gpt"},
    {"vraag": "waar koop ik een lamp", "winkel_kon_genoemd": True,
     "winkels": [{"naam": "FonQ"}], "aanbevolen_winkels": [], "model": "gemini"},
    {"vraag": "welke webshop verkoopt vazen", "winkel_kon_genoemd": True,
     "winkels": [{"naam": "FonQ"}], "aanbevolen_winkels": [], "model": "gpt"},
]
beeld = beoordeling.klantbeeld("https://mijnwinkel.nl", beoordelingen)
namen = [c["naam"].lower() for c in beeld["concurrenten"]]
zo("er is precies een regel voor fonq", namen.count("fonq"), 1)
regel = [c for c in beeld["concurrenten"] if c["naam"].lower() == "fonq"][0]
zo("genoemd bij twee vragen, niet bij drie antwoorden", regel["genoemd"], 2)
zo("de aanbeveling hangt aan diezelfde regel", regel["aanbevolen"], 1)

# ---------------------------------------------------------------------------
print("\n== de klantpagina van een ander is niet over te nemen ==")
# Was: wie bij een bestelling de URL van een bestaande klant invulde, kreeg
# diens token in zijn eigen mailbox, zag al zijn rapporten en kon zijn
# abonnement opzeggen.
WINKEL = "https://echteklant.nl"
token = db.get_or_create_klant(WINKEL, "echte@klant.nl")
zo("de echte klant krijgt een token", bool(token), True)
zo("hij is niet te raden", len(token) >= 24, True)
zo("dezelfde klant krijgt hetzelfde token",
   db.get_or_create_klant(WINKEL, "echte@klant.nl"), token)
zo("hoofdletters in het adres maken niet uit",
   db.get_or_create_klant(WINKEL, "Echte@Klant.nl"), token)
zo("iemand anders krijgt NIETS",
   db.get_or_create_klant(WINKEL, "indringer@ergensanders.nl"), None)
zo("en het token van de echte klant is niet veranderd",
   db.get_or_create_klant(WINKEL, "echte@klant.nl"), token)

# ---------------------------------------------------------------------------
print("\n== uitslagen van anderen zijn niet meer op te tellen ==")
# Was: /api/zichtbaarheidstest/<rijnummer>. Wie zelf nummer 812 kreeg kon
# 1 tot en met 811 opvragen en zag van elke bezoeker de winkel en de uitslag.
a = db.start_zichtbaarheidstest("https://eerste.nl", "een@test.nl")
b = db.start_zichtbaarheidstest("https://tweede.nl", "twee@test.nl")
zo("er komt een kenmerk uit", bool(a["kenmerk"]), True)
zo("het is niet te raden", len(a["kenmerk"]) >= 20, True)
zo("twee tests krijgen verschillende kenmerken", a["kenmerk"] != b["kenmerk"], True)
zo("een rijnummer geeft niets meer",
   client.get(f"/api/zichtbaarheidstest/{a['id']}").status_code, 404)
zo("het kenmerk werkt wel",
   client.get(f"/api/zichtbaarheidstest/{a['kenmerk']}").status_code, 200)
zo("en toont de juiste winkel",
   client.get(f"/api/zichtbaarheidstest/{a['kenmerk']}").get_json()["webshop_url"],
   "https://eerste.nl")
zo("het mailadres blijft erbuiten",
   "een@test.nl" in client.get(f"/api/zichtbaarheidstest/{a['kenmerk']}").get_data(as_text=True),
   False)
zo("een verzonnen kenmerk geeft niets",
   client.get("/api/zichtbaarheidstest/zelfverzonnenkenmerk123").status_code, 404)

# ---------------------------------------------------------------------------
print("\n== betaald maar niet geleverd kan opnieuw geprobeerd worden ==")
# Was: de claim werd gezet voor de levering. Mislukte de scan, dan stopte elke
# herhaling van Mollie daarop. Geld binnen, nooit een rapport, geen melding.
zo("de eerste claim lukt", db.claim_payment("tr_test1"), True)
zo("een tweede keer niet", db.claim_payment("tr_test1"), False)
zo("de claim terugdraaien lukt", db.ontclaim_payment("tr_test1"), True)
zo("en daarna kan het weer", db.claim_payment("tr_test1"), True)
zo("een onbekende betaling terugdraaien is geen fout",
   db.ontclaim_payment("tr_bestaatniet"), False)

meldingen = []
krillo._meld_aan_beheer = lambda kop, bericht: meldingen.append(kop) or True
krillo._levering_mislukt("tr_test1", "https://winkel.nl", "a@b.nl", "audit", "geblokkeerd")
zo("de betaling staat weer open", db.claim_payment("tr_test1"), True)
zo("en er is een melding uitgegaan", meldingen, ["Betaald maar niet geleverd"])

pogingen = []


def nep_scan(url):
    pogingen.append(url)
    return {"error": "geblokkeerd"} if len(pogingen) < 3 else {"score": 60, "checks": []}


krillo.run_scan = nep_scan
uit = krillo._scan_met_herkansing("https://traag.nl", pogingen=3)
zo("een tijdelijke storing wordt herkanst", len(pogingen), 3)
zo("en de scan lukt alsnog", uit.get("score"), 60)

# ---------------------------------------------------------------------------
print("\n== geen twee keer dezelfde weekmail op een dag ==")
# Was: _is_aan_de_beurt keek alleen naar de dag van de week. Vuurde de cron
# twee keer, dan kreeg elke klant twee mails en draaide de meting dubbel.
nu = datetime.now(timezone.utc)
db.save_report("monitoring", "https://weekklant.nl", "week@klant.nl", 60, [], None, None)
zo("vandaag al gemeten, dus niet nog een keer",
   krillo._is_aan_de_beurt("https://weekklant.nl", nu), False)
zo("met alles=True wel", krillo._is_aan_de_beurt("https://weekklant.nl", nu, alles=True), True)
zo("een winkel die nog nooit gemeten is, is wel aan de beurt",
   krillo._is_aan_de_beurt("https://nooitgemeten.nl", nu), True)

# ---------------------------------------------------------------------------
print("\n== de beheersleutel ==")
zo("de juiste sleutel klopt", krillo._sleutel_klopt("testsleutel", "testsleutel"), True)
zo("een verkeerde niet", krillo._sleutel_klopt("testsleutex", "testsleutel"), False)
zo("een lege niet", krillo._sleutel_klopt("", "testsleutel"), False)
zo("None niet", krillo._sleutel_klopt(None, "testsleutel"), False)
zo("een te korte niet", krillo._sleutel_klopt("test", "testsleutel"), False)
for pad in ("/admin/benadering", "/admin/onderzoeksmail", "/admin/kosten", "/admin/demo"):
    zo(f"{pad} is dicht zonder sleutel", client.get(pad).status_code, 404)
    zo(f"{pad} is dicht met de verkeerde", client.get(f"{pad}?key=fout").status_code, 404)
zo("de cron is dicht met de verkeerde sleutel",
   client.get("/api/cron/benadering?key=fout").status_code, 404)

# ---------------------------------------------------------------------------
print("\n== de Shopify-app mag alleen door Shopify ingebed worden ==")
# Was: er ging geen enkele kop mee. Shopify eist dit, en het is de enige
# bescherming tegen een vreemde site die ons scherm in een onzichtbaar venster
# zet en de winkelier daarin laat klikken.
r = client.get("/shopify?shop=testwinkel.myshopify.com")
kop = r.headers.get("Content-Security-Policy") or ""
zo("de kop staat erop", "frame-ancestors" in kop, True)
zo("met de winkel zelf erin", "https://testwinkel.myshopify.com" in kop, True)
zo("en het beheerscherm van Shopify", "https://admin.shopify.com" in kop, True)
zo("bij een verzonnen winkel geen eigen adres in de kop",
   "kwaadaardig" in (client.get("/shopify?shop=kwaadaardig.nl")
                     .headers.get("Content-Security-Policy") or ""), False)
zo("op de gewone site staat de kop niet",
   "frame-ancestors" in (client.get("/").headers.get("Content-Security-Policy") or ""), False)

# ---------------------------------------------------------------------------
print("\n== de proefweek krijg je een keer ==")
# Was: opzeggen en meteen weer starten gaf telkens zeven nieuwe gratis dagen.
db.bewaar_shopify_winkel("proefwinkel.myshopify.com", "shpat_x",
                         geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://proefwinkel.nl")
rij = db.get_shopify_winkel("proefwinkel.myshopify.com")
zo("nog geen proef gehad", rij.get("proef_gehad_op"), None)
zo("vastleggen lukt", db.markeer_proef_gehad("proefwinkel.myshopify.com"), True)
rij = db.get_shopify_winkel("proefwinkel.myshopify.com")
zo("nu wel", rij.get("proef_gehad_op") is not None, True)
eerst = rij["proef_gehad_op"]
db.markeer_proef_gehad("proefwinkel.myshopify.com")
zo("de datum verspringt niet bij een tweede keer",
   db.get_shopify_winkel("proefwinkel.myshopify.com")["proef_gehad_op"], eerst)

import shopify_billing
gestuurd = {}
shopify_billing._graphql = lambda w, s, v, var=None: (
    gestuurd.update(var or {}) or
    {"gelukt": True, "gegevens": {"appSubscriptionCreate": {
        "userErrors": [], "confirmationUrl": "https://x.myshopify.com/c",
        "appSubscription": {"id": "gid://1", "status": "PENDING"}}}})
shopify_billing.start_abonnement("proefwinkel.myshopify.com", "shpat_x", "https://k.nl/t")
zo("standaard zeven proefdagen", gestuurd["proefdagen"], 7)
shopify_billing.start_abonnement("proefwinkel.myshopify.com", "shpat_x", "https://k.nl/t",
                                 proefdagen=0)
zo("en nul als de proef al gebruikt is", gestuurd["proefdagen"], 0)

# ---------------------------------------------------------------------------
print("\n== bij een wisverzoek gaat de benaderlijst ook weg ==")
# Was: het gevonden contactadres van de winkel en onze notities bleven staan.
db.voeg_benadering_toe("https://wiswinkel.nl", naam="Wis", land="NL")
db.zet_benadering("https://wiswinkel.nl", stand="adres", email="info@wiswinkel.nl")
db.bewaar_shopify_winkel("wiswinkel.myshopify.com", "shpat_y",
                         geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://wiswinkel.nl")
zo("hij staat er nu", bool(db.get_benadering("https://wiswinkel.nl")), True)
db.wis_shopify_winkel("wiswinkel.myshopify.com")
zo("na het wissen niet meer", db.get_benadering("https://wiswinkel.nl"), None)

# ---------------------------------------------------------------------------
print("\n== een afmelding blokkeert alle post, via welke weg dan ook ==")
db.get_benchmark_token("https://afmeldwinkel.nl")
db.meld_benadering_af("https://afmeldwinkel.nl")
zo("hij staat als afgemeld", db.is_afgemeld("https://afmeldwinkel.nl"), True)
gelukt, reden = krillo._stuur_onderzoeksmail("https://afmeldwinkel.nl", "info@afmeldwinkel.nl")
zo("er gaat niets heen", gelukt, False)
zo("met de reden erbij", "afgemeld" in (reden or ""), True)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
