"""Stap 73: een platform is geen concurrent.

WAAROM DEZE TEST BESTAAT

Nino deed op 21 september de gratis test op brixt.nl, een makelaarssite. Onder
"wie er wel genoemd werd" stonden Pararius, Funda en Kamernet. Dat zijn geen
concurrenten van een makelaar: het zijn portalen waar een makelaar juist op
hoort te staan. Zijn woorden: "pararius zou niet een webshop zijn bij wijze van
spreken". Bij winkels is het net zo met bol.com, Marktplaats of Kieskeurig.

Waarom dat erger is dan een cosmetisch foutje:
- het leest als "je verliest van Pararius", terwijl er iets anders aan de hand
  is: AI stuurt kopers naar een platform waar jij nog niet goed op staat;
- in de index zou een platform een positie innemen in een RANGLIJST VAN
  WINKELS, en dan klopt de nummer 1 niet meer.

Deze test bewaakt dat het leesmodel het verschil moet maken, dat een platform
niet in de ranglijst belandt, en dat de mail en de pagina twee lijstjes tonen.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["BREVO_API_KEY"] = "test"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import beoordeling  # noqa: E402
import categoriemeting  # noqa: E402
import emailing  # noqa: E402
import opschonen  # noqa: E402
import zichtbaarheid  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


print("\n== DE LEESOPDRACHT VRAAGT OM HET VERSCHIL ==")
for naam, prompt in (("de categoriemeting", categoriemeting._PROMPT_SJABLOON),
                     ("de meting per winkel", beoordeling.PROMPT
                      if hasattr(beoordeling, "PROMPT") else lees("beoordeling.py")),
                     ("het opschonen", lees("opschonen.py"))):
    laag = prompt.lower()
    klopt(f"{naam}: legt platform uit", "platform" in laag)
    klopt(f"{naam}: met voorbeelden die het duidelijk maken",
          "pararius" in laag or "marktplaats" in laag or "kieskeurig" in laag)

print("\n== HET LEESMODEL MAG MAAR TWEE DINGEN ZEGGEN ==")
# Wat het model ook terugstuurt, er komt "winkel" of "platform" uit. Alles
# wat wij niet kennen telt als winkel, zoals het hiervoor altijd ging.
neppe = {"winkel_kon_genoemd": True,
         "winkels": [{"naam": "Pararius", "adres": "pararius.nl", "positie": 1,
                      "soort": "PLATFORM"},
                     {"naam": "Mijn Winkel", "adres": "mijnwinkel.nl", "positie": 2,
                      "soort": "winkel"},
                     {"naam": "Derde", "adres": "derde.nl", "positie": 3,
                      "soort": "onzin"}],
         "aanbevolen": []}
categoriemeting._lees_met = lambda lezer, prompt: neppe
uit = categoriemeting.winkels_uit_antwoord("v", "a")
soorten = {w["naam"]: w["soort"] for w in uit["winkels"]}
klopt(f"Pararius is een platform (kreeg {soorten})", soorten.get("Pararius") == "platform")
klopt("een winkel blijft een winkel", soorten.get("Mijn Winkel") == "winkel")
klopt("en onzin telt als winkel, niet als platform", soorten.get("Derde") == "winkel")

print("\n== EEN PLATFORM KOMT NIET IN DE RANGLIJST ==")
gezet = {}
toegevoegd_urls = []
categoriemeting.db.voeg_benadering_toe = lambda url, naam=None, land=None, branche=None: (
    toegevoegd_urls.append(url) or True)
categoriemeting.db.zet_categorie = lambda url, slug: True
categoriemeting.db.zet_soorten = lambda per_url: gezet.update(per_url) or True
# Met de GELEZEN uitvoer, want zo komt het in de echte keten binnen: eerst
# winkels_uit_antwoord, dan pas dit.
nieuw = categoriemeting.nieuwe_winkels_uit_antwoorden(
    [dict(uit, winkel_kon_genoemd=True)], [], "makelaars", bestaat=lambda d: True)
klopt(f"de winkels komen erbij (kreeg {nieuw})",
      "https://mijnwinkel.nl" in nieuw and "https://derde.nl" in nieuw)
klopt("het platform niet", "https://pararius.nl" not in nieuw)
klopt("maar wij raken hem ook niet kwijt: hij staat er als platform",
      gezet.get("https://pararius.nl") == "platform")
klopt("en de meetwachtrij kijkt alleen naar winkels",
      "b.soort = 'winkel'" in lees("db.py"))
klopt("het opschonen kent platform als soort", opschonen.SOORT_PLATFORM == "platform")

print("\n== HET BEELD VAN DE KLANT SPLITST ZE ==")
beoordelingen = [
    {"vraag": "hoe vind ik een huurwoning?", "winkel_kon_genoemd": True, "model": "gpt",
     "genoemd": False, "aanbevolen": False, "sterkte": 0,
     "winkels": [{"naam": "Pararius", "soort": "platform"},
                 {"naam": "Makelaar Jansen", "soort": "winkel"}],
     "aanbevolen_winkels": []},
    {"vraag": "welke makelaar in Amsterdam?", "winkel_kon_genoemd": True, "model": "gpt",
     "genoemd": False, "aanbevolen": False, "sterkte": 0,
     "winkels": [{"naam": "Pararius", "soort": "platform"},
                 {"naam": "Makelaar Jansen", "soort": "winkel"}],
     "aanbevolen_winkels": ["Makelaar Jansen"]},
]
beeld = beoordeling.klantbeeld("https://brixt.nl", beoordelingen)
per_naam = {c["naam"]: c for c in beeld["concurrenten"]}
klopt("Pararius is gemarkeerd als platform", per_naam.get("Pararius", {}).get("platform") is True)
klopt("de makelaar niet", per_naam.get("Makelaar Jansen", {}).get("platform") is False)

kort = zichtbaarheid._inkorten(beeld)
klopt("in de uitslag staan platforms apart",
      [p["naam"] for p in kort.get("platforms", [])] == ["Pararius"])
klopt("en niet meer tussen de concurrenten",
      "Pararius" not in [c["naam"] for c in kort["concurrenten"]])
klopt("de makelaar staat er wel bij",
      "Makelaar Jansen" in [c["naam"] for c in kort["concurrenten"]])

print("\n== DE MAIL TOONT TWEE LIJSTJES ==")
gevangen = []
emailing.send_email = lambda naar, onderwerp, html, koppen=None: (
    gevangen.append(html) or True)
uitslag = dict(kort, gesteld=5, telbaar=2, genoemd=0, aanbevolen=0,
               modellen=["ChatGPT"], regels=[])
emailing.send_zichtbaarheidstest("a@b.nl", "https://brixt.nl", uitslag, "zin",
                                 "https://krilloai.com")
h = gevangen[-1]
klopt("er staat een kop voor winkels", "Who was named instead" in h)
klopt("en een aparte kop voor platforms", "Platforms AI points buyers to" in h)
klopt("met uitleg dat het geen concurrenten zijn", "not competitors" in h)
klopt("Pararius staat onder de platforms, niet bij de winkels",
      h.index("Platforms AI points buyers to") < h.index("Pararius"))

print("\n== EN DE PAGINA OOK ==")
pagina = lees("templates/index.html")
klopt("de pagina kent de lijst platforms", "r.platforms" in pagina)
klopt("met dezelfde kop", "Platforms AI points buyers to" in pagina)
klopt("en zet platforms niet meer tussen de concurrenten",
      "!c.wij && !c.platform" in pagina)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: een platform is geen concurrent meer.")
