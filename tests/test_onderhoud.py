"""Het onderhoud: indelen, opschonen en meten zonder dat iemand kijkt.

WAAROM DIT DE BELANGRIJKSTE TEST WORDT ALS KRILLO GROEIT

Vandaag draait Krillo op knoppen, en dat werkt bij negenhonderd winkels in twee
landen. Bij tienduizend winkels in acht landen komen er elke dag winkels bij en
verlopen er elke dag metingen. Dan moet het vanzelf gaan.

Iets dat vanzelf gaat en geld uitgeeft, is precies het soort machine dat je 's
nachts failliet laat draaien als er een rem ontbreekt. Wat hier bewaakt wordt
is dus niet of het onderhoud werkt, maar of het op tijd STOPT.

- Hoogstens EEN categorie per ronde. Een ronde die alles doet wat er ligt, doet
  op een dag met driehonderd nieuwe winkels ineens driehonderd euro.
- Voor elke stap wordt de kostenrem gevraagd. Zit die dicht, dan stopt de ronde
  en gaat morgen verder waar hij gebleven was.
- Twee rondes tegelijk kan niet. De cron kan dubbel afgaan, en dan zou dezelfde
  categorie twee keer gemeten en dus twee keer betaald worden.
- Een categorie die net gemeten is, wordt niet opnieuw gemeten.
- De ronde hangt nooit aan een verzoek.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["CRON_KEY"] = "cronsleutel"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db          # noqa: E402
import kosten      # noqa: E402
import onderhoud   # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


db.init_db()
CAT = "onderhoud-test"
WINKELS = [f"https://onderhoudwinkel{n}.nl" for n in range(1, 13)]


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (WINKELS,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    conn.close()


opruimen()
for url in WINKELS:
    db.voeg_benadering_toe(url, naam=url, land="NL", branche="test")
    db.zet_categorie(url, CAT)

print("\n== welke categorieen aan de beurt zijn ==")
aan_de_beurt = db.categorieen_om_te_meten(minimum=10, ouder_dan_dagen=30)
namen = [r["categorie"] for r in aan_de_beurt]
klopt("een categorie die nooit gemeten is staat erbij", CAT in namen)
rij = next(r for r in aan_de_beurt if r["categorie"] == CAT)
zo("met het juiste aantal winkels", rij["aantal"], 12)
klopt("en zonder meetdatum", rij["laatst_gemeten"] is None)

print("\n== een te kleine categorie doet niet mee ==")
klein = db.categorieen_om_te_meten(minimum=20, ouder_dan_dagen=30)
klopt("twaalf winkels is te weinig bij een minimum van twintig",
      CAT not in [r["categorie"] for r in klein])

print("\n== een net gemeten categorie wordt met rust gelaten ==")
ronde = db.start_categorie_ronde(CAT, 30, 12)
db.bewaar_categorie_uitkomsten(
    ronde, CAT, [{"webshop_url": WINKELS[0], "positie": 1, "genoemd": 1,
                  "aanbevolen": 1, "beste_positie": 1}], 19)
opnieuw = [r["categorie"] for r in db.categorieen_om_te_meten(10, 30)]
klopt("vers gemeten, dus niet aan de beurt", CAT not in opnieuw)
verlopen = [r["categorie"] for r in db.categorieen_om_te_meten(10, 0)]
klopt("maar met een vervaltermijn van nul wel", CAT in verlopen)

print("\n== hoogstens een categorie per ronde ==")
echte_meting = onderhoud.categoriemeting.meet_categorie
gemeten = []
onderhoud.categoriemeting.meet_categorie = lambda slug, **k: (
    gemeten.append(slug) or {"winkels": 12, "telbaar": 19})
try:
    onderhoud.OPNIEUW_METEN_NA_DAGEN = 0
    verslag = onderhoud.stap_meten()
    zo("er is er precies een gemeten", len(verslag["gemeten"]), 1)
    klopt("en de wachtrij was langer", verslag["wachtrij"] >= 1)

    gemeten.clear()
    verslag = onderhoud.stap_meten(hoeveel=0)
    zo("met nul mag er niets gemeten worden", len(verslag["gemeten"]), 0)
    zo("en is er dus ook niets aangeroepen", len(gemeten), 0)

    print("\n== een meting die niet meer in de dagpot past begint niet ==")
    # Dit is een andere fout dan een dichte rem. De rem zegt "je mag nog", maar
    # er is nog maar vijftig cent over en een meting kost twee euro vijftig.
    # Halverwege afgekapt worden betekent: wel betaald, geen ranglijst.
    echte_ruimte = kosten.ruimte_vandaag
    kosten.ruimte_vandaag = lambda: {"besteed": 1.80, "grens": 2.00, "over": 0.20,
                                     "past_een_categorie": False, "onbekend": False}
    onderhoud.kosten.ruimte_vandaag = kosten.ruimte_vandaag
    try:
        gemeten.clear()
        verslag = onderhoud.stap_meten()
        zo("er is niets gemeten", len(verslag["gemeten"]), 0)
        zo("en ook niets aangeroepen", len(gemeten), 0)
        klopt("er staat bij hoeveel er over is",
              "0.20 euro" in verslag.get("gestopt_door", ""))
    finally:
        kosten.ruimte_vandaag = echte_ruimte
        onderhoud.kosten.ruimte_vandaag = echte_ruimte

    print("\n== bij onbekende kosten wordt er niet gegokt ==")
    kosten.ruimte_vandaag = lambda: {"besteed": None, "grens": 2.00, "over": 0.0,
                                     "past_een_categorie": False, "onbekend": True}
    onderhoud.kosten.ruimte_vandaag = kosten.ruimte_vandaag
    try:
        gemeten.clear()
        zo("niet weten is niet beginnen", len(onderhoud.stap_meten()["gemeten"]), 0)
    finally:
        kosten.ruimte_vandaag = echte_ruimte
        onderhoud.kosten.ruimte_vandaag = echte_ruimte

    print("\n== een dichte kostenrem stopt de meting ==")
    echte_rem = kosten.mag_doorgaan
    kosten.mag_doorgaan = lambda *a, **k: {"mag": False, "reden": "dagpot op"}
    onderhoud.kosten.mag_doorgaan = kosten.mag_doorgaan
    try:
        gemeten.clear()
        verslag = onderhoud.stap_meten()
        zo("er is niets gemeten", len(verslag["gemeten"]), 0)
        zo("en er staat bij waarom", verslag.get("gestopt_door"), "dagpot op")
        zo("indelen gaat ook niet door",
           onderhoud.stap_indelen().get("overgeslagen"), "kostenrem")
    finally:
        kosten.mag_doorgaan = echte_rem
        onderhoud.kosten.mag_doorgaan = echte_rem
finally:
    onderhoud.categoriemeting.meet_categorie = echte_meting
    onderhoud.OPNIEUW_METEN_NA_DAGEN = 30

print("\n== nieuwe winkels worden vanzelf opgeschoond ==")
NIEUW = ["https://verswinkel.nl", "https://verswinkel.be", "Vers Zonder Adres"]


def nieuw_opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (NIEUW,))
    conn.close()


nieuw_opruimen()
for url in NIEUW:
    db.voeg_benadering_toe(url, naam=url, land="NL", branche="test")

wacht = [w["webshop_url"] for w in db.winkels_zonder_opschoning()]
klopt("de nieuwe winkels staan in de wachtrij", all(u in wacht for u in NIEUW))

# Geen modelaanroep: alleen het gratis adreswerk controleren.
echte_merken = onderhoud.opschonen.merken_in
onderhoud.opschonen.merken_in = lambda groep: {}
try:
    verslag = onderhoud.stap_opschonen()
    klopt("er zijn nieuwe winkels gezien", verslag["nieuw"] >= 3)
    klopt("de regel zonder adres is eruit gehaald", verslag["zonder_adres"] >= 1)
    klopt("en de .be is onder de .nl gehangen", verslag["samengevoegd"] >= 1)
finally:
    onderhoud.opschonen.merken_in = echte_merken

rijen = {r["webshop_url"]: r for r in db.alle_benaderingen_kaal()}
zo("verswinkel.be hoort bij verswinkel.nl",
   rijen["https://verswinkel.be"]["hoort_bij"], "https://verswinkel.nl")
zo("en de naamregel staat als geen-adres",
   rijen["Vers Zonder Adres"]["soort"], "geen-adres")

daarna = [w["webshop_url"] for w in db.winkels_zonder_opschoning()]
klopt("ze staan niet meer in de wachtrij",
      not any(u in daarna for u in NIEUW))

print("\n== twee rondes tegelijk kan niet ==")
onderhoud._stand["bezig"] = True
klopt("een tweede start wordt geweigerd", onderhoud.start_ronde() is False)
onderhoud._stand["bezig"] = False

print("\n== de cron-ingang hangt het werk niet aan het verzoek ==")
bron = lees("app.py")
i = bron.find("def cron_onderhoud(")
klopt("de cron-ingang bestaat", i > 0)
blok = bron[i:i + 1400]
einde = blok.find("\n@app.route")
blok = blok[:einde] if einde > 0 else blok
klopt("er wordt om een sleutel gevraagd", "CRON_KEY" in blok)
zo("en gestart via start_ronde", blok.count("start_ronde"), 1)
klopt("ronde() wordt niet rechtstreeks aangeroepen", "onderhoud.ronde(" not in blok)

print("\n== zonder sleutel gebeurt er niets ==")
import app as krillo  # noqa: E402

krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()
zo("zonder sleutel een 404", klant.get("/api/cron/onderhoud").status_code, 404)
zo("met een verkeerde sleutel ook",
   klant.get("/api/cron/onderhoud?key=fout").status_code, 404)

print("\n== de beheerpagina laat de wachtrij zien ==")
antwoord = klant.get("/admin/opschonen?key=testsleutel", follow_redirects=True)
zo("de pagina laadt", antwoord.status_code, 200)
tekst = antwoord.get_data(as_text=True)
klopt("met het onderhoud erop", "Het onderhoud" in tekst)
klopt("en de wachtrij erin", "in de wachtrij" in tekst)

opruimen()
nieuw_opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
