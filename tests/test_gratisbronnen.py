"""Bewaakt de bronanalyse in de gratis test, en het weglekken van kosten.

Waarom dit bestand er is. De bronanalyse is het sterkste dat Krillo heeft: niet
"je wordt niet genoemd" maar "hier staan de pagina's waar je concurrent wel op
staat en jij niet". Dat zat volledig achter de betaalmuur, dus wie de gratis
test deed zag een probleem zonder enige aanwijzing dat wij weten waar het
vandaan komt.

Er zitten drie manieren in waarop dit geld kan kosten zonder dat iemand het
merkt, en die worden hier alledrie bewaakt:

1. De voorproef draait bij ELKE gratis scan. Zou de bronanalyse daar meelopen,
   dan krijgt de goedkoopste stap van de trechter er een zoekmachine en een
   reeks paginabezoeken bij. Die moet dus uit staan.
2. De analyse mag nooit de volle klantinstelling gebruiken, en hij moet die
   instelling teruggeven ook als hij halverwege stukloopt. Blijft de gratis
   stand staan, dan krijgt de volgende betalende klant een halve analyse.
3. Een modelnaam die niet in de prijslijst staat komt binnen als nul euro. Dat
   gebeurde echt: tweeduizend aanroepen op gemini-flash-latest telden voor
   niets mee, en dan klopt de dagpot ook niet meer.

En één ding dat geen geld kost maar wel de verkoop: de gratis uitslag mag de
volledige lijst met adressen niet weggeven. Hoogstens drie pagina's, en zonder
het directe webadres. Dat je weet dat die plekken bestaan is gratis, de lijst om
mee aan het werk te gaan is het product.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import bronnen        # noqa: E402
import kosten         # noqa: E402
import zichtbaarheid  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


SAMENVATTING = {
    "paginas": 9, "sites": 7, "wij_erop": 1, "gemist": 6,
    "conclusie": "We bekeken 9 pagina's op 7 verschillende websites.",
    "concurrenten": [{"naam": "Concurrent A", "paginas": 4, "voorbeelden": []}],
    "gemiste_paginas": [
        {"url": f"https://vergelijk{i}.nl/beste-winkels", "titel": f"Beste winkels {i}",
         "domein": f"vergelijk{i}.nl", "vraag": "waar koop ik x",
         "concurrenten": ["A", "B", "C", "D", "E"]}
        for i in range(6)
    ],
    "vragen": ["waar koop ik x"],
}


print("\n== de gratis uitslag geeft de lijst niet weg ==")
kort = zichtbaarheid._bronnen_inkorten(SAMENVATTING)
zo("hoogstens drie pagina's", len(kort["gemiste_paginas"]), 3)
klopt("nergens een webadres om op te klikken",
      all("url" not in g for g in kort["gemiste_paginas"]))
klopt("de domeinnaam staat er wel, anders zegt het niets",
      all(g["domein"] for g in kort["gemiste_paginas"]))
zo("hoogstens vier concurrenten per pagina",
   max(len(g["concurrenten"]) for g in kort["gemiste_paginas"]), 4)
zo("het totaal blijft eerlijk", kort["gemist"], 6)
klopt("met de conclusie erbij", "9 pagina's" in kort["conclusie"])
zo("niets zonder samenvatting", zichtbaarheid._bronnen_inkorten(None), None)


print("\n== de instelling gaat terug, ook als het stukloopt ==")
vol_vragen = bronnen.MAX_VRAGEN_PER_RONDE
vol_paginas = bronnen.MAX_PAGINAS

echte_analyseer = bronnen.analyseer
echte_beschikbaar = bronnen.beschikbaar
echte_mag = kosten.mag_doorgaan
kosten.mag_doorgaan = lambda **kw: {"mag": True, "reden": None}
bronnen.beschikbaar = lambda: True

gezien = {}


def nep_analyseer(webshop_url, klantbeeld, **kw):
    gezien["vragen"] = bronnen.MAX_VRAGEN_PER_RONDE
    gezien["paginas"] = bronnen.MAX_PAGINAS
    gezien["land"] = kw.get("land")
    raise RuntimeError("zoekmachine ligt eruit")


bronnen.analyseer = nep_analyseer
uit = zichtbaarheid._bronnen_erbij("https://winkel.nl", {"regels": []}, "Winkel", 1)
zo("een kapotte analyse geeft gewoon niets terug", uit, None)
klopt("hij zocht met minder vragen dan bij een klant", gezien["vragen"] < vol_vragen)
klopt("en keek naar minder pagina's", gezien["paginas"] < vol_paginas)
zo("de klantinstelling staat weer terug", bronnen.MAX_VRAGEN_PER_RONDE, vol_vragen)
zo("ook het aantal pagina's", bronnen.MAX_PAGINAS, vol_paginas)

print("\n== zonder zoekmachine gebeurt er niets ==")
bronnen.analyseer = lambda *a, **kw: (_ for _ in ()).throw(
    AssertionError("mocht niet aangeroepen worden"))
bronnen.beschikbaar = lambda: False
zo("niets, en geen foutmelding",
   zichtbaarheid._bronnen_erbij("https://winkel.nl", {"regels": []}, "Winkel", 1), None)
bronnen.beschikbaar = lambda: True

print("\n== de kostenrem gaat hier ook overheen ==")
kosten.mag_doorgaan = lambda **kw: {"mag": False, "reden": "dagpot op"}
zo("de dag is op, dus niet zoeken",
   zichtbaarheid._bronnen_erbij("https://winkel.nl", {"regels": []}, "Winkel", 1), None)
kosten.mag_doorgaan = lambda **kw: {"mag": True, "reden": None}

print("\n== en met de schakelaar uit helemaal niets ==")
aan_was = zichtbaarheid.GRATIS_BRONNEN_AAN
zichtbaarheid.GRATIS_BRONNEN_AAN = False
zo("uit is uit",
   zichtbaarheid._bronnen_erbij("https://winkel.nl", {"regels": []}, "Winkel", 1), None)
zichtbaarheid.GRATIS_BRONNEN_AAN = aan_was

bronnen.analyseer = echte_analyseer
bronnen.beschikbaar = echte_beschikbaar
kosten.mag_doorgaan = echte_mag


print("\n== de voorproef doet dit niet mee ==")
# Dit is het duurste dat er mis kan gaan: de voorproef draait bij elke scan.
app_tekst = lees("app.py")
begin = app_tekst.find("def _draai_voorproef")
stuk = app_tekst[begin:begin + 900]
klopt("de voorproef zet de bronanalyse expliciet uit", "bronnen_erbij=False" in stuk)
klopt("draai() kent die schakelaar",
      "bronnen_erbij=True" in lees("zichtbaarheid.py"))
# De volledige gratis test moet hem juist WEL doen. Die roept draai() aan
# zonder de schakelaar, dus met de standaard.
begin = app_tekst.find("def _draai_zichtbaarheidstest")
stuk = app_tekst[begin:begin + 900]
klopt("de volledige gratis test doet hem wel", "bronnen_erbij" not in stuk)


print("\n== de uitslag laat het zien, op de pagina en in de mail ==")
pagina = lees("templates/index.html")
klopt("de pagina leest het veld uit", "r.bronnen" in pagina)
klopt("met een kop die zegt waar het over gaat",
      "Waar je concurrent wel staat en jij niet" in pagina)
klopt("en zet de namen door de ontsmetter", "veilig(g.titel" in pagina)
mail = lees("emailing.py")
klopt("de mail leest het veld uit", 'resultaat.get("bronnen")' in mail)
klopt("en ontsmet de tekst die erin komt", "_html.escape(namen)" in mail)
klopt("het blok zit ook echt in de mail", "+ bronblok +" in mail)
# De belofte onderaan moet blijven kloppen. Stond er eerst "we hebben je niet
# verteld waarom het zo is", en dat is niet meer waar zodra dit erin zit.
klopt("de mail belooft niets wat hij nu wel geeft",
      "niet verteld waarom het zo is" not in mail)
klopt("de pagina ook niet", "verteld waaróm" not in pagina)


print("\n== elk model dat wij aanroepen heeft een prijs ==")
# Een modelnaam zonder prijs telt als nul euro. Dan lijkt de dagpot nog ruim
# terwijl hij het niet is, en dat is precies waar de rem voor bedoeld is.
namen = {p["model"] for p in kosten.PRIJZEN}
for provider, model in (("google", "gemini-flash-latest"),
                        ("google", "gemini-3.7-flash")):
    klopt(f"{model} staat in de prijslijst", model in namen)
    prijs = kosten.zoek_prijs(provider, model)
    klopt(f"{model} heeft een prijs boven nul",
          prijs and prijs["invoer_per_miljoen"] > 0 and prijs["uitvoer_per_miljoen"] > 0)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
