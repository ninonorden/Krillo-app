"""Nameting, waarschuwing bij daling, en de rem op het aantal berichten.

WAAROM DEZE TEST STRENG IS

Een mail naar een echte klant kun je niet terughalen. Alles wat hier misgaat
gaat mis in iemands inbox, en de klant die drie mails in een week krijgt zet ze
uit. Daarna ziet hij ook de mail niet meer die er wel toe doet.

WAT ER TOT VANDAAG NIET WAAR WAS

Op de site staat "Proof it worked: four weeks later we measure again" en "a
warning when you drop". Het eerste bestond niet, het tweede keek naar de oude
meting per winkel in plaats van naar de positie in de index. Beide beloftes
staan in het pakket van 149 euro, dus ze horen te kloppen voordat de nieuwe
site live gaat.

WAT DEZE TEST BEWAAKT

- Een nameting komt tussen vier en tien weken na een oplevering, en daarna
  nooit meer voor diezelfde oplevering.
- Een daling onder de drempel is ruis en levert geen bericht op.
- Er gaat nooit een tweede bericht uit binnen de rustperiode.
- Dezelfde meetronde kan nooit twee mails opleveren, ook niet als de code twee
  keer langskomt.
- De beheerpagina verstuurt NIETS. Alleen de nachtronde doet dat.
- Een daling wordt niet weggemoffeld: het staat er gewoon, met wat wij eraan
  gaan doen.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import db          # noqa: E402
import meldingen   # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


def dagen_terug(n):
    return datetime.now(timezone.utc) - timedelta(days=n)


db.init_db()

print("\n== de keuze: welk bericht hoort erbij ==")
basis = {"positie": 14, "vorige_positie": 14, "van": 34, "genoemd": 3,
         "telbaar": 13, "aanbevolen": 0, "opgeleverd_op": None}


def met(**extra):
    k = dict(basis)
    k.update(extra)
    return k


zo("zonder positie gaat er niets uit",
   meldingen.kies_bericht(met(positie=None))["soort"], "geen")

zo("gelijk gebleven is een gewoon maandbericht",
   meldingen.kies_bericht(met())["soort"], "maand")

zo("gestegen is ook gewoon een maandbericht",
   meldingen.kies_bericht(met(positie=10, vorige_positie=14))["soort"], "maand")

print("\n== de drempel: kleine bewegingen zijn ruis ==")
zo("twee plaatsen zakken is geen nieuws",
   meldingen.kies_bericht(met(positie=16, vorige_positie=14))["soort"], "maand")
zo("drie plaatsen zakken wel",
   meldingen.kies_bericht(met(positie=17, vorige_positie=14))["soort"], "daling")
zo("en acht plaatsen zeker",
   meldingen.kies_bericht(met(positie=22, vorige_positie=14))["soort"], "daling")

print("\n== de rustperiode ==")
pas = {"soort": "maand", "verstuurd_op": dagen_terug(3)}
zo("drie dagen na een bericht gaat er niets uit",
   meldingen.kies_bericht(met(), laatste=pas)["soort"], "geen")
zo("ook niet bij een flinke daling",
   meldingen.kies_bericht(met(positie=25, vorige_positie=14), laatste=pas)["soort"],
   "geen")
lang = {"soort": "maand", "verstuurd_op": dagen_terug(30)}
zo("dertig dagen later wel",
   meldingen.kies_bericht(met(positie=25, vorige_positie=14), laatste=lang)["soort"],
   "daling")

print("\n== de nameting ==")
zo("een week na oplevering is te vroeg",
   meldingen.kies_bericht(met(opgeleverd_op=dagen_terug(7)))["soort"], "maand")
zo("vier weken erna is het moment",
   meldingen.kies_bericht(met(opgeleverd_op=dagen_terug(28)))["soort"], "nameting")
zo("een half jaar later is het geen nameting meer",
   meldingen.kies_bericht(met(opgeleverd_op=dagen_terug(180)))["soort"], "maand")
zo("een nameting die al gestuurd is komt niet nog eens",
   meldingen.kies_bericht(met(opgeleverd_op=dagen_terug(28)),
                          nameting_gedaan=True)["soort"], "maand")
zo("de nameting gaat voor op de rustperiode",
   meldingen.kies_bericht(met(opgeleverd_op=dagen_terug(28)), laatste=pas)["soort"],
   "nameting")
zo("en voor op een daling",
   meldingen.kies_bericht(met(positie=25, vorige_positie=14,
                              opgeleverd_op=dagen_terug(30)))["soort"], "nameting")

print("\n== de teksten ==")
keuze = meldingen.kies_bericht(met(positie=17, vorige_positie=14))
t = meldingen.tekst(met(positie=17, vorige_positie=14), keuze, "Speelgoed")
klopt("bij een daling staat er hoeveel plaatsen", "3 plaatsen gezakt" in t)
klopt("en wat wij eraan doen", "oplossingen" in t.lower())
klopt("de positie staat erin", "plaats 17 van de 34" in t)
klopt("geen uitroepteken", "!" not in t)

keuze_n = meldingen.kies_bericht(met(opgeleverd_op=dagen_terug(28)))
tn = meldingen.tekst(met(), keuze_n, "Speelgoed")
klopt("de nameting noemt dezelfde vragen", "dezelfde vragen" in tn)

en = meldingen.tekst(met(positie=17, vorige_positie=14), keuze, "Toys", taal="en")
klopt("de Engelse tekst is echt Engels", "dropped" in en and "plaats" not in en)
klopt("het onderwerp verschilt per soort",
      meldingen.onderwerp(keuze, "Speelgoed") != meldingen.onderwerp(keuze_n, "Speelgoed"))

print("\n== een adres, een taal: het maandbericht is Engels (sinds 21 sep) ==")
zo("een .nl winkel krijgt Engels", meldingen._taal_van("https://winkel.nl"), "en")
zo("een .be winkel ook", meldingen._taal_van("https://winkel.be"), "en")
zo("een .com winkel krijgt Engels", meldingen._taal_van("https://shop.com"), "en")

# ---------------------------------------------------------------------------
# Met database: de rem die er echt toe doet
# ---------------------------------------------------------------------------
CAT = "melding-test"
WINKEL = "https://meldingwinkel.nl"
ANDER = "https://meldingtwee.nl"


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM berichten WHERE webshop_url = ANY(%s)", ([WINKEL, ANDER],))
        cur.execute("DELETE FROM klanten WHERE webshop_url = ANY(%s)", ([WINKEL, ANDER],))
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", ([WINKEL, ANDER],))
        cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    conn.close()


opruimen()
for url in (WINKEL, ANDER):
    db.voeg_benadering_toe(url, naam=url, land="NL", branche="test")
    db.zet_categorie(url, CAT)
db.get_or_create_klant(WINKEL, "klant@example.com")

vorige = db.start_categorie_ronde(CAT, 30, 2)
db.bewaar_categorie_uitkomsten(vorige, CAT, [
    {"webshop_url": WINKEL, "positie": 4, "genoemd": 6, "aanbevolen": 1, "beste_positie": 2},
    {"webshop_url": ANDER, "positie": 5, "genoemd": 5, "aanbevolen": 0, "beste_positie": 3},
], 20)
nu = db.start_categorie_ronde(CAT, 30, 2)
db.bewaar_categorie_uitkomsten(nu, CAT, [
    {"webshop_url": WINKEL, "positie": 12, "genoemd": 2, "aanbevolen": 0, "beste_positie": 7},
    {"webshop_url": ANDER, "positie": 5, "genoemd": 5, "aanbevolen": 0, "beste_positie": 3},
], 20)

print("\n== alleen betalende klanten krijgen bericht ==")
rijen = db.klanten_in_ronde(nu)
zo("er staat een klant in deze ronde", len(rijen), 1)
zo("en dat is de winkel met een abonnement", rijen[0]["webshop_url"], WINKEL)
zo("met zijn positie van nu", rijen[0]["positie"], 12)
zo("en die van de vorige ronde", rijen[0]["vorige_positie"], 4)

print("\n== de droogloop verstuurt niets en legt niets vast ==")
verstuurd = []
import emailing  # noqa: E402
echt = emailing.send_vermeldingen_update
emailing.send_vermeldingen_update = lambda *a, **k: verstuurd.append(a) or True
meldingen.emailing = emailing
try:
    droog = meldingen.na_meting(nu, CAT, verstuur=False)
    zo("hij ziet de klant", droog["klanten"], 1)
    zo("en zou een daling sturen", droog["per_soort"].get("daling"), 1)
    zo("maar er is niets verstuurd", len(verstuurd), 0)
    zo("en niets vastgelegd", db.laatste_bericht(WINKEL), None)

    print("\n== met verstuur=True gaat hij wel uit, en precies een keer ==")
    echt_uit = meldingen.na_meting(nu, CAT, verstuur=True, basis="https://www.krillo.nl")
    zo("een bericht verstuurd", echt_uit["verstuurd"], 1)
    zo("en de mail is echt aangeroepen", len(verstuurd), 1)
    bericht = db.laatste_bericht(WINKEL)
    klopt("het staat vastgelegd", bericht is not None)
    zo("als daling", bericht["soort"], "daling")

    print("\n== dezelfde ronde nog eens draaien mailt niet opnieuw ==")
    nogmaals = meldingen.na_meting(nu, CAT, verstuur=True, basis="https://www.krillo.nl")
    zo("er gaat niets meer uit", nogmaals["verstuurd"], 0)
    zo("en de mail is niet nog eens aangeroepen", len(verstuurd), 1)

    print("\n== en een nieuwe ronde valt binnen de rustperiode ==")
    derde = db.start_categorie_ronde(CAT, 30, 2)
    db.bewaar_categorie_uitkomsten(derde, CAT, [
        {"webshop_url": WINKEL, "positie": 20, "genoemd": 1, "aanbevolen": 0,
         "beste_positie": 9},
    ], 20)
    later = meldingen.na_meting(derde, CAT, verstuur=True, basis="https://www.krillo.nl")
    zo("nog steeds maar een mail in totaal", len(verstuurd), 1)
    zo("en de reden staat erbij",
       later["regels"][0]["soort"], "geen")
finally:
    emailing.send_vermeldingen_update = echt

print("\n== de beheerpagina verstuurt nooit ==")
import app as krillo  # noqa: E402
bron = open(os.path.join(APP, "app.py")).read()
stuk = bron[bron.index('def admin_ranglijst'):]
stuk = stuk[:stuk.index("\n@app.route")]
klopt("op de beheerpagina staat verstuur=False", "verstuur=False" in stuk)
klopt("en nergens verstuur=True", "verstuur=True" not in stuk)

onderhoudbron = open(os.path.join(APP, "onderhoud.py")).read()
klopt("de nachtronde verstuurt wel", "verstuur=True" in onderhoudbron)

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
