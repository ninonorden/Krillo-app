"""Bewaakt de stekker per winkelplatform.

Waarom dit bewaakt moet worden. Het actieplan zegt wat er moet gebeuren, de
stekker zegt waar je dat doet. Die twee lijsten staan in verschillende
bestanden, en zo'n paar loopt vanzelf uit elkaar: er komt een taak bij in
actieplan.py en niemand denkt eraan er een weg bij te zetten. Dan staat er bij
die ene taak niets, en dat merk je pas als je in de winkel van een klant zit.

Het tweede stuk is een belofte. Alleen Shopify kan Krillo echt zelf bijwerken,
want daar bestaat een app met toestemming en een knop om alles terug te zetten.
Zou hier per ongeluk ergens anders `automatisch: True` komen te staan, dan zegt
het werkbriefje dat Krillo het doet terwijl er niets gebeurt. Dan blijft het
werk liggen bij een klant die betaald heeft.
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, TEMPLATES, lees  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import actieplan       # noqa: E402
import scan_engine     # noqa: E402
import toepasmodule    # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== elk platform dat de scan herkent heeft een stekker ==")
# Zonder dit valt een herkend platform stilletjes terug op het algemene
# verhaal, en dan is het herkennen voor niets geweest.
for naam, _sporen in scan_engine.PLATFORM_SPOREN:
    s = toepasmodule.stekker(naam)
    zo(f"{naam} heeft een eigen stekker", s is not toepasmodule.ONBEKEND, True)
    zo(f"{naam} heet ook zo", bool(s["naam"]), True)

print("\n== de naam mag geschreven worden zoals hij uitkomt ==")
for schrijfwijze in ("CCV Shop", "ccvshop", "CCV shop", "ccv-shop"):
    zo(f"{schrijfwijze!r} vindt dezelfde stekker",
       toepasmodule.stekker(schrijfwijze)["naam"], "CCV Shop")
zo("onbekend is geen fout", toepasmodule.stekker("Iets Nieuws")["naam"],
   "onbekend platform")
zo("leeg ook niet", toepasmodule.stekker(None)["naam"], "onbekend platform")

print("\n== elke taak uit het actieplan heeft een weg ==")
# De sleutels uit actieplan.py. Komt er daar een taak bij, dan valt deze test
# om zolang er geen weg bij staat, en dat is precies de bedoeling.
taken = sorted(set(actieplan.BLOKKADE_ACTIES) | set(actieplan.BELEMMERING_ACTIES))
klopt("er zijn taken om te controleren", len(taken) >= 10)
for sleutel, s in toepasmodule.STEKKERS.items():
    ontbreekt = [t for t in taken if not toepasmodule.stappen_voor(s["naam"], t)]
    zo(f"{s['naam']} weet bij elke taak de weg", ontbreekt, [])
ontbreekt = [t for t in taken if not toepasmodule.stappen_voor("Iets Nieuws", t)]
zo("ook bij een onbekend platform", ontbreekt, [])

print("\n== de stappen zeggen echt iets ==")
# Een weg van vier woorden is geen weg. Dit vangt het geval dat iemand een
# platform toevoegt met lege of half ingevulde teksten.
for sleutel, s in toepasmodule.STEKKERS.items():
    kort = [t for t, tekst in s["stappen"].items() if len(tekst or "") < 30]
    zo(f"{s['naam']} heeft nergens een loze regel", kort, [])

print("\n== geen gedachtestreepjes ==")
streepjes = []
for s in list(toepasmodule.STEKKERS.values()) + [toepasmodule.ONBEKEND]:
    streepjes += [f"{s['naam']}:{t}" for t, tekst in s["stappen"].items()
                  if "—" in (tekst or "") or "–" in (tekst or "")]
zo("nergens een gedachtestreepje", streepjes, [])

print("\n== alleen Shopify belooft dat wij het zelf doen ==")
automatisch = sorted(s["naam"] for s in toepasmodule.STEKKERS.values() if s["automatisch"])
zo("precies één platform", automatisch, ["Shopify"])
klopt("en dat is Shopify", toepasmodule.kan_automatisch("Shopify"))
klopt("WooCommerce niet", not toepasmodule.kan_automatisch("WooCommerce"))
klopt("onbekend al helemaal niet", not toepasmodule.kan_automatisch(None))
# Wat belooft te schrijven, moet ook een motor hebben die dat kan.
for s in toepasmodule.STEKKERS.values():
    if s["automatisch"]:
        klopt(f"{s['naam']} heeft een motor", bool(s["motor"]))
        klopt(f"de motor van {s['naam']} bestaat echt",
              os.path.exists(os.path.join(APP, s["motor"] + ".py")))

print("\n== het plan krijgt de stappen erbij ==")
plan = {"kop": "Kop", "acties": [{"id": "faq", "titel": "Zet er een vraagpagina bij"},
                                 {"id": "alt_tekst", "titel": "Alt-teksten"},
                                 {"id": "bronnen", "titel": "Externe pagina's"}]}
uit = toepasmodule.verrijk_plan(plan, "WooCommerce")
klopt("bij de vraagpagina staat het WordPress-menu",
      "Pagina's" in uit["acties"][0]["stappen"])
klopt("bij alt-tekst staat waar dat veld zit",
      "Alternatieve tekst" in uit["acties"][1]["stappen"])
# "bronnen" is geen taak in de winkel maar buiten de winkel. Daar hoort geen
# menupad bij, en er hoort ook geen verzonnen pad te verschijnen.
zo("bij werk buiten de winkel staat niets", uit["acties"][2]["stappen"], None)
zo("een plan zonder acties blijft heel",
   toepasmodule.verrijk_plan({"acties": []}, "Shopify"), {"acties": []})
zo("geen plan geeft geen fout", toepasmodule.verrijk_plan(None, "Shopify"), None)

print("\n== het werkbriefje laat het ook echt zien ==")
briefje = open(os.path.join(TEMPLATES, "admin_werkbriefje.html")).read()
klopt("de stappen staan op de pagina", "a.stappen" in briefje)
klopt("met de naam van het platform erboven", "stekker.naam" in briefje)
klopt("en een waarschuwing bij een platform dat wij zelf doen",
      "stekker.automatisch" in briefje)
app_tekst = lees("app.py")
klopt("de pagina krijgt de stekker mee", "stekker=stek" in app_tekst)
klopt("en het plan wordt verrijkt", "toepasmodule.verrijk_plan" in app_tekst)

print("\n== het overzicht zet de automatische bovenaan ==")
regels = toepasmodule.overzicht()
klopt("er staat iets in", len(regels) >= 8)
zo("Shopify staat vooraan", regels[0]["platform"], "Shopify")
klopt("elk platform noemt hoeveel taken hij kent",
      all(r["taken"] >= 10 for r in regels))

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
