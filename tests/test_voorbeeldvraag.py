"""Welke vraag er als voorbeeld in de onderzoeksmail belandt.

Deze keuze is klein en kan de hele mail onderuit halen, dus hij staat vast in
een test. Wat er mis kan gaan zonder dat iemand het merkt:

- Een vraag waarbij de winkel WEL genoemd werd. Dan zegt het voorbeeld precies
  het tegenovergestelde van de zin eromheen.
- De winkel van de lezer tussen de concurrenten. Dan staat zijn eigen naam bij
  de winkels die er wel uitkwamen, met daaronder dat hij er niet bij stond.
- De winkels van twee modellen bij elkaar geveegd. Dan staat er "ChatGPT
  antwoordde met acht winkels" terwijl ChatGPT er vier noemde. Dat is niet waar,
  en bij een ongevraagde mail word je daarop afgerekend.
- Een antwoord met een enkele winkel erin. Dat is geen patroon maar een
  uitschieter.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import beoordeling  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


WINKEL = "https://voorbeeldwinkel.nl"


def antwoord(vraag, winkels, genoemd=False, telt_mee=True, model="gpt-5.6-terra"):
    return {"vraag": vraag, "model": model, "genoemd": genoemd,
            "winkel_kon_genoemd": telt_mee,
            "winkels": [{"naam": n} for n in winkels]}


print("\n== het antwoord met de meeste winkels wint ==")
uit = beoordeling.voorbeeldvraag(WINKEL, [
    antwoord("Waar koop ik sokken?", ["Bol", "Zalando"]),
    antwoord("Beste webshop voor wol?", ["Bol", "Zalando", "Wolhuis", "Breiland"]),
    antwoord("Waar vind ik naalden?", ["Bol", "Zalando", "Naaldpunt"]),
])
zo("de rijkste vraag is gekozen", uit["vraag"], "Beste webshop voor wol?")
zo("met alle vier de winkels", uit["aantal"], 4)
zo("en de naam van het model dat antwoordde", uit["model"], "ChatGPT")

print("\n== een vraag waarbij de winkel wel genoemd werd doet niet mee ==")
uit = beoordeling.voorbeeldvraag(WINKEL, [
    antwoord("Waar koop ik sokken?", ["Bol", "Zalando", "Sokkenhuis", "Tex"],
             genoemd=True),
    antwoord("Beste webshop voor wol?", ["Bol", "Zalando"]),
])
zo("de vraag zonder vermelding is gekozen", uit["vraag"], "Beste webshop voor wol?")

print("\n== de eigen winkel telt nooit als concurrent ==")
uit = beoordeling.voorbeeldvraag(WINKEL, [
    antwoord("Waar koop ik sokken?", ["Voorbeeldwinkel", "Bol", "Zalando"]),
])
klopt("de eigen naam staat er niet tussen",
      not any("voorbeeldwinkel" in n.lower() for n in uit["winkels"]))
zo("en telt ook niet mee in het aantal", uit["aantal"], 2)

print("\n== twee modellen worden niet bij elkaar geveegd ==")
# Allebei de modellen noemden twee winkels bij dezelfde vraag. Er mag dan geen
# antwoord van vier uitkomen, want geen van beide modellen zei dat.
uit = beoordeling.voorbeeldvraag(WINKEL, [
    antwoord("Waar koop ik sokken?", ["Bol", "Zalando"], model="gpt-5.6-terra"),
    antwoord("Waar koop ik sokken?", ["Coolblue", "Wehkamp"], model="gemini-3.7-flash"),
])
zo("het blijft bij het aantal van een model", uit["aantal"], 2)

print("\n== dubbele namen in een antwoord tellen een keer ==")
uit = beoordeling.voorbeeldvraag(WINKEL, [
    antwoord("Waar koop ik sokken?", ["Bol", "bol", "BOL", "Zalando"]),
])
zo("een keer Bol, een keer Zalando", uit["aantal"], 2)

print("\n== wanneer er geen voorbeeld is ==")
zo("zonder beoordelingen niets", beoordeling.voorbeeldvraag(WINKEL, []), None)
zo("een antwoord met een winkel is te mager",
   beoordeling.voorbeeldvraag(WINKEL, [antwoord("Waar?", ["Bol"])]), None)
zo("een vraag die niet meetelt doet niet mee",
   beoordeling.voorbeeldvraag(WINKEL, [
       antwoord("Waar?", ["Bol", "Zalando"], telt_mee=False)]), None)
zo("overal genoemd betekent geen voorbeeld",
   beoordeling.voorbeeldvraag(WINKEL, [
       antwoord("Waar?", ["Bol", "Zalando"], genoemd=True)]), None)
zo("een lege vraag doet niet mee",
   beoordeling.voorbeeldvraag(WINKEL, [antwoord("", ["Bol", "Zalando"])]), None)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
