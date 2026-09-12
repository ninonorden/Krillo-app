"""Klopt alles wat wij op de site en in de mails beloven?

Waarom dit bestand bestaat. Krillo verkoopt aan winkeliers, ongevraagd, per
mail. Bij zo'n dienst is de tekst het product: wie iets belooft wat er niet
gebeurt krijgt geen boze klant maar een terugboeking, een klacht en een
beschadigd domein. Op 12 september zijn alle teksten nagelopen en er zaten vijf
dingen tussen die niet waar waren. Die staan hieronder, elk met een test eronder,
zodat ze niet terugsluipen.

Wat er fout was, en waarom het fout was:

1. "Wij voeren ELKE MAAND de verbeteringen uit" stond op de prijskaart, met op de
   regel eronder "hoogstens drie dingen PER WEEK". Twee tempo's voor hetzelfde
   werk, en de keten draait wekelijks. Dus per maand was gewoon onjuist.
2. "De mail aan de redactie staat klaar, of WIJ STUREN HEM NAMENS JOU." Er is
   geen enkele code die namens een klant een mail aan een derde stuurt. Wij
   schrijven de tekst, hij verstuurt hem.
3. "Op dit moment is dat ChatGPT" op de methodepagina, terwijl er bij twee
   modellen gemeten wordt. Onszelf tekortdoen is ook onwaar.
4. "85% van wat AI over een merk zegt komt uit externe bronnen. Onderzoek naar
   ruim 21.000 vermeldingen." Een extern cijfer waarvan wij de bron niet kunnen
   aanwijzen. Als iemand ernaar vraagt heb je niets.
5. "Bij Shopify vervalt onze toegang vanzelf na negentig dagen zonder inloggen."
   Inloggen heeft er niets mee te maken; het is de verversleutel die negentig
   dagen geldig is.

En verder: de getallen die op de site staan moeten uit de code komen, niet uit
een zin die ooit is opgeschreven. Dertien controlepunten, dertig koopvragen,
hoogstens drie acties.
"""
import os
import re
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES, lees  # noqa: E402
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


# De pagina's die een bezoeker of een klant echt te zien krijgt. De
# beheerschermen blijven buiten beschouwing: die zijn voor jezelf en beloven
# niemand iets.
PUBLIEK = [n for n in sorted(os.listdir(TEMPLATES))
           if n.endswith(".html") and not n.startswith("admin_")]
TEKSTEN = {n: open(os.path.join(TEMPLATES, n)).read() for n in PUBLIEK}
MAILS = lees("emailing.py")
TAAL = lees("paginataal.py")
ALLES = dict(TEKSTEN, **{"emailing.py": MAILS, "paginataal.py": TAAL})


def nergens(omschrijving, zin):
    """Deze zin hoort in geen enkele publieke tekst meer voor te komen."""
    gevonden = [naam for naam, tekst in ALLES.items() if zin.lower() in tekst.lower()]
    zo(omschrijving, gevonden, [])


print("\n== de vijf beloftes die niet waar waren ==")
nergens("wij versturen geen mail namens een klant", "sturen hem namens jou")
nergens("geen tweede tempo voor hetzelfde werk", "Wij voeren elke maand de verbeteringen uit")
nergens("de methodepagina doet ons niet tekort", "Op dit moment is dat ChatGPT")
nergens("en verderop ook niet", "Vandaag is dat ChatGPT")
nergens("geen extern cijfer zonder bron", "21.000 vermeldingen")
nergens("geen los percentage uit andermans onderzoek", "85% van wat AI over een merk zegt")
nergens("de Shopify-toegang wordt goed uitgelegd", "negentig dagen zonder inloggen")

