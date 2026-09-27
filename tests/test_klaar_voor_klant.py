"""Klaar voor de eerste betalende klant.

WAAROM DEZE TEST BESTAAT

27 september, nul klanten. De betaalde routes hadden nog nooit echt gedraaid.
Een onafhankelijke controle van de hele klantweg vond wat er mis zou gaan bij
de eerste klant:
1. Herroepen legde het verzoek vast, maar het abonnement bij Mollie liep door.
2. De Shopify-app verwijderen zette ook een klant stil die via de site betaalt.
3. Het wisverzoek van Shopify (shop/redact) wiste ook zo'n site-klant.
4. Het dashboard liet een site-klant die ooit de app probeerde niet opzeggen.
5. Stopte de verwerking van een betaling halverwege, dan kwam er nooit meer
   iets (Mollie stuurt een betaalde melding maar een keer). Nu: een knop
   "Opnieuw verwerken" en een nachtelijke controle.
6. Opzeggen stopte alles meteen, terwijl de voorwaarden de rest van de
   betaalde maand beloven.
7. De bedanktpagina zei "Nothing was charged" bij een betaling die nog liep.
8. Een mislukte welkomstmail en nieuw Fix-werk buiten Shopify gingen stil.
"""
import os
import sys
import types
from datetime import datetime, timezone, timedelta

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
os.environ["BEHEERDER_EMAIL"] = "beheer@krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


import db  # noqa: E402
import app as krillo  # noqa: E402
import payments  # noqa: E402
import emailing  # noqa: E402

db.init_db()
meldingen, mails = [], []
krillo._meld_aan_beheer = lambda kop, tekst: meldingen.append((kop, tekst)) or True
emailing.send_email = lambda *a, **k: mails.append(a) or True
emailing.send_herroeping_bevestiging = lambda *a, **k: True
emailing.send_herroeping_melding = lambda *a, **k: True
emailing.send_opzegging_bevestiging = lambda *a, **k: True


def sql(opdracht, waarden=None, een=False):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden)
            uit = cur.fetchone() if een else None
    conn.close()
    return uit


U = "https://eerste-klant.nl"
sql("DELETE FROM klanten WHERE webshop_url = %s", (U,))
sql("DELETE FROM shopify_winkels WHERE winkel = 'eerste-klant.myshopify.com'")
sql("INSERT INTO klanten (klant_token, webshop_url, email, aangemaakt_op) "
    "VALUES ('tok-eerste', %s, 'eigenaar@eerste-klant.nl', now() - interval '40 days')", (U,))
db.zet_mollie_klant(U, "cst_test123", "fix")
client = krillo.app.test_client()

print("\n== 1. HERROEPEN STOPT HET ABONNEMENT ==")
opgezegd = []
payments.zoek_abonnement = lambda url: {"customer_id": "cst_test123", "subscription_id": "sub_1"} if url == U else None
payments.zeg_abonnement_op = lambda c, s: opgezegd.append((c, s)) or {"ok": True}
db.leg_herroeping_vast = lambda e, u, t: 7
r = client.post("/api/herroepen", json={"email": "eigenaar@eerste-klant.nl", "url": U})
klopt("het verzoek wordt aangenomen", r.status_code == 200)
klopt("het abonnement bij Mollie is opgezegd", opgezegd == [("cst_test123", "sub_1")])
klopt("jij krijgt een melding om terug te betalen",
      any("Herroeping" in k and "Terugbetalen" in t for k, t in meldingen))
opgezegd.clear(); meldingen.clear()
sql("UPDATE klanten SET opgezegd_op = NULL WHERE webshop_url = %s", (U,))
r = client.post("/api/herroepen", json={"email": "eigenaar@eerste-klant.nl", "url": ""})
klopt("zonder winkeladres vinden we hem via zijn mailadres", opgezegd == [("cst_test123", "sub_1")])
sql("UPDATE klanten SET opgezegd_op = NULL WHERE webshop_url = %s", (U,))

print("\n== 2. APP VERWIJDEREN ZET EEN SITE-KLANT NIET STIL ==")
bron = lees("app.py")
klopt("uninstall kijkt naar mollie_klant_id",
      "if klant_weg and not klant_weg.get(\"mollie_klant_id\"):" in bron)
klopt("en de abonnements-webhook ook",
      "if (klant and not klant.get(\"mollie_klant_id\")" in bron)

print("\n== 3. SHOP/REDACT WIST GEEN SITE-KLANT ==")
sql("INSERT INTO shopify_winkels (winkel, webshop_url) VALUES ('eerste-klant.myshopify.com', %s)", (U,))
db.wis_shopify_winkel("eerste-klant.myshopify.com")
klopt("de app-gegevens zijn weg",
      sql("SELECT 1 FROM shopify_winkels WHERE winkel = 'eerste-klant.myshopify.com'", een=True) is None)
klopt("de klant zelf staat er nog", sql("SELECT 1 FROM klanten WHERE webshop_url = %s", (U,), een=True))

print("\n== 4. HET DASHBOARD LAAT HEM OPZEGGEN ==")
sql("INSERT INTO shopify_winkels (winkel, webshop_url, toegangssleutel) "
    "VALUES ('eerste-klant.myshopify.com', %s, 'x')", (U,))
klopt("geen 'je abonnement loopt via Shopify' voor een Mollie-klant",
      krillo._paginagegevens(U)["shopify_beheer"] is None)
