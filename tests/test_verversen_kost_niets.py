"""Verversen mag nooit iets starten, en nooit geld kosten.

WAT ER MISGING OP 16 SEPTEMBER

Nino startte een meting van Speelgoed en ververste een kwartier lang de pagina.
Er stond steeds "BEZIG met Speelgoed, sinds 0 seconden".

Nul seconden, na een kwartier. Dat was de aanwijzing. Elke verversing stuurde
het formulier opnieuw op, startte een nieuwe meting, en gooide de vorige weg.
Hij heeft dus nooit gezien wat er misging, want de foutmelding van de mislukte
poging werd elke keer overschreven door een nieuwe poging.

Erger dan de verwarring is de rekening: een meting kost geld, en verversen
hoort gratis te zijn.

Er zat nog een tweede lek in dezelfde pagina. Het keuzemenu voor de categorie
stuurde hetzelfde formulier op. Een andere categorie kiezen om even te kijken
startte dus meteen een meting van die categorie.

DE OPLOSSING, EN WAAROM DEZE

Verwerk de POST, stuur door naar een GET, zet de melding in het webadres.
Verversen is dan alleen nog kijken. Dit heet doorsturen na versturen en is de
standaardoplossing voor precies dit probleem.

Plus: meten gebeurt alleen bij een knop die "actie=meten" meestuurt. Kiezen
kan niets meer starten.

WAT DEZE TEST BEWAAKT

- Een GET op een beheerpagina start nooit iets.
- Een POST stuurt altijd door naar een GET.
- Een categorie kiezen start geen meting.
- Alleen de knop met actie=meten start een meting.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import categorieen      # noqa: E402
import categoriemeting  # noqa: E402
import db               # noqa: E402
import opschonen        # noqa: E402

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
import app as krillo  # noqa: E402

krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()
SLEUTEL = "?key=testsleutel"

# De echte starters vervangen, zodat deze test nooit een euro kan kosten en
# tegelijk precies kan tellen hoe vaak er gestart werd.
gestart = {"meting": 0, "vergelijking": 0, "opschonen": 0, "indelen": 0}
echt = {
    "meting": categoriemeting.start_meting,
    "vergelijking": categoriemeting.start_vergelijking,
    "opschonen": opschonen.start_opschonen,
    "indelen": categorieen.start_indelen,
}


def teller(naam):
    def nep(*a, **k):
        gestart[naam] += 1
        return True
    return nep


categoriemeting.start_meting = teller("meting")
categoriemeting.start_vergelijking = teller("vergelijking")
opschonen.start_opschonen = teller("opschonen")
categorieen.start_indelen = teller("indelen")
krillo.categoriemeting.start_meting = categoriemeting.start_meting
krillo.categoriemeting.start_vergelijking = categoriemeting.start_vergelijking
krillo.opschonen.start_opschonen = opschonen.start_opschonen
krillo.categorieen.start_indelen = categorieen.start_indelen

try:
    print("\n== een GET start nooit iets ==")
    for pad in ("/admin/ranglijst", "/admin/opschonen", "/admin/categorieen"):
        for keer in range(3):
            klant.get(pad + SLEUTEL, follow_redirects=True)
    zo("drie keer de ranglijst openen start geen meting", gestart["meting"], 0)
    zo("en geen vergelijking", gestart["vergelijking"], 0)
    zo("het opschonen ook niet", gestart["opschonen"], 0)
    zo("en het indelen ook niet", gestart["indelen"], 0)

    print("\n== een categorie kiezen kost niets ==")
    # Dit ging mis: het keuzemenu stuurde het meetformulier op.
    klant.get("/admin/ranglijst?key=testsleutel&categorie=speelgoed",
              follow_redirects=True)
    klant.get("/admin/ranglijst?key=testsleutel&categorie=kleding",
              follow_redirects=True)
    zo("wisselen van categorie start geen meting", gestart["meting"], 0)

    print("\n== alleen de knop met actie=meten start een meting ==")
    antwoord = klant.post("/admin/ranglijst" + SLEUTEL,
                          data={"categorie": "speelgoed"})
    zo("een POST zonder actie start niets", gestart["meting"], 0)

    antwoord = klant.post("/admin/ranglijst" + SLEUTEL,
                          data={"categorie": "speelgoed", "actie": "meten"})
    zo("met de knop wel", gestart["meting"], 1)
    klopt("en hij stuurt door naar een GET", antwoord.status_code in (301, 302))
    klopt("naar de ranglijst met de melding erin",
          "/admin/ranglijst" in antwoord.headers.get("Location", "")
          and "m=" in antwoord.headers.get("Location", ""))

    print("\n== die doorgestuurde pagina verversen start niets ==")
    plek = antwoord.headers["Location"]
    for keer in range(5):
        klant.get(plek + "&key=testsleutel")
    zo("vijf keer verversen, nog steeds een meting", gestart["meting"], 1)

    print("\n== hetzelfde voor opschonen en indelen ==")
    antwoord = klant.post("/admin/opschonen" + SLEUTEL, data={})
    zo("opschonen is gestart", gestart["opschonen"], 1)
    klopt("en stuurt door", antwoord.status_code in (301, 302))
    for keer in range(4):
        klant.get(antwoord.headers["Location"] + "&key=testsleutel")
    zo("verversen start niets nieuws", gestart["opschonen"], 1)

    antwoord = krillo.app.test_client().post("/admin/categorieen" + SLEUTEL, data={})
    zo("indelen is gestart", gestart["indelen"], 1)
    klopt("en stuurt door", antwoord.status_code in (301, 302))
    for keer in range(4):
        klant.get(antwoord.headers["Location"] + "&key=testsleutel")
    zo("verversen start niets nieuws", gestart["indelen"], 1)

    print("\n== de dure knoppen zeggen wat ze kosten ==")
    tekst = klant.get("/admin/ranglijst" + SLEUTEL,
                      follow_redirects=True).get_data(as_text=True)
    klopt("bij meten staat dat het geld kost", "Dit kost geld" in tekst)
    klopt("en bij kiezen dat het niets kost", "Kiezen kost niets" in tekst)
finally:
    categoriemeting.start_meting = echt["meting"]
    categoriemeting.start_vergelijking = echt["vergelijking"]
    opschonen.start_opschonen = echt["opschonen"]
    categorieen.start_indelen = echt["indelen"]
    krillo.categoriemeting.start_meting = echt["meting"]
    krillo.categoriemeting.start_vergelijking = echt["vergelijking"]
    krillo.opschonen.start_opschonen = echt["opschonen"]
    krillo.categorieen.start_indelen = echt["indelen"]

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