print("\n== een model noemen betekent alle modellen noemen ==")
# Meten doen we bij ChatGPT EN Gemini. Noemt een zin over onze meting er maar
# een, dan klopt hij niet, ook al klinkt hij bescheidener.
#
# De uitzonderingen staan hieronder met reden. Komt er een nieuwe zin bij die
# alleen ChatGPT noemt, dan valt deze test om en moet je hem bewust toevoegen.
UITZONDERINGEN = (
    "chatgpt.com",        # een webadres in een artikel, geen belofte
    "vraagt aan chatgpt",  # de lezer die zelf iets vraagt
    "aan chatgpt vraagt",
    "does chatgpt mention",  # de kop van de Shopify-app
    "noemt chatgpt",         # de kop van de homepage
    "zitten er niet in",      # gaat over wat CONCURRENTEN niet meten, niet over ons
)
zinnen_fout = []
for naam, tekst in ALLES.items():
    kaal = re.sub(r"<[^>]+>", " ", tekst)
    for zin in re.split(r"(?<=[.!?])\s+", kaal):
        z = " ".join(zin.split())
        if "ChatGPT" not in z or "Gemini" in z:
            continue
        if not any(w in z.lower() for w in ("koopvra", "meten", "meting", "vragen aan",
                                            "genoemd")):
            continue
        if any(u in z.lower() for u in UITZONDERINGEN):
            continue
        zinnen_fout.append(f"{naam}: {z[:110]}")
zo("geen meetbelofte met maar een model erin", zinnen_fout, [])
for z in zinnen_fout:
    print("       " + z)

print("\n== de getallen op de site komen uit de code ==")
import scan_engine  # noqa: E402
import actieplan    # noqa: E402
import koopvragen   # noqa: E402
import inspect      # noqa: E402

bron = inspect.getsource(scan_engine.run_scan)
punten = bron.split("checks = [")[1].split("]")[0].count("check_")
zo("dertien controlepunten, en de site zegt dertien", punten, 13)
klopt("en dat getal staat ook echt op de site",
      "dertien" in TEKSTEN.get("zo-meten-we.html", "").lower())

zo("hoogstens drie acties per ronde", actieplan.MAX_ACTIES, 3)
klopt("en de site belooft er niet meer",
      "hoogstens drie" in TEKSTEN.get("index.html", "").lower())

standaard = inspect.signature(koopvragen.genereer_koopvragen).parameters["aantal"].default
zo("dertig koopvragen per winkel", standaard, 30)
klopt("en de site zegt dertig", "dertig" in TEKSTEN.get("faq.html", "").lower()
      or "30 koopvragen" in TEKSTEN.get("index.html", ""))

print("\n== wat er nooit beloofd mag worden ==")
# Hier is bewust nooit iets over beloofd en dat moet zo blijven. Niemand kan
# garanderen dat een AI-model een winkel gaat aanbevelen.
verboden = ("garanderen dat je genoemd", "gegarandeerd genoemd", "je wordt gegarandeerd",
            "verzekeren wij dat je", "altijd bovenaan")
for zin in verboden:
    nergens(f"geen resultaatgarantie: {zin!r}", zin)

klopt("en de methodepagina zegt met zoveel woorden dat we geen resultaat beloven",
      "beloven daarom geen resultaat" in TEKSTEN.get("zo-meten-we.html", ""))
klopt("de voorwaarden ook", "resultaatgarantie" in TEKSTEN.get("voorwaarden.html", ""))

print("\n== de mails beloven hetzelfde als de site ==")
klopt("de welkomstmail noemt de grens van drie ook in het engels",
      "at most three things a week" in MAILS)
klopt("en in het nederlands", "hoogstens drie dingen" in MAILS)
klopt("de opleveringsmail waarschuwt dat AI tijd nodig heeft",
      "voordat AI-modellen je nieuwe teksten hebben opgepikt" in " ".join(MAILS.split()))
klopt("de onderzoeksmail belooft alleen openbare informatie te gebruiken",
      "alleen openbare informatie van je website gebruikt en niets aan je site veranderd" in " ".join(MAILS.split()))

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
