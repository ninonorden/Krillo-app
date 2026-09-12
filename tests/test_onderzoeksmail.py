"""De onderzoeksmail: het kader mag het antwoord niet weggeven.

Waarom deze test bestaat.

Brevo liet op 12 september zien dat 45 procent van de ontvangers deze mail
opent, met nul spamklachten, en dat daarvan maar 8 procent doorklikt. De mail
komt dus aan en wordt gelezen. Wat er misging zat in de tekst: er stond
"genoemd bij 0 van de 5 vragen" in het kader, en daarmee wist de lezer genoeg.
Wie het antwoord al heeft, klikt niet.

Het kader zegt nu hetzelfde feit van de andere kant: er kwam WEL een winkel
uit, alleen niet die van jou. Welke, dat staat op de pagina. Deze test bewaakt
dat die volgorde blijft staan, want dit is precies het soort zin dat bij een
volgende bewerking ongemerkt terugdraait naar het oude.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import emailing  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


def klopt(omschrijving, voorwaarde):
    return zo(omschrijving, bool(voorwaarde), True)


verstuurd = {}


def nep_send_email(to_email, onderwerp, html, koppen=None, **rest):
    verstuurd.clear()
    verstuurd.update({"aan": to_email, "onderwerp": onderwerp,
                      "html": html, "koppen": koppen})
    return True


emailing.send_email = nep_send_email


VOORBEELD = {"vraag": "Waar koop ik online duurzame babykleding?",
             "winkels": ["Kleine Vos", "Bebe Natuur", "Groenhuis", "Wolwinkel"],
             "aantal": 4, "model": "ChatGPT",
             "na_klik_vragen": 15, "na_klik_modellen": 2}


def mail(**kwargs):
    grond = dict(to_email="winkel@voorbeeld.nl",
                 webshop_url="https://voorbeeldwinkel.nl",
                 uitkomst_url="https://www.krillo.nl/uitkomst/abc123",
                 afmeld_url="https://www.krillo.nl/afmelden/abc123")
    grond.update(kwargs)
    emailing.send_onderzoeksmail(**grond)
    return verstuurd["html"]


print("\n== Het woord koopvraag komt in geen enkele variant meer voor ==")
# Dat was ons woord en niet dat van de ontvanger. Wie het las moest eerst raden
# wat er gemeten was, en raden kost precies de twee seconden die deze mail heeft.
for geval in ({"genoemd": 0, "telbaar": 6}, {"genoemd": 3, "telbaar": 6},
              {"genoemd": 6, "telbaar": 6}, {},
              {"genoemd": 0, "telbaar": 6, "voorbeeld": VOORBEELD}):
    klopt(f"geen jargon bij {geval or 'een lege meting'}",
          "koopvraag" not in mail(**geval).lower())

print("\n== Nul keer genoemd: het kader gaat over de winkel die er wel uitkwam ==")
h = mail(genoemd=0, telbaar=5, nooit_genoemd=41, gemeten=75)
klopt("het kader begint bij de andere winkel, niet bij het cijfer",
      "Bij alle 5 vragen kwam er een andere winkel uit" in h)
klopt("en noemt de winkel zelf erbij", "voorbeeldwinkel.nl niet" in h)
klopt("het cijfer staat er nog wel, maar kleiner eronder",
      "Genoemd bij 0 van de 5 vragen" in h)
klopt("de vergelijking met de rest van de meting staat erbij",
      "van de 75 gemeten winkels werden er 41" in h)
klopt("de knop belooft wat alleen de pagina heeft",
      "Bekijk welke winkels er wel uitkwamen" in h)
klopt("de mail zegt niet dat de lijst in de mail staat",
      "staat op je eigen pagina" in h)

# Dit is de kern van de wijziging. Stond dit er nog, dan was het verhaal in de
# mail al af en had de pagina geen reden meer om bezocht te worden.
kader = h.split("Jouw uitkomst")[1].split("</table>")[0]
klopt("het kader opent niet met het aantal keer genoemd",
      kader.index("een andere winkel uit") < kader.index("Genoemd bij 0"))

print("\n== Deels genoemd: het gemiste deel staat voorop ==")
h = mail(genoemd=2, telbaar=5)
klopt("het aantal gemiste vragen klopt",
      "Bij 3 van de 5 vragen kwam er een andere winkel uit" in h)
klopt("het eigen cijfer staat eronder", "Genoemd bij 2 van de 5 vragen" in h)

print("\n== Overal genoemd: dan geen valse zorg, maar het echte verschil ==")
h = mail(genoemd=5, telbaar=5)
klopt("de mail erkent dat het goed staat",
      "werd bij alle 5 vragen genoemd" in h)
klopt("en legt uit waarom de pagina dan toch iets toevoegt",
      "Genoemd worden is niet hetzelfde als aanbevolen worden" in h)
klopt("geen verzonnen gemiste vragen",
      "kwam er een andere winkel uit" not in h)

print("\n== Zonder cijfers valt de mail niet om ==")
h = mail()
klopt("er staat een nette zin in plaats van een leeg kader",
      "meegenomen in de meting" in h)

print("\n== Wat er in elke onderzoeksmail hoort te staan ==")
h = mail(genoemd=0, telbaar=5)
klopt("de afmeldlink staat in de tekst", "/afmelden/abc123" in h)
klopt("en als kop, want dat scheelt spamklachten",
      verstuurd["koppen"].get("List-Unsubscribe") == "<https://www.krillo.nl/afmelden/abc123>")
klopt("de lezer ziet waar de link heen gaat voordat hij klikt",
      "De link gaat naar" in h)
klopt("KVK en adres staan eronder", "KVK" in h)
klopt("de onderwerpregel is ongewijzigd, die werkt",
      verstuurd["onderwerp"] == "voorbeeldwinkel.nl in ons onderzoek naar AI-antwoorden")

print("\n== De echte vraag in de mail, in plaats van uitleg ==")
h = mail(genoemd=0, telbaar=6, voorbeeld=VOORBEELD)
klopt("de vraag staat er letterlijk in",
      "Waar koop ik online duurzame babykleding?" in h)
klopt("met het model dat hem beantwoordde", "ChatGPT antwoordde met 4 winkels" in h)
klopt("de eerste winkel staat er", "Kleine Vos" in h)
klopt("de tweede ook", "Bebe Natuur" in h)
klopt("en de rest wordt geteld, niet opgesomd", "nog 2 andere winkels" in h)

# Dit is de reden dat er maar twee namen in staan. De hele lijst in de mail
# zetten betekent dat er niets meer te halen valt op de pagina.
klopt("de derde winkel staat er NIET in", "Groenhuis" not in h)
klopt("de vierde ook niet", "Wolwinkel" not in h)

klopt("de winkel van de lezer staat als enige met een kruis",
      "voorbeeldwinkel.nl stond er niet bij" in h)
klopt("en het patroon staat eronder",
      "Dat gebeurde bij alle 6 vragen die we stelden" in h)
klopt("de knop wijst naar de rest", "Bekijk de andere vragen" in h)

h = mail(genoemd=0, telbaar=6, nooit_genoemd=84, gemeten=101, voorbeeld=VOORBEELD)
klopt("de vergelijking met het hele onderzoek staat eronder",
      "van de 101 gemeten winkels werden er 84" in h)

h = mail(genoemd=2, telbaar=6, voorbeeld=VOORBEELD)
klopt("bij deels genoemd telt de slotregel het gemiste deel",
      "Dat gebeurde bij 4 van de 6 vragen" in h)

print("\n== Een voorbeeld met te weinig winkels wordt niet gebruikt ==")
# Een antwoord met een enkele winkel is geen patroon maar een uitschieter, en
# dan valt de mail terug op de tekst zonder voorbeeld.
mager = dict(VOORBEELD, winkels=["Kleine Vos"], aantal=1)
h = mail(genoemd=0, telbaar=6, voorbeeld=mager)
klopt("de vraag staat er niet in", "duurzame babykleding" not in h)
klopt("het gewone kader staat er wel", "Jouw uitkomst" in h)

print("\n== De belofte over de vervolgmeting klopt met de instellingen ==")
# Hier stond ooit "vijftien vragen aan twee modellen" vast in de tekst, terwijl
# beide getallen in Render ingesteld worden. Nu komen ze mee.
h = mail(genoemd=0, telbaar=6, voorbeeld=VOORBEELD)
klopt("het aantal vragen komt uit de instelling",
      "15 vragen in plaats van 6" in h)
klopt("en het aantal modellen uit de sleutels die er echt zijn",
      "bij 2 modellen in plaats van een" in h)

h = mail(genoemd=0, telbaar=6, voorbeeld=dict(VOORBEELD, na_klik_modellen=1))
klopt("met een model wordt er niets over modellen beloofd",
      "modellen in plaats van" not in h)
klopt("maar de grotere meting nog wel", "15 vragen in plaats van 6" in h)

h = mail(genoemd=0, telbaar=6, voorbeeld=dict(VOORBEELD, na_klik_vragen=6))
klopt("is de vervolgmeting niet groter, dan staat er geen belofte",
      "in plaats van" not in h)

h = mail(genoemd=0, telbaar=6, voorbeeld=dict(VOORBEELD, na_klik_vragen=None,
                                              na_klik_modellen=None))
klopt("zonder getallen belooft de mail niets over een vervolg",
      "grotere meting" not in h)

print("\n== Zonder adres of link gaat er niets uit ==")
verstuurd.clear()
zo("geen adres, geen mail",
   emailing.send_onderzoeksmail("", "https://voorbeeldwinkel.nl", "https://x/y"), False)
zo("geen uitkomstlink, geen mail",
   emailing.send_onderzoeksmail("a@b.nl", "https://voorbeeldwinkel.nl", ""), False)
klopt("en er is niets verstuurd", verstuurd == {})

print()
if fouten:
    for f in fouten:
        print(f)
    print(f"\n{len(fouten)} fout(en)")
    sys.exit(1)
print("Alles goed.")
