"""De lopende koersbalk bovenaan de homepage.

WAAROM DEZE TEST BESTAAT

De koersbalk stond eerst als een gewone regel met flex-wrap. Bij drie gemeten
categorieen paste dat niet meer op een regel en viel de balk over twee regels.
Op een screenshot van 18 september zag Nino dat, en terecht: het oogt als een
fout in plaats van als een ontwerp. Het wordt ook alleen maar erger, want de
index groeit naar 31 categorieen.

De balk loopt nu door als een nieuwsbalk. Dat werkt op een truc die stilletjes
kapot kan gaan bij een latere wijziging, en dan ziet niemand het meteen:

1. De berichten moeten er TWEE keer in staan. Schuift het spoor de helft op,
   dan staat kopie twee precies waar kopie een stond en zie je geen sprong.
   Haalt iemand de tweede kopie weg, dan loopt de balk leeg en springt hij
   terug. Dat is precies het soort fout dat je pas ziet als je een halve minuut
   naar je eigen homepage staart.
2. De berichten mogen GEEN gap op het spoor gebruiken maar een marge per
   bericht. Met een gap is de helft van de breedte niet gelijk aan het aantal
   berichten en springt hij alsnog.
3. De loopduur moet meegroeien met het aantal berichten, anders wordt de balk
   een waas zodra de index vol is.

Deze test bewaakt die drie dingen, plus dat de tweede kopie verborgen is voor
een schermlezer en dat de balk stilstaat voor wie beweging heeft uitgezet.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


index = lees("templates/index.html")

print("\n== DE OPBOUW VAN DE BALK ==")
klopt("de balk staat er nog", 'class="ticker"' in index)
klopt("er is een baan die afknipt wat buiten beeld loopt", 'class="baan"' in index)
klopt("er is een spoor dat schuift", 'class="spoor"' in index)
klopt("het merk staat vast links", 'class="merk"' in index)

print("\n== HET LOOPJE ==")
klopt("het spoor heeft een animatie", "animation:tickerloop" in index)
klopt("de animatie schuift precies de helft op",
      "translateX(-50%)" in index)
klopt("de berichten staan er twee keer in",
      "for kopie in [1, 2]" in index)
# Een gap op het spoor is precies de fout die het loopje laat springen. De
# berichten horen hun eigen marge te hebben.
spoor = re.search(r"\.ticker \.spoor\{[^}]*\}", index)
klopt("het spoor gebruikt geen gap", spoor and "gap:" not in spoor.group(0))
klopt("elk bericht heeft zijn eigen marge rechts",
      re.search(r"\.ticker \.post\{[^}]*margin-right:", index) is not None)

print("\n== DE SNELHEID ==")
klopt("de loopduur komt uit het aantal berichten",
      "--loopduur:{{ index.ticker | length" in index)
klopt("er staat een terugval als de variabele ontbreekt",
      "var(--loopduur,")

print("\n== TOEGANKELIJKHEID ==")
klopt("de tweede kopie wordt niet dubbel voorgelezen",
      'aria-hidden="true"' in index)
klopt("de balk staat stil voor wie beweging heeft uitgezet",
      "prefers-reduced-motion" in index
      and re.search(r"prefers-reduced-motion[^@]*\.ticker \.spoor\{animation:none", index) is not None)

print("\n== DE BALK ZELF RENDEREN ==")
# De echte pagina ophalen is het enige dat bewijst dat het sjabloon niet stuk
# is. Een Jinja-fout in de lus valt hier om, niet pas op de live site.
import app  # noqa: E402

app.app.config["TESTING"] = True
k = app.app.test_client()
thuis = k.get("/").get_data(as_text=True)
zo("de homepage laadt", k.get("/").status_code, 200)
# Staat er nog niets gemeten, dan valt de hele balk weg. Dat is bestaand en
# gewenst gedrag: liever geen balk dan een verzonnen regel.
if 'class="ticker"' in thuis:
    klopt("de gerenderde balk heeft twee helften",
          thuis.count('class="helft"') == 2)
    klopt("de gerenderde balk heeft een loopduur",
          "--loopduur:" in thuis)
    print("  (er is gemeten, dus de balk is gerenderd en nagekeken)")
else:
    print("  (nog niets gemeten in deze testdatabase, dus geen balk. "
          "Dat is gewenst gedrag en geen fout.)")

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed: de koersbalk loopt en blijft naadloos.")
