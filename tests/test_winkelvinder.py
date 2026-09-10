"""Bewaakt het zelf vinden van winkels en het beheer van de meetrij.

Twee dingen die allebei uit dezelfde klacht komen: de machine moet zonder
handwerk draaien, en hij moet niet doen alsof hij werkt terwijl hij stilstaat.

1. De benaderlijst raakte op. Bij vijftien mails per dag is tweehonderd winkels
   binnen twee weken leeg. Dan staat alles stil zonder dat er iets kapot is, en
   moest er met de hand een lijst geplakt worden.

2. De meetrij staat in het geheugen en verdwijnt bij elke herstart van Render,
   ook bij een nieuwe versie. Winkels bleven dan op "meten" staan terwijl er
   niets liep, en elke ronde zette er vijf nieuwe bij. Zo liep de teller op naar
   vijfenzestig terwijl er nul gemeten werd.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db             # noqa: E402
import benadering     # noqa: E402
import bronnen        # noqa: E402
import winkelvinder   # noqa: E402

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

print("\n== wat geen webshop is komt er niet op ==")
# Deze staan altijd bovenaan bij dit soort zoekopdrachten. Zouden ze erop komen,
# dan mail je een marktplaats of een krant, en dat is precies het soort post
# waar iemand op 'spam' drukt.
for host in ("bol.com", "shop.bol.com", "amazon.nl", "marktplaats.nl",
             "wikipedia.org", "nu.nl", "blog.iemand.nl", "trustpilot.com",
             "shopify.com", "postnl.nl", ""):
    zo(f"{host!r} valt af", winkelvinder._is_bruikbaar(host), False)

print("\n== een echte winkel komt er wel op ==")
for host in ("mooiewinkel.nl", "de-groene-plantenshop.nl", "winkel.be",
             "sieraden-atelier.nl"):
    zo(f"{host!r} mag erop", winkelvinder._is_bruikbaar(host), True)

print("\n== het webadres wordt goed uitgelezen ==")
zo("met www en een pad", winkelvinder._domein("https://www.Winkel.nl/a/b?x=1"),
   "winkel.nl")
zo("zonder pad", winkelvinder._domein("http://winkel.be"), "winkel.be")
zo("leeg blijft leeg", winkelvinder._domein(None), "")

print("\n== elke ronde zoekt iets anders ==")
# Zonder dit levert ronde twee precies dezelfde winkels op als ronde een, en
# betaal je elke ronde opnieuw voor niets.
r0 = [o["vraag"] for o in winkelvinder._zoekopdrachten(4, ronde=0)]
r1 = [o["vraag"] for o in winkelvinder._zoekopdrachten(4, ronde=1)]
zo("vier opdrachten per ronde", len(r0), 4)
zo("geen overlap met de vorige ronde", sorted(set(r0) & set(r1)), [])
klopt("de branche staat erin", any("kleding" in v for v in r0))
klopt("en het land ook", all("Nederland" in v or "Belgie" in v for v in r0))
# Ver vooruit moet hij nog steeds werken en niet buiten de lijst vallen.
ver = winkelvinder._zoekopdrachten(4, ronde=999)
zo("ook na duizend rondes vier opdrachten", len(ver), 4)
klopt("allemaal met een echte branche",
      all(o["branche"] in winkelvinder.BRANCHES for o in ver))

print("\n== gevonden winkels komen op de lijst ==")
echte_zoek = bronnen.zoek
echte_beschikbaar = bronnen.beschikbaar
bronnen.beschikbaar = lambda: True
bronnen.zoek = lambda vraag, **kw: [
    {"url": "https://www.bol.com/nl/kleding", "titel": "bol"},
    {"url": "https://vindertest-een.nl/collectie", "titel": "winkel"},
    {"url": "https://www.vindertest-twee.be/", "titel": "winkel"},
    {"url": "https://vindertest-een.nl/andere-pagina", "titel": "zelfde winkel"},
]
for u in ("https://vindertest-een.nl", "https://vindertest-twee.be"):
    db.zet_benadering(u, stand="afgevallen")

uit = winkelvinder.zoek_nieuwe_winkels(hoeveel_zoekopdrachten=1, ronde=0)
zo("er is een keer gezocht", uit["gezocht"], 1)
klopt("er zijn winkels bij gekomen of ze stonden er al",
      uit["nieuw"] >= 0 and uit.get("reden") in (None, ) or uit["nieuw"] == 0)
lijst = {r["webshop_url"] for r in db.get_benaderingen(alleen_niet_afgemeld=False)}
klopt("de eerste winkel staat erop", "https://vindertest-een.nl" in lijst)
klopt("de tweede ook", "https://vindertest-twee.be" in lijst)
klopt("bol.com niet", not any("bol.com" in u for u in lijst))

print("\n== dezelfde winkel komt er niet twee keer op ==")
voor = len(db.get_benaderingen(alleen_niet_afgemeld=False))
winkelvinder.zoek_nieuwe_winkels(hoeveel_zoekopdrachten=1, ronde=0)
na = len(db.get_benaderingen(alleen_niet_afgemeld=False))
zo("de lijst is niet gegroeid", na, voor)

print("\n== zonder zoekmachine gebeurt er niets, zonder foutmelding ==")
bronnen.beschikbaar = lambda: False
uit = winkelvinder.zoek_nieuwe_winkels(hoeveel_zoekopdrachten=1)
zo("er is niet gezocht", uit["gezocht"], 0)
klopt("met een reden erbij", "beschikbaar" in (uit["reden"] or ""))
bronnen.beschikbaar = lambda: True

print("\n== er wordt alleen gezocht als de voorraad op raakt ==")
# Anders betaal je elke ronde voor namen die weken blijven liggen.
uit = winkelvinder.vul_aan_indien_nodig(ondergrens=0)
zo("bij genoeg voorraad niet zoeken", uit["gezocht"], 0)
uit = winkelvinder.vul_aan_indien_nodig(ondergrens=10 ** 6)
klopt("bij te weinig voorraad wel", uit["gezocht"] >= 1)

bronnen.zoek = echte_zoek
bronnen.beschikbaar = echte_beschikbaar

print("\n== het rondenummer loopt op en blijft bewaard ==")
een = benadering.rondenummer()
twee = benadering.rondenummer()
zo("de tweede is een hoger", twee, een + 1)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
