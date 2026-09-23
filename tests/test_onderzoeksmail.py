"""De onderzoeksmail: de positie in de index, in het Engels (stap 36).

WAAROM DEZE TEST BESTAAT

Tot 23 september was dit de laatste mail uit het oude model: Nederlands, met
een eigen meting van de winkel ("genoemd bij 0 van de 5 vragen") en een link
naar een eigen uitkomstpagina. De site zegt inmiddels iets anders: "je
positie in de index". Een koude mail die een ander cijfer noemt dan de
openbare ranglijst is precies het soort tegenspraak waardoor iemand denkt dat
het oplichterij is.

Deze test bewaakt:
- het cijfer in de mail is de positie uit de index, met categorie en land;
- de mail is Engels, zonder ons eigen jargon;
- platforms staan nooit als "in plaats van jou" (bol.com is geen concurrent);
- namen van buiten worden onschadelijk gemaakt;
- zonder positie gaat er GEEN mail uit;
- afmeldlink, afmeldkop, KVK en "waar gaat de link heen" staan er altijd.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import emailing  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


verstuurd = {}


def nep_send_email(to_email, onderwerp, html, koppen=None, **rest):
    verstuurd.clear()
    verstuurd.update({"aan": to_email, "onderwerp": onderwerp,
                      "html": html, "koppen": koppen})
    return True


emailing.send_email = nep_send_email

BEELD = {
    "positie": 7, "van": 24, "genoemd": 3, "telbaar": 30, "aanbevolen": 1,
    "categorie": "babykleding", "land": "nl",
    "boven_mij": [{"positie": 5, "naam": "Groenhuis", "webshop_url": "https://groenhuis.nl"},
                  {"positie": 6, "naam": "https://bebe-natuur.nl",
                   "webshop_url": "https://bebe-natuur.nl"}],
    "gemiste_vragen": [
        {"vraag": "Where can I buy organic baby clothes online?",
         "concurrenten": ["Kleine Vos", "Wolwinkel", "Derde Winkel"],
         "platforms": ["bol.com"]},
    ],
}


def mail(beeld=BEELD, **kw):
    grond = dict(to_email="winkel@voorbeeld.nl", webshop_url="https://voorbeeldwinkel.nl",
                 link_url="https://krilloai.com/uitkomst/abc123", beeld=beeld,
                 categorienaam="Baby clothes", landnaam="the Netherlands",
                 afmeld_url="https://krilloai.com/afmelden/abc123")
    grond.update(kw)
    verstuurd.clear()
    uit = emailing.send_onderzoeksmail(**grond)
    return uit, verstuurd.get("html", "")


print("\n== HET CIJFER IS DE POSITIE IN DE INDEX ==")
ok, h = mail()
klopt("de mail gaat uit", ok)
klopt("de positie staat erin", "#7 of 24" in h)
klopt("met categorie en land", "Your place in Baby clothes, the Netherlands" in h)
klopt("per vraag geteld", "in 3 of 30 buying questions" in h)
klopt("wie net boven hem staat, nooit als webadres",
      "Just ahead of you: bebe-natuur.nl (#6)" in h and "https://bebe-natuur.nl" not in h)
klopt("de onderwerpregel noemt de positie",
      verstuurd["onderwerp"] == "voorbeeldwinkel.nl: #7 of 24 in the Krillo index")

print("\n== ENGELS, ZONDER OUDE ZINNEN ==")
for oud in ("Genoemd bij", "Jouw uitkomst", "onderzoek naar", "koopvraag", "Bekijk",
            "Met vriendelijke groet", "vragen in plaats van"):
    klopt(f"geen {oud!r}", oud.lower() not in h.lower())
klopt("de knop zegt waar hij heen gaat", "See the full ranking" in h)

print("\n== EEN ECHTE VRAAG, ALLEEN MET WINKELS ==")
klopt("de vraag staat erin", "Where can I buy organic baby clothes online?" in h)
klopt("twee winkels", "Kleine Vos" in h and "Wolwinkel" in h)
klopt("niet de hele lijst", "Derde Winkel" not in h)
klopt("de eigen winkel met een kruis", "voorbeeldwinkel.nl was not named" in h)
klopt("bol.com staat er NIET als concurrent in", "bol.com" not in h)

print("\n== ALLEEN PLATFORMS BIJ DE VRAAG: DAN GEEN VOORBEELD ==")
alleen_platform = dict(BEELD, gemiste_vragen=[
    {"vraag": "Cheap baby clothes?", "concurrenten": [], "platforms": ["bol.com"]}])
ok, h = mail(beeld=alleen_platform)
klopt("de mail gaat wel uit", ok)
klopt("zonder voorbeeldvraag", "Cheap baby clothes?" not in h and "One of the questions" not in h)

print("\n== NUL KEER GENOEMD ==")
ok, h = mail(beeld=dict(BEELD, genoemd=0, positie=24))
klopt("eerlijk gezegd", "in none of the 30 buying questions" in h)

print("\n== NAMEN VAN BUITEN WORDEN ONSCHADELIJK ==")
kwaad = dict(BEELD, gemiste_vragen=[
    {"vraag": "<script>x</script>", "concurrenten": ['<a href="http://kwaad">Win</a>', "B"],
     "platforms": []}])
ok, h = mail(beeld=kwaad)
klopt("geen script", "<script>" not in h)
klopt("geen vreemde link", 'href="http://kwaad"' not in h)

print("\n== WAT ER IN ELKE KOUDE MAIL HOORT ==")
ok, h = mail()
klopt("de afmeldlink staat in de tekst", "/afmelden/abc123" in h)
klopt("en als kop, want dat scheelt spamklachten",
      verstuurd["koppen"].get("List-Unsubscribe") == "<https://krilloai.com/afmelden/abc123>")
klopt("de lezer ziet waar de link heen gaat", "The link goes to krilloai.com" in h)
klopt("KVK en adres staan eronder", "KVK" in h)
klopt("en waarom hij deze mail krijgt", "your store is in the Krillo index" in h)

print("\n== ZONDER POSITIE GAAT ER NIETS UIT ==")
for omschrijving, kw in [("geen beeld", {"beeld": None}),
                         ("beeld zonder positie", {"beeld": dict(BEELD, positie=None)}),
                         ("geen adres", {"to_email": ""}),
                         ("geen link", {"link_url": ""})]:
    ok, h = mail(**kw)
    klopt(f"{omschrijving}: geen mail", ok is False and verstuurd == {})

print("\n== DE AANROEP HAALT DE POSITIE UIT DE INDEX ==")
bron = lees("app.py")
i = bron.index("def _stuur_onderzoeksmail(")
blok = bron[i:bron.index("\ndef ", i + 10)]
klopt("via klantbeeld.bouw", "klantbeeld.bouw(" in blok)
klopt("zonder positie een eigen reden", "GEEN_POSITIE" in blok)
klopt("de uitkomstlink stuurt door naar de ranglijst",
      '#p{beeld[\'positie\']}' in bron and "def uitkomst(token)" in bron)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de koude mail noemt de positie uit de index, in het Engels.")
