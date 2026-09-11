"""Bewaakt dat een pagina openen niets in de database verandert.

Dit is de fout die op 11 september de hele site heeft platgelegd. De
kostenpagina werkte bij elke keer laden tweeduizend regels bij. Dat duurde
langer dan de tijdslimiet van de webserver, dus de werker werd afgeschoten, de
opdracht draaide terug, en de volgende verversing begon opnieuw. Ondertussen
laadde er niets meer, ook de gewone pagina's niet.

De regel die hier bewaakt wordt: een verzoek dat alleen iets opvraagt (een GET,
dus gewoon een pagina openen of verversen) mag niets veranderen. Wil je iets
laten gebeuren, dan hoort daar een knop bij, en dus een POST of op zijn minst
een uitdrukkelijke parameter in het webadres.

Dit is geen theorie. Een browser haalt pagina's soms uit zichzelf op, een
voorvertoning van een link doet dat ook, en jij drukt op verversen als iets niet
werkt. Alle drie horen niets aan te zetten.

Onderaan staat een lijst met de plekken waar een GET wel iets vastlegt, met per
plek de reden. Komt er een nieuwe bij, dan valt deze test om en moet je die
bewust op de lijst zetten.
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import lees  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


# Waar een GET wel iets mag vastleggen, en waarom. Alles hier is klein: één
# regel erbij of één veld bijwerken, geen lus over duizenden rijen.
TOEGESTAAN = {
    # Tellen dat iemand zijn uitslag opende of doorklikte. Dat is precies één
    # regel, en het moet bij het openen gebeuren, anders meet je het niet.
    "uitkomst": "telt dat de uitslag geopend is",
    "uitkomst_verder": "telt de doorklik naar de prijzen",
    "rapport": "telt dat het rapport bekeken is",
    # De terugkeer van Shopify na het geven van toestemming. Dat is een
    # eenmalige stap in het inloggen en kan niet anders.
    "shopify_callback": "slaat de toegang op die de winkelier net gaf",
    "shopify_api_abonnement": "legt de keuze van de winkelier vast",
    # Beheerpagina's die op een uitdrukkelijke parameter iets doen. Die
    # parameter is de knop: zonder staat er niets te gebeuren.
    "admin_koopvragen": "alleen op ?opnieuw, ?aanvul of ?ontdubbel",
    "admin_metingen": "alleen op ?start",
    "admin_beoordelingen": "alleen op ?start, ?opnieuw of ?controleer",
    "admin_oplossingen": "alleen op ?opnieuw",
    "admin_kosten": "alleen op ?herstel",
}

SCHRIJFT = re.compile(
    r"db\.(zet_|bewaar_|voeg_|verwijder_|markeer|start_|claim_|noteer_|herstel_"
    r"|leg_|ontclaim|save_)")

bron = lees("app.py")
stukken = re.split(r"\n@app\.route\(", bron)

gevonden = {}
for stuk in stukken[1:]:
    kop = stuk.split(")", 1)[0]
    naam = re.search(r"def (\w+)", stuk)
    if not naam:
        continue
    einde = stuk.find("\n@app.route")
    lichaam = stuk[:einde] if einde > 0 else stuk
    # Alleen routes die geen POST accepteren. Een POST komt van een formulier,
    # en dat is per definitie een knop.
    if "POST" in kop:
        continue
    if SCHRIJFT.search(lichaam):
        gevonden[naam.group(1)] = sorted(set(m.group(0) for m in SCHRIJFT.finditer(lichaam)))

print("\n== geen nieuwe plek waar een GET stiekem iets vastlegt ==")
nieuw = sorted(set(gevonden) - set(TOEGESTAAN))
zo("geen onbekende schrijvende GET-route", nieuw, [])
if nieuw:
    for n in nieuw:
        print(f"       {n} schrijft: {gevonden[n]}")
        print("       Hoort dit hier? Zet er dan een knop of een parameter op, of")
        print("       zet hem met een reden in TOEGESTAAN in deze test.")

print("\n== de beheerpagina's doen alleen iets op een uitdrukkelijke parameter ==")
for functie in ("admin_koopvragen", "admin_metingen", "admin_beoordelingen",
                "admin_oplossingen", "admin_kosten"):
    i = bron.find(f"def {functie}(")
    klopt(f"{functie} bestaat nog", i > 0)
    if i < 0:
        continue
    blok = bron[i:]
    einde = blok.find("\n@app.route")
    blok = blok[:einde] if einde > 0 else blok[:6000]
    klopt(f"{functie} kijkt eerst naar een parameter", "request.args.get(" in blok)

print("\n== en de kostenpagina in het bijzonder ==")
i = bron.find("def admin_kosten(")
blok = bron[i:i + 1600]
klopt("herstellen hangt aan ?herstel=ja", 'request.args.get("herstel") == "ja"' in blok)
klopt("en staat niet los in de functie",
      blok.count("db.herstel_onbekende_kosten") == 1)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