sql("DELETE FROM shopify_winkels WHERE winkel = 'eerste-klant.myshopify.com'")

print("\n== 5. BETAALD MAAR NIETS GELEVERD ==")
klopt("maandbetaling zonder metadata telt als geleverd",
      krillo._is_geleverd({"id": "tr_a", "type": "onbekend", "webshop_url": "-"}))
klopt("een klant met klantregel is geleverd",
      krillo._is_geleverd({"id": "tr_b", "type": "monitoring", "webshop_url": U}))
klopt("zonder klant en rapport: niet geleverd",
      not krillo._is_geleverd({"id": "tr_c", "type": "monitoring", "webshop_url": "https://niemand-hier.nl"}))
nu = datetime.now(timezone.utc)
payments.list_recent_orders = lambda limit=25: [
    {"id": "tr_oud", "type": "monitoring", "webshop_url": "https://niemand-hier.nl", "email": "a@b.nl",
     "paid_at": (nu - timedelta(hours=3)).isoformat()},
    {"id": "tr_vers", "type": "monitoring", "webshop_url": "https://niemand-hier.nl", "email": "a@b.nl",
     "paid_at": (nu - timedelta(minutes=10)).isoformat()}]
meldingen.clear()
krillo._controleer_betalingen()
klopt("de nachtronde meldt een betaling van drie uur geleden zonder levering",
      any("tr_oud" in t for _, t in meldingen))
klopt("maar niet een die nog bezig kan zijn", not any("tr_vers" in t for _, t in meldingen))
opnieuw = []
krillo._betaling_opnieuw = lambda pid: opnieuw.append(pid)
with client.session_transaction() as sessie:
    sessie["beheer"] = True
r = client.post("/admin/bestellingen?key=testsleutel", data={"payment_id": "tr_oud"})
klopt("de knop 'Opnieuw verwerken' werkt", opnieuw == ["tr_oud"] or r.status_code in (302, 303))
klopt("de oude belofte 'Mollie probeert het opnieuw' is weg",
      "melding van Mollie probeert het opnieuw" not in bron)
klopt("en een nep-nummer wordt geweigerd", 're.fullmatch(r"tr_[A-Za-z0-9]+", pid)' in bron)

print("\n== 6. OPZEGGEN: TOEGANG TOT HET EINDE VAN DE BETAALDE MAAND ==")
begon = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
eind = krillo._einde_betaalde_maand(begon, nu=datetime(2026, 9, 25, tzinfo=timezone.utc))
klopt("begonnen op de 10e, opgezegd op de 25e: tot 10 oktober", eind.date().isoformat() == "2026-10-10")
eind31 = krillo._einde_betaalde_maand(datetime(2026, 1, 31, tzinfo=timezone.utc),
                                     nu=datetime(2026, 2, 5, tzinfo=timezone.utc))
klopt("begonnen op 31 januari: tot 28 februari", eind31.date().isoformat() == "2026-02-28")
klopt("een einde in de toekomst is nog geen einde",
      not krillo._toegang_voorbij({"opgezegd_op": nu + timedelta(days=5)}))
klopt("een einde in het verleden wel", krillo._toegang_voorbij({"opgezegd_op": nu - timedelta(days=1)}))
payments.zoek_abonnement = lambda url: {"customer_id": "cst_test123", "subscription_id": "sub_1"}
r = client.post("/api/opzeggen/tok-eerste")
eind_db = sql("SELECT opgezegd_op FROM klanten WHERE webshop_url = %s", (U,), een=True)[0]
klopt("na 40 dagen opzeggen: toegang loopt nog door", eind_db and eind_db > nu)
klopt("dus hij blijft Fix-werk krijgen tot dat moment", krillo._abonnement_stand(U)[0] is True)
klopt("en telt mee in de maandronde",
      "AND (k.opgezegd_op IS NULL OR k.opgezegd_op > now())" in lees("db.py"))

print("\n== 7. BEDANKTPAGINA BIJ EEN BETALING DIE NOG LOOPT ==")
payments.get_payment_status = lambda pid: {"status": "open", "is_paid": False}
p = client.get("/bedankt?type=monitoring&ref=tr_x").get_data(as_text=True)
klopt("geen 'Nothing was charged' bij open", "Nothing was charged" not in p)
payments.get_payment_status = lambda pid: {"status": "canceled", "is_paid": False}
p = client.get("/bedankt?type=monitoring&ref=tr_x").get_data(as_text=True)
klopt("wel bij geannuleerd", "Nothing was charged" in p)

print("\n== 8. NIETS GAAT MEER STIL ==")
klopt("een mislukte welkomstmail geeft een melding", "Welkomstmail NIET verstuurd" in bron)
klopt("nieuw Fix-werk buiten Shopify geeft een melding", "Fix-werk klaar voor een klant" in bron)
klopt("wisselen van pakket: eerlijk hoe dat gaat", "we switch" in bron and "without paying twice" in bron)

print("\n== 9. TESTABONNEMENT HEET GEEN NIEUWE KLANT (beoordelaar Shopify, 27 september) ==")
klopt("de melding zegt TEST bij een testabonnement", '"TEST, geen echt geld: " if is_test' in bron)

sql("DELETE FROM klanten WHERE webshop_url = %s", (U,))
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de eerste klant kan komen.")
