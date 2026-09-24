"""De voorbeeldvraag in de koude mail past bij wat de winkel verkoopt.

WAAROM DEZE TEST BESTAAT

24 september: keekabuu.com kreeg een mail met de vraag "Welke Nederlandse
webshop verkoopt betrouwbare kinderwagens?" en "keekabuu.com was not named".
Keekabuu verkoopt geen kinderwagens. De vraag hoorde bij de categorie, niet bij
de winkel, en zo leest de mail als een machine die niet kijkt. Nu wordt per
winkel de vraag gekozen die past, en past er geen, dan geen vraag.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
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


import vraagkeuze  # noqa: E402
import categoriemeting  # noqa: E402
import kosten  # noqa: E402

kosten.registreer_aanroep = lambda **k: None
vraagkeuze.db.get_winkelprofiel = lambda url: None
HOMEPAGE = ('<html><head><title>Keekabuu | Duurzame babykleding en slaapzakken</title>'
            '<meta name="description" content="Biologische babykleding, rompers en '
            'slaapzakken voor je kleintje."></head><body><h1>Babykleding</h1></body></html>')
GEMIST = [{"vraag": "Welke Nederlandse webshop verkoopt betrouwbare kinderwagens?",
           "concurrenten": ["Babypark"]},
          {"vraag": "waar koop ik biologische babykleding online", "concurrenten": ["Petit Bateau"]},
          {"vraag": "beste webshop voor een babyslaapzak", "concurrenten": ["Lodger"]}]

print("\n== WAT DE WINKEL VERKOOPT ==")
tekst = vraagkeuze.wat_verkoopt("https://keekabuu.com", ophalen=lambda u: HOMEPAGE)
klopt("uit titel en omschrijving van de homepage", "babykleding" in tekst.lower()
      and "slaapzakken" in tekst.lower())
vraagkeuze.db.get_winkelprofiel = lambda url: {"omschrijving": "Wij verkopen speelgoed van hout."}
klopt("ons eigen winkelprofiel gaat voor", vraagkeuze.wat_verkoopt("https://x.nl") ==
      "Wij verkopen speelgoed van hout.")
vraagkeuze.db.get_winkelprofiel = lambda url: None

print("\n== MET HET MODEL ==")


class _Antw:
    def __init__(self, tekst):
        self.content = [type("B", (), {"text": tekst})()]
        self.usage = type("U", (), {"input_tokens": 50, "output_tokens": 5})()


class _Model:
    antwoord = '{"passend": [1, 2]}'

    class messages:  # noqa: N801
        @staticmethod
        def create(**k):
            _Model.prompt = k["messages"][0]["content"]
            return _Antw(_Model.antwoord)


categoriemeting._client = lambda: _Model()
uit = vraagkeuze.passende_vragen("https://keekabuu.com", GEMIST, ophalen=lambda u: HOMEPAGE)
klopt("de kinderwagenvraag valt af", all("kinderwagens" not in g["vraag"] for g in uit))
klopt("de passende vragen blijven, beste eerst",
      [g["concurrenten"][0] for g in uit] == ["Petit Bateau", "Lodger"])
klopt("het model kreeg de omschrijving mee", "Duurzame babykleding" in _Model.prompt)
_Model.antwoord = '{"passend": []}'
klopt("past er geen, dan geen vraag",
      vraagkeuze.passende_vragen("https://keekabuu.com", GEMIST, ophalen=lambda u: HOMEPAGE) == [])
_Model.antwoord = '{"passend": [7, "x", 1, 1]}'
klopt("onzin uit het model wordt genegeerd",
      len(vraagkeuze.passende_vragen("https://keekabuu.com", GEMIST, ophalen=lambda u: HOMEPAGE)) == 1)

print("\n== ZONDER MODEL ==")
categoriemeting._client = lambda: None
uit = vraagkeuze.passende_vragen("https://keekabuu.com", GEMIST, ophalen=lambda u: HOMEPAGE)
klopt("dan op woorden: babykleding past, kinderwagens niet",
      [g["concurrenten"][0] for g in uit] == ["Petit Bateau"])
klopt("weten wij niets van de winkel, dan geen vraag",
      vraagkeuze.passende_vragen("https://onbekend.nl", GEMIST, ophalen=lambda u: "") == [])

print("\n== DE MAIL GEBRUIKT HET ==")
bron = lees("app.py")
klopt("de mail kiest de vraag per winkel", "vraagkeuze.passende_vragen(" in bron)
klopt("uit een ruimere lijst", "max_vragen=20)" in bron)
import emailing  # noqa: E402
verstuurd = []
emailing.send_email = lambda to, onderwerp, html, **k: verstuurd.append(html) or True
emailing.send_onderzoeksmail("a@b.nl", "https://keekabuu.com", "https://krilloai.com/uitkomst/t",
                             beeld={"positie": 15, "van": 17, "genoemd": 0, "telbaar": 30,
                                    "land": "nl", "categorie": "baby", "gemiste_vragen": []},
                             categorienaam="Babyspullen en verzorging", landnaam="the Netherlands")
klopt("zonder passende vraag gaat de mail zonder voorbeeld, wel met de plek",
      "#15 of 17" in verstuurd[-1] and "questions we asked" not in verstuurd[-1])

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de voorbeeldvraag past bij de winkel.")
