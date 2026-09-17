"""Een ranglijst verbeteren zonder opnieuw te meten, en zwakke vragen eruit.

WAAR DIT VANDAAN KOMT (17 september)

Twee dingen vielen op in de eerste echte ranglijsten.

1. In servies stonden cookinglife.be en cookinglife.nl als twee regels met
   precies dezelfde cijfers. Dat is een keten met twee adressen. Het opschonen
   weet dat inmiddels, maar de ranglijst was al gemaakt, en de enige manier om
   hem te verbeteren was opnieuw meten: veertig cent en een half uur, voor
   precies dezelfde antwoorden.

2. Bij Speelgoed telden 13 van de 30 vragen mee. De andere zeventien vroegen om
   een product of een merk, daar komt geen webshop in voor, en ze zijn dus wel
   betaald en leverden niets op.

WAT DIT BEWAAKT

- Herberekenen kost NUL modelaanroepen. Dit is de hele reden dat de knop mag
  bestaan; zou hij stiekem toch iets vragen of lezen, dan is het een dure knop
  die zich voordoet als een gratis knop.
- Herberekenen geeft dezelfde uitkomst als meten zou geven: ketens samen,
  merken eruit.
- Een regel die na het herberekenen niet meer in de lijst hoort, VERDWIJNT ook
  echt. Alleen overschrijven zou hem met zijn oude cijfers laten staan.
- Herberekenen verzet de eindtijd van de ronde niet. Anders zou een gratis
  herberekening de ronde in het kostenoverzicht duurder laten lijken.
- Snoeien zet alleen vragen uit die bij TWEE of meer antwoorden niets
  opleverden. Op een enkele meting afkeuren is afkeuren op toeval.
- De knoppen sturen door naar een GET, zodat verversen niets herhaalt.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import categoriemeting  # noqa: E402
import db               # noqa: E402
import metingen         # noqa: E402

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

CAT = "herbereken-test"
HOOFD = "https://ketenwinkel.nl"
ZUSJE = "https://ketenwinkel.be"
ANDER = "https://anderewinkel.nl"
MERK = "https://eenmerk.nl"
ALLE = [HOOFD, ZUSJE, ANDER, MERK]


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (ALLE,))
        cur.execute("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_vragen WHERE categorie = %s", (CAT,))
    conn.close()


opruimen()
for url in ALLE:
    db.voeg_benadering_toe(url, naam=url, land="NL", branche="test")
    db.zet_categorie(url, CAT)

VRAAG_GOED = "waar koop ik online een pan"
VRAAG_OOK_GOED = "welke webshop verkoopt goede messen"
VRAAG_SLECHT = "wat is het beste merk pannen"

db.bewaar_categorie_vragen(CAT, [
    {"vraag": VRAAG_GOED, "intentie": "winkel"},
    {"vraag": VRAAG_OOK_GOED, "intentie": "winkel"},
    {"vraag": VRAAG_SLECHT, "intentie": "alternatief"},
])

ronde = db.start_categorie_ronde(CAT, 3, 4)


def antwoord(vraag, model, kon, winkels, aanbevolen=()):
    db.bewaar_categorie_antwoord(
        ronde, CAT, vraag, model, f"antwoordtekst voor {vraag}",
        {"winkel_kon_genoemd": kon,
         "winkels": [{"naam": n, "positie": p} for p, n in enumerate(winkels, 1)],
         "aanbevolen": list(aanbevolen)})


# De keten wordt onder BEIDE adressen genoemd bij dezelfde vraag. Dat hoort een
# keer te tellen en niet twee keer.
antwoord(VRAAG_GOED, "model-a", True,
         ["ketenwinkel.nl", "ketenwinkel.be", "anderewinkel.nl", "eenmerk.nl"],
         ["ketenwinkel.nl"])
antwoord(VRAAG_GOED, "model-b", True, ["anderewinkel.nl"])
antwoord(VRAAG_OOK_GOED, "model-a", True, ["ketenwinkel.be"])
antwoord(VRAAG_OOK_GOED, "model-b", True, ["ketenwinkel.nl", "anderewinkel.nl"])
# De merkvraag: geen enkele winkel kon genoemd worden, twee keer.
antwoord(VRAAG_SLECHT, "model-a", False, [])
antwoord(VRAAG_SLECHT, "model-b", False, [])

# Een oude ranglijst zoals hij eruitzag VOOR het opschonen: de twee adressen van
# de keten als losse regels, en het merk erin.
db.bewaar_categorie_uitkomsten(ronde, CAT, [
    {"webshop_url": HOOFD, "positie": 1, "genoemd": 2, "aanbevolen": 1, "beste_positie": 1},
    {"webshop_url": ZUSJE, "positie": 2, "genoemd": 2, "aanbevolen": 0, "beste_positie": 2},
    {"webshop_url": ANDER, "positie": 3, "genoemd": 2, "aanbevolen": 0, "beste_positie": 1},
    {"webshop_url": MERK, "positie": 4, "genoemd": 1, "aanbevolen": 0, "beste_positie": 4},
], 2)

voor = db.laatste_ranglijst(CAT)
zo("de oude lijst heeft vier regels", len(voor["rijen"]), 4)

conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("SELECT afgerond_op FROM categorie_rondes WHERE id = %s", (ronde,))
    afgerond_voor = cur.fetchone()[0]
conn.close()

# Nu weet de database wat het opschonen geleerd heeft.
db.zet_hoort_bij(ZUSJE, HOOFD)
db.zet_soort(MERK, "merk")

print("\n== herberekenen roept geen enkel model aan ==")
aanroepen = []
echt_vragen = metingen.stel_een_vraag
echt_lezen = categoriemeting._lees_met


def verboden(*a, **k):
    aanroepen.append(a)
    raise AssertionError("Herberekenen mag geen model aanroepen.")


metingen.stel_een_vraag = verboden
categoriemeting.metingen.stel_een_vraag = verboden
categoriemeting._lees_met = verboden
try:
    uit = categoriemeting.herbereken_ranglijst(CAT)
finally:
    metingen.stel_een_vraag = echt_vragen
    categoriemeting.metingen.stel_een_vraag = echt_vragen
    categoriemeting._lees_met = echt_lezen

zo("er is geen enkele aanroep gedaan", len(aanroepen), 0)
zo("en er kwam gewoon een uitkomst uit", uit.get("fout"), None)
zo("op dezelfde ronde", uit["ronde"], ronde)
zo("uit zes bewaarde antwoorden", uit["antwoorden"], 6)
zo("twee vragen telden mee", uit["telbaar"], 2)

print("\n== de keten staat nog een keer op de lijst, het merk is eruit ==")
na = db.laatste_ranglijst(CAT)
urls = [r["webshop_url"] for r in na["rijen"]]
zo("er zijn nog twee regels over", len(na["rijen"]), 2)
klopt("het hoofdadres staat erop", HOOFD in urls)
klopt("het tweede adres van dezelfde keten niet meer", ZUSJE not in urls)
klopt("het merk ook niet meer", MERK not in urls)
klopt("de andere winkel staat er gewoon nog op", ANDER in urls)

keten = next(r for r in na["rijen"] if r["webshop_url"] == HOOFD)
zo("de keten is bij beide vragen genoemd", keten["genoemd"], 2)
zo("en een keer aanbevolen", keten["aanbevolen"], 1)
zo("de keten staat eerste, want aanbevolen weegt zwaarder", keten["positie"], 1)

print("\n== de eindtijd van de ronde blijft staan ==")
conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("SELECT afgerond_op FROM categorie_rondes WHERE id = %s", (ronde,))
    afgerond_na = cur.fetchone()[0]
conn.close()
zo("herberekenen verzet hem niet", afgerond_na, afgerond_voor)

print("\n== dezelfde telling als een verse meting zou geven ==")
winkels = db.winkels_in_categorie_met_kinderen(CAT)
telling, telbaar = categoriemeting.tel_uit_antwoorden(
    db.antwoorden_van_ronde(ronde), winkels)
rangen = categoriemeting.maak_ranglijst(telling, winkels)
zo("evenveel regels", len(rangen), len(na["rijen"]))
zo("dezelfde volgorde", [r["webshop_url"] for r in rangen], urls)

print("\n== welke soort vragen iets oplevert ==")
per_soort = {r["intentie"]: r for r in db.telbaarheid_per_intentie(CAT)}
zo("de winkelvragen telden allemaal mee", per_soort["winkel"]["telden_mee"], 4)
zo("en de merkvraag geen enkele keer", per_soort["alternatief"]["telden_mee"], 0)
zo("het aandeel klopt", per_soort["alternatief"]["aandeel"], 0)

print("\n== snoeien haalt alleen de kansloze vragen eruit ==")
zwak = [z["vraag"] for z in db.vragen_die_nooit_meetelden(CAT)]
zo("er is er precies een kansloos", len(zwak), 1)
zo("en dat is de merkvraag", zwak[0], VRAAG_SLECHT)

uit = categoriemeting.snoei_vragen(CAT)
zo("er is er een uitgezet", uit["uitgezet"], 1)
actief = [v["vraag"] for v in db.categorie_vragen(CAT)]
klopt("de merkvraag wordt niet meer gesteld", VRAAG_SLECHT not in actief)
klopt("de goede vragen staan er nog", VRAAG_GOED in actief and VRAAG_OOK_GOED in actief)
zo("maar bewaard blijft hij wel", len(db.categorie_vragen(CAT, alleen_actief=False)), 3)

print("\n== een vraag met een enkele misser wordt niet afgekeurd ==")
EEN_KEER = "waar vind ik een braadpan"
db.bewaar_categorie_vragen(CAT, [{"vraag": EEN_KEER, "intentie": "winkel"}])
antwoord(EEN_KEER, "model-a", False, [])
zwak = [z["vraag"] for z in db.vragen_die_nooit_meetelden(CAT)]
klopt("een enkel antwoord is te weinig om iets te vinden", EEN_KEER not in zwak)
antwoord(EEN_KEER, "model-b", False, [])
zwak = [z["vraag"] for z in db.vragen_die_nooit_meetelden(CAT)]
klopt("bij twee missers wel", EEN_KEER in zwak)

print("\n== elke soort koopvraag vraagt om een WINKEL ==")
# De meting van Speelgoed op 17 september, per soort vraag, aandeel dat meetelde:
#   winkel 100%, praktisch 100%, prijs 40%, alternatief 10%, algemeen 0%,
#   doelgroep 0%.
# De twee die het goed deden zijn precies de twee die letterlijk om een webshop
# vroegen. De rest vroeg om een product, en daar antwoordt een assistent met
# productnamen. Alle zes omschrijvingen vragen nu om een winkel; deze test houdt
# dat zo, want dit is het soort regel dat bij de volgende herschrijving zo weer
# sneuvelt.
for naam, gewicht, uitleg in categoriemeting.KOOPINTENTIES():
    laag = uitleg.lower()
    klopt(f"de soort '{naam}' vraagt om een winkel",
          "webshop" in laag or "winkel" in laag)
    klopt(f"en '{naam}' heeft een gewicht", gewicht >= 1)

print("\n== de verdeling telt precies op ==")
for aantal in (30, 12, 6, 3, 1):
    verdeling = categoriemeting._verdeling(aantal)
    zo(f"{aantal} vragen worden er ook {aantal}",
       sum(h for _, _, h in verdeling), aantal)
    klopt("geen enkele soort krijgt er nul",
          all(h >= 1 for _, _, h in verdeling))
dertig = dict((n, h) for n, _, h in categoriemeting._verdeling(30))
klopt("winkel krijgt de meeste vragen, want die telt altijd mee",
      dertig["winkel"] == max(dertig.values()))

print("\n== zonder meting valt er niets te herberekenen ==")
leeg = categoriemeting.herbereken_ranglijst("bestaat-echt-niet")
klopt("dat zegt hij gewoon", "fout" in leeg)

print("\n== de knoppen sturen door naar een GET ==")
import app as krillo  # noqa: E402
krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()
antwoordje = klant.post("/admin/ranglijst?key=testsleutel",
                        data={"categorie": CAT, "actie": "herbereken"})
klopt("herberekenen stuurt door", antwoordje.status_code in (301, 302))
klopt("met een melding erin", "m=herberekend" in antwoordje.headers.get("Location", ""))
antwoordje = klant.post("/admin/ranglijst?key=testsleutel",
                        data={"categorie": CAT, "actie": "snoeien"})
klopt("snoeien stuurt ook door", antwoordje.status_code in (301, 302))

print("\n== de pagina zegt dat het gratis is ==")
tekst = klant.get(f"/admin/ranglijst?key=testsleutel&categorie={CAT}").get_data(as_text=True)
klopt("bij de herberekenknop staat gratis", "Gratis" in tekst)
klopt("en de knop staat er", "Ranglijst opnieuw uitrekenen" in tekst)

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
