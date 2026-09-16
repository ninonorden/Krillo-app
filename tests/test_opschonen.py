"""De winkellijst opschonen voor de ranglijst openbaar wordt.

Deze test is geschreven naar aanleiding van de eerste echte ranglijst van
14 september, categorie servies en tafelgerei. Daar stonden drie fouten in:

1. cookinglife.be op een en cookinglife.nl op twee, met exact dezelfde cijfers.
   villeroy-boch.be op zeven en villeroy-boch.nl op acht. Dezelfde winkel, twee
   plekken.
2. Villeroy & Boch en Brabantia in een lijst van webshops, terwijl het merken
   zijn.
3. Zestien van de veertig regels zonder webadres: "Atelier Object", "Blubber en
   Glas", "Hamono", "Mento". Die scoren altijd nul, ook als AI ze wel noemt,
   want de koppeling loopt via het adres.

Alle drie moeten opgelost zijn voordat er ook maar een pagina openbaar gaat.
Een openbare lijst met deze fouten erin is geen index maar een klachtenmagneet,
en het is precies het soort fout dat een winkel zelf als eerste ziet.

Wat hier bewaakt wordt:

- De adresregels zijn puur en zonder modelaanroep. Ketens samenvoegen mag nooit
  van een model afhangen: dat moet in elk land hetzelfde werken en het moet
  na te rekenen zijn.
- Een vermelding gaat NOOIT verloren bij het samenvoegen. De treffer verhuist
  naar het hoofdadres, hij verdwijnt niet.
- Twee adressen van dezelfde keten in dezelfde vraag tellen als een vraag, niet
  als twee. Anders krijgt een keten met vier landdomeinen een viervoudige score.
- Opschonen draait op een eigen draad, nooit aan een verzoek.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db                # noqa: E402
import opschonen         # noqa: E402
import categoriemeting   # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== wat is een webadres en wat is gewoon een naam ==")
for adres in ("https://cookinglife.nl", "cookinglife.nl", "www.dille-kamille.be",
              "https://livingandcompany.com/servies"):
    klopt(f"{adres} is een adres", opschonen.heeft_webadres(adres))
for naam in ("Atelier Object", "Blubber en Glas", "Hamono", "Mento",
             "Woerdman Kookkado", "", None, "geenpunt"):
    klopt(f"{naam!r} is geen adres", not opschonen.heeft_webadres(naam))

print("\n== de stam van een adres ==")
zo("cookinglife.be", opschonen.stam("https://cookinglife.be"), "cookinglife")
zo("cookinglife.nl", opschonen.stam("https://cookinglife.nl"), "cookinglife")
zo("met www ervoor", opschonen.stam("https://www.villeroy-boch.nl"), "villeroy-boch")
zo("een dubbele uitgang", opschonen.stam("https://kookwinkel.co.uk"), "kookwinkel")

print("\n== ketens samenvoegen, zonder een enkele modelaanroep ==")
ECHT = [
    "https://cookinglife.be", "https://cookinglife.nl",
    "https://villeroy-boch.be", "https://villeroy-boch.nl",
    "https://kookpunt.nl", "https://dille-kamille.be",
    "Atelier Object", "Hamono",
]
koppeling = opschonen.groepeer_ketens(ECHT)
zo("cookinglife.be valt onder de .nl",
   koppeling["https://cookinglife.be"], "https://cookinglife.nl")
zo("en de .nl onder zichzelf",
   koppeling["https://cookinglife.nl"], "https://cookinglife.nl")
zo("villeroy-boch ook", koppeling["https://villeroy-boch.be"],
   "https://villeroy-boch.nl")
zo("kookpunt staat alleen", koppeling["https://kookpunt.nl"], "https://kookpunt.nl")
zo("dille-kamille.be heeft hier geen .nl naast zich, dus blijft zichzelf",
   koppeling["https://dille-kamille.be"], "https://dille-kamille.be")
zo("een naam zonder adres blijft ook zichzelf",
   koppeling["Atelier Object"], "Atelier Object")
klopt("elk adres komt in de uitkomst voor", len(koppeling) == len(ECHT))

print("\n== korte stammen worden niet samengevoegd ==")
# "abc.nl" en "abc.be" kunnen prima twee losse bedrijven zijn.
kort = opschonen.groepeer_ketens(["https://abc.nl", "https://abc.be"])
zo("abc.nl blijft zichzelf", kort["https://abc.nl"], "https://abc.nl")
zo("abc.be ook", kort["https://abc.be"], "https://abc.be")

print("\n== de ranglijst na opschonen ==")
WINKELS = [
    {"webshop_url": "https://cookinglife.nl", "soort": "winkel",
     "hoort_bij": "https://cookinglife.nl"},
    {"webshop_url": "https://cookinglife.be", "soort": "winkel",
     "hoort_bij": "https://cookinglife.nl"},
    {"webshop_url": "https://kookpunt.nl", "soort": "winkel",
     "hoort_bij": "https://kookpunt.nl"},
    {"webshop_url": "https://brabantia.com", "soort": "merk",
     "hoort_bij": "https://brabantia.com"},
    {"webshop_url": "Atelier Object", "soort": "geen-adres",
     "hoort_bij": "Atelier Object"},
]
TELLING = {
    "https://cookinglife.nl": {"genoemd": {"v1", "v2"}, "aanbevolen": {"v1"},
                               "beste_positie": 2},
    "https://cookinglife.be": {"genoemd": {"v2", "v3"}, "aanbevolen": {"v3"},
                               "beste_positie": 1},
    "https://kookpunt.nl": {"genoemd": {"v1"}, "aanbevolen": set(),
                            "beste_positie": 4},
    "https://brabantia.com": {"genoemd": {"v1", "v2", "v3"},
                              "aanbevolen": {"v1", "v2"}, "beste_positie": 1},
    "Atelier Object": {"genoemd": set(), "aanbevolen": set(), "beste_positie": None},
}
uit = categoriemeting.rol_ketens_op(TELLING, WINKELS)

zo("er blijven twee winkels over", len(uit), 2)
klopt("cookinglife staat er een keer in", "https://cookinglife.nl" in uit)
klopt("en niet meer onder .be", "https://cookinglife.be" not in uit)
klopt("het merk is eruit", "https://brabantia.com" not in uit)
klopt("de regel zonder adres ook", "Atelier Object" not in uit)

samen = uit["https://cookinglife.nl"]
zo("de vermeldingen van beide adressen zijn opgeteld",
   samen["genoemd"], {"v1", "v2", "v3"})
zo("v2 telt een keer, ook al stond hij bij allebei", len(samen["genoemd"]), 3)
zo("de aanbevelingen ook", samen["aanbevolen"], {"v1", "v3"})
zo("de beste positie is de beste van de twee", samen["beste_positie"], 1)

print("\n== een hoofdadres buiten de categorie laat de telling niet verdampen ==")
LOS = [{"webshop_url": "https://winkel-be.be", "soort": "winkel",
        "hoort_bij": "https://winkel-be.nl"}]
uit2 = categoriemeting.rol_ketens_op(
    {"https://winkel-be.be": {"genoemd": {"v1"}, "aanbevolen": set(),
                              "beste_positie": 3}}, LOS)
klopt("de winkel staat er gewoon", "https://winkel-be.be" in uit2)
zo("met zijn vermelding", uit2["https://winkel-be.be"]["genoemd"], {"v1"})

print("\n== in de database ==")
db.init_db()
PROEF = ["https://proefwinkel-nl.nl", "https://proefwinkel-nl.be", "Proef Zonder Adres"]


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (PROEF,))
    conn.close()


opruimen()
for url in PROEF:
    db.voeg_benadering_toe(url, naam=url, land="NL", branche="test")

rijen = {r["webshop_url"]: r for r in db.alle_benaderingen_kaal()}
klopt("de proefwinkels staan erin", all(u in rijen for u in PROEF))
zo("en beginnen als winkel", rijen[PROEF[0]]["soort"], "winkel")

db.zet_soort("Proef Zonder Adres", "geen-adres")
db.zet_hoort_bij(PROEF[1], PROEF[0])
rijen = {r["webshop_url"]: r for r in db.alle_benaderingen_kaal()}
zo("de soort is bewaard", rijen["Proef Zonder Adres"]["soort"], "geen-adres")
zo("en het hoofdadres ook", rijen[PROEF[1]]["hoort_bij"], PROEF[0])

telling = db.opschoonstand()
klopt("de opschoonstand telt iets", telling.get("totaal", 0) >= 3)

print("\n== opschonen draait op een eigen draad ==")
bron = lees("app.py")
i = bron.find("def admin_opschonen(")
klopt("de route bestaat", i > 0)
blok = bron[i:i + 2200]
einde = blok.find("\n@app.route")
blok = blok[:einde] if einde > 0 else blok
klopt("de route accepteert POST", 'methods=["GET", "POST"]' in bron[max(0, i - 120):i])
klopt("opschonen gebeurt alleen op een POST", 'request.method == "POST"' in blok)
zo("via start_opschonen en niet rechtstreeks", blok.count("start_opschonen"), 1)
klopt("schoon_alles_op wordt niet in het verzoek aangeroepen",
      "schoon_alles_op(" not in blok)

print("\n== de beheerpagina laadt ==")
import app as krillo  # noqa: E402

krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()
antwoord = klant.get("/admin/opschonen?key=testsleutel", follow_redirects=True)
zo("de pagina laadt", antwoord.status_code, 200)
tekst = antwoord.get_data(as_text=True)
klopt("met de kop erop", "Winkels opschonen" in tekst)

kaal = krillo.app.test_client()
antwoord = kaal.get("/admin/opschonen")
klopt("zonder inloggen kom je er niet in",
      antwoord.status_code in (301, 302)
      and "/admin/inloggen" in antwoord.headers.get("Location", ""))

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
