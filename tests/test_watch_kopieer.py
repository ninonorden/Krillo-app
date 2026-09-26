"""Wat elk plan in de app met de fixes mag: lezen, kopieren of toepassen.

WAAROM DEZE TEST BESTAAT

26 september vroeg Nino: bij Watch kun je toch ook "Add this" en "Undo this"
doen, dus schrijven we dan ook in de winkel? Het antwoord was: ja, maar alleen
de 3 gratis wijzigingen die iedereen krijgt. Dat klopte op de server. Het
scherm klopte niet:
1. Watch belooft "every fix written out, ready to copy", maar er was geen
   Copy-knop.
2. Een gratis winkel zag precies dezelfde teksten als Watch, dus Watch voegde
   aan fixes niets toe.
3. Na de 3 gratis stond er "the plan below applies the rest", ook voor iemand
   die Watch al had.
Nu: gratis ziet de teksten van zijn gratis wijzigingen, Watch ziet alles met
Copy, Fix zet alles erin. Wat op slot staat gaat niet mee naar de browser.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
os.environ.setdefault("ADMIN_KEY", "testsleutel")
os.environ.setdefault("BASE_URL", "https://krilloai.com")
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


import app as appmod  # noqa: E402

V = [{"id": f"shopify:tekst:{i}", "waar": f"Product {i}", "wat": "Description",
      "oud": "", "nieuw": f"Nieuwe tekst {i}"} for i in range(6)]

print("\n== DE TRAP PER PLAN ==")
fix = appmod._voorstellen_per_plan(V, "fix", None)
klopt("Fix ziet alles", all(v.get("nieuw") for v in fix) and not any(v.get("slot") for v in fix))
watch = appmod._voorstellen_per_plan(V, "watch", 0)
klopt("Watch ziet alle teksten, ook met 0 gratis over",
      all(v.get("nieuw") for v in watch) and not any(v.get("slot") for v in watch))
gratis = appmod._voorstellen_per_plan(V, None, 3)
klopt("gratis: de eerste 3 open", [bool(v.get("nieuw")) for v in gratis] == [True] * 3 + [False] * 3)
klopt("de rest op slot, zonder tekst", all(v.get("slot") and "nieuw" not in v for v in gratis[3:]))
klopt("maar WAAR het ontbreekt staat er wel", gratis[5]["waar"] == "Product 5")
op = appmod._voorstellen_per_plan(V, None, 0)
klopt("gratis op: alles op slot", all(v.get("slot") for v in op))
klopt("het origineel blijft heel (de server past nog steeds toe)", all(v.get("nieuw") for v in V))

print("\n== DE SERVER ==")
bron = lees("app.py")
klopt("onbeperkt toepassen blijft alleen Fix",
      bron.count('betaalt = stand_nu["actief"] and stand_nu.get("plan") == "fix"') == 1
      and 'betaalt = plan == "fix" and not stand_nu.get("fout")' in bron)
klopt("het plan gaat mee naar het scherm", '"plan": plan,' in bron)
klopt("het toepassen-antwoord noemt het plan",
      '"plan": stand_nu.get("plan") if stand_nu.get("actief") else None' in bron)
klopt("geeft Shopify geen antwoord, dan teksten tonen maar niets extra toepassen",
      'plan = "watch"' in bron)

print("\n== HET SCHERM ==")
scherm = lees("templates/shopify_app.html")
klopt("Watch krijgt een Copy-knop bij elke fix", "toonKopieer = (stand.plan === 'watch')" in scherm)
klopt("een klik op Copy vinkt het vakje niet om", "e.preventDefault();" in scherm)
klopt("op slot: geen vakje om aan te vinken", 'disabled data-slot="1"' in scherm)
klopt("op slot verwijst naar Watch", "Written out in Watch" in scherm)
klopt("Watch leest niet meer 'the plan below applies the rest'",
      "The plan below applies the rest" not in scherm)
klopt("de Watch-kaart noemt de Copy-knop", "with a Copy button" in scherm)
klopt("en zegt eerlijk dat de gratis wijzigingen er ook bij zitten",
      "Plus the same {{ gratis_totaal }} free changes applied for you" in scherm)
klopt("Undo blijft er voor iedereen", "Undo this" in scherm)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: gratis leest, Watch kopieert, Fix past toe.")
