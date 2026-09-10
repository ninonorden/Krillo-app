"""Bewaakt dat een Engelse winkel geen Nederlandse voortgangstekst ziet.

Dit ging mis en het is precies het soort fout dat je zelf niet meer ziet: de
knoppen, de kopjes en de voorstellen waren allang Engels, maar de balk die
minutenlang in beeld staat zei "Working: vragen stellen aan AI".

Waarom de teksten uit app.py gelezen worden in plaats van hier overgetypt: dan
valt deze test om zodra iemand een nieuwe stap toevoegt zonder vertaling. Een
lijst die je hier moet bijhouden raakt achter en bewaakt dan niets meer.
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import app as krillo  # noqa: E402

NL = {"is_nederlands": True}
EN = {"is_nederlands": False}

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


bron = open(os.path.join(APP, "app.py")).read()
teksten = set(re.findall(r'melden\(\s*"([^"]+)"', bron))
teksten |= set(re.findall(r'"tekst":\s*"([^"]+)"', bron))
# Komt uit de labeltabel voor soorten wijzigingen, geen voortgangstekst.
teksten.discard("tekst")
# Teksten die met "mislukt" beginnen hebben een vrije Nederlandse reden achter
# zich uit de kostenrem of de meetketen. Die worden niet vertaald maar
# vervangen door een nette Engelse zin, want een halve Nederlandse zin op een
# Engels scherm is erger dan minder detail.
mislukt = {t for t in teksten if t.startswith("mislukt")}
teksten -= mislukt

print("\n== elke voortgangstekst heeft een vertaling ==")
zo("aantal teksten gevonden", len(teksten) > 8, True)
ontbreekt = sorted(t for t in teksten if t not in krillo.STAND_ENGELS)
zo("geen enkele zonder vertaling", ontbreekt, [])

print("\n== een Nederlandse winkel ziet exact hetzelfde als eerst ==")
alles_gelijk = all(
    krillo._stand_in_taal({"tekst": t, "klaar": False}, NL)["tekst"] == t
    for t in teksten)
klopt("alle teksten blijven onveranderd", alles_gelijk)

print("\n== een Engelse winkel krijgt Engels ==")
nederlands = re.compile(r"\b(je|winkel|wij|vragen|klaar|beginnen|het|een|iets|mis)\b")
for t in sorted(teksten):
    uit = krillo._stand_in_taal({"tekst": t, "klaar": False}, EN)["tekst"]
    klopt(f"{t!r} is vertaald", uit != t and not nederlands.search(uit))

print("\n== een mislukking met een Nederlandse reden erachter ==")
for t in sorted(mislukt) + ["mislukt: er is niets gemeten (de dagpot is op)"]:
    uit = krillo._stand_in_taal({"tekst": t, "klaar": True}, EN)["tekst"]
    klopt(f"{t[:40]!r} wordt een Engelse zin",
          uit == krillo.MISLUKT_ENGELS and not nederlands.search(uit))
zo("een Nederlandse winkel ziet de echte reden nog wel",
   krillo._stand_in_taal({"tekst": "mislukt: er is niets gemeten (x)"}, NL)["tekst"],
   "mislukt: er is niets gemeten (x)")

print("\n== randgevallen ==")
zo("geen stand blijft None", krillo._stand_in_taal(None, EN), None)
zo("een onbekende tekst gaat onvertaald door, niet leeg",
   krillo._stand_in_taal({"tekst": "onbekend"}, EN)["tekst"], "onbekend")

origineel = {"tekst": "klaar", "klaar": True, "betaalt": True, "gratis_over": 2}
uit = krillo._stand_in_taal(origineel, EN)
zo("de rest van de stand blijft heel", uit["gratis_over"], 2)
klopt("klaar en betaalt blijven staan", uit["klaar"] and uit["betaalt"])
zo("het origineel wordt niet aangepast", origineel["tekst"], "klaar")

print("\n== geen enkele route stuurt een stand langs de vertaling heen ==")
langs = [r.strip() for r in bron.splitlines()
         if 'jsonify({"stand"' in r and "_stand_in_taal" not in r]
zo("alle stand-routes vertalen", langs, [])
# En de stand die meteen in de pagina meegebakken wordt ook.
klopt("de pagina zelf vertaalt ook",
      "stand=_stand_in_taal(" in bron)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
