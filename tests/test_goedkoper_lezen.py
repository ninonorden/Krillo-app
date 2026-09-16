"""Het lezen van antwoorden door een goedkoper model.

WAAROM DIT ERTOE DOET

Een categorie meten is dertig vragen aan twee modellen, dus zestig antwoorden,
en elk antwoord moet gelezen worden. Het stellen van de vraag kunnen wij niet
goedkoper maken, want dat is precies wat wij meten: wat ChatGPT en Gemini
antwoorden. Het lezen wel. Dat is een leesopdracht met een vast format eruit,
en daar is geen duur model voor nodig.

Op 14 september kostte een winkel ongeveer 35 cent per maand, en het leeswerk
was daarvan het grootste deel.

WAAROM DIT TEGELIJK RISICOVOL IS

Een goedkoper model dat een winkel over het hoofd ziet, kost een klant zijn
positie in een openbare ranglijst. Dat is erger dan een paar cent duurder
meten. Daarom:

- Het leesmodel staat in een omgevingsvariabele, dus terugzetten kan zonder
  nieuwe versie.
- Ontbreekt de sleutel van het goedkope model, dan valt hij terug op het dure.
  Stil niets meten zou veel erger zijn dan iets duurder meten.
- Er is een vergelijking die beide modellen over dezelfde AL BEWAARDE antwoorden
  laat lopen. Geen enkele vraag wordt opnieuw gesteld, dus die vergelijking kost
  een paar cent.
- De vergelijking geeft pas groen licht bij 95 procent overeenstemming over de
  vraag of een antwoord meetelt, en 90 procent over welke winkels erin staan.

Wat hier bewaakt wordt, is die machinerie. Of het goedkope model in de praktijk
goed genoeg is, kan een test zonder echte sleutels niet uitmaken; dat moet de
vergelijking op de echte data zeggen.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import db               # noqa: E402
import categoriemeting  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== de leesopdracht is er maar een ==")
# Het sjabloon moet gedeeld worden. Zouden de meting en de vergelijking elk hun
# eigen opdracht hebben, dan vergelijk je twee modellen op twee verschillende
# vragen en zegt de uitkomst niets.
prompt = categoriemeting._leesprompt("Waar koop ik emaille servies?",
                                     "Kijk eens bij fonQ en bij Flinders.")
klopt("de vraag staat erin", "Waar koop ik emaille servies?" in prompt)
klopt("het antwoord staat erin", "Flinders" in prompt)
klopt("het gevraagde format staat erin", '"winkel_kon_genoemd"' in prompt)
klopt("het verschil tussen merk en winkel staat erin",
      "merk" in prompt.lower() and "winkel" in prompt.lower())
klopt("het verschil tussen genoemd en aanbevolen staat erin",
      "aanbevolen" in prompt.lower())

print("\n== welk model leest ==")
bron = open(os.path.join(APP, "categoriemeting.py")).read()
klopt("het leesmodel is in te stellen zonder nieuwe versie", "LEES_MODEL" in bron)
# De standaard moet het DURE model zijn. Zou het goedkope model vanzelf aangaan
# bij een nieuwe versie, dan verandert stilletjes de meetkwaliteit van iedereen
# die al in een ranglijst staat, zonder dat iemand het gezien heeft.
zo("de standaard is het dure model", categoriemeting.LEES_PROVIDER, "anthropic")
zo("en niet iets goedkoops", categoriemeting.LEES_MODEL, categoriemeting.MODEL)

oude = dict(os.environ)
oude_provider, oude_model = categoriemeting.LEES_PROVIDER, categoriemeting.LEES_MODEL
try:
    for sleutel in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(sleutel, None)
    categoriemeting.LEES_PROVIDER = "openai"
    categoriemeting.LEES_MODEL = "gpt-5.6-luna"
    zo("zonder de sleutel van het goedkope model valt hij terug op het dure",
       categoriemeting._lezer()["provider"], "anthropic")
    zo("en dus op het dure model", categoriemeting._lezer()["model"],
       categoriemeting.MODEL)
    os.environ["OPENAI_API_KEY"] = "test"
    zo("mét die sleutel leest het goedkope model",
       categoriemeting._lezer()["model"], "gpt-5.6-luna")
finally:
    categoriemeting.LEES_PROVIDER, categoriemeting.LEES_MODEL = oude_provider, oude_model
    os.environ.clear()
    os.environ.update(oude)

print("\n== de vergelijking, met nagemaakte modellen ==")
db.init_db()
CAT = "test-goedkoop"


# Twee echte winkels in deze categorie. Zonder die kan de vergelijking niet
# meten wat er werkelijk toe doet, want dan is "onze winkels" bij beide modellen
# leeg en zijn ze het dus altijd eens.
ONZE = ["https://fonq.nl", "https://flinders.nl"]


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (ONZE,))
    conn.close()


opruimen()
for url in ONZE:
    db.voeg_benadering_toe(url, naam=url.split("//")[1].split(".")[0],
                           land="NL", branche="test")
    db.zet_categorie(url, CAT)
for nummer, (vraag, antwoord) in enumerate([
        ("Waar koop ik servies?", "Kijk bij fonQ en Flinders."),
        ("Welk merk servies is goed?", "Serax en Ferm Living maken mooi servies."),
        ("Waar koop ik wijnglazen?", "Bij Dille en Kamille of bij fonQ.")], start=1):
    db.bewaar_categorie_antwoord(1, CAT, vraag, "gpt-test", antwoord,
                                 {"winkel_kon_genoemd": True, "winkels": [],
                                  "aanbevolen": []})

bewaard = db.bewaarde_antwoorden(CAT, 10)
zo("de antwoorden staan er nog", len(bewaard), 3)

echte_lees = categoriemeting._lees_met
aanroepen = {"n": 0}


def eens(aanbieder, prompt):
    # Beide modellen zien hetzelfde.
    aanroepen["n"] += 1
    return {"winkel_kon_genoemd": True,
            "winkels": [{"naam": "fonQ", "positie": 1}], "aanbevolen": ["fonQ"]}


def oneens(aanbieder, prompt):
    aanroepen["n"] += 1
    if aanbieder["model"] == categoriemeting.MODEL:
        return {"winkel_kon_genoemd": True,
                "winkels": [{"naam": "fonQ", "positie": 1},
                            {"naam": "Flinders", "positie": 2}],
                "aanbevolen": ["fonQ"]}
    return {"winkel_kon_genoemd": False, "winkels": [], "aanbevolen": []}


def alleen_vreemde_naam_erbij(aanbieder, prompt):
    """Het goedkope model ziet een winkel extra die NIET van ons is.

    Dit is precies het geval waarop de eerste versie van deze vergelijking
    onterecht rood gaf: de namenlijsten verschillen, maar er verandert geen
    letter in onze ranglijst."""
    aanroepen["n"] += 1
    basis = [{"naam": "Kookhuis", "positie": 1}]
    if aanbieder["model"] != categoriemeting.MODEL:
        basis.append({"naam": "Een Belgische Winkel Die Wij Niet Volgen", "positie": 2})
    return {"winkel_kon_genoemd": True, "winkels": basis, "aanbevolen": ["Kookhuis"]}


try:
    categoriemeting._lees_met = eens
    uit = categoriemeting.vergelijk_lezers(CAT, aantal=3)
    zo("drie antwoorden bekeken", uit["bekeken"], 3)
    zo("zes aanroepen, twee per antwoord", aanroepen["n"], 6)
    zo("altijd eens over meetellen", uit["aandeel_meetellen"], 1.0)
    zo("altijd eens over de winkels", uit["aandeel_winkels"], 1.0)
    klopt("dus groen licht", uit["mag_over"])
    klopt("en geen verschillen te melden", uit["verschillen"] == [])

    aanroepen["n"] = 0
    categoriemeting._lees_met = oneens
    uit = categoriemeting.vergelijk_lezers(CAT, aantal=3)
    zo("nooit eens over meetellen", uit["aandeel_meetellen"], 0.0)
    zo("nooit eens over de winkels", uit["aandeel_winkels"], 0.0)
    zo("en ook niet over onze winkels", uit["aandeel_onze_winkels"], 0.0)
    klopt("dus geen groen licht", uit["mag_over"] is False)
    klopt("en de verschillen staan erbij", len(uit["verschillen"]) == 3)
    klopt("met welke van onze winkels het dure model wel zag",
          any("flinders" in u for u in uit["verschillen"][0]["alleen_duur"]))

    print("\n== een extra winkel die niet van ons is telt NIET als afkeuring ==")
    # Op 16 september gaf de echte vergelijking 60% op de namenlijst en dus rood,
    # terwijl er in onze ranglijst mogelijk niets veranderde. Dat was te streng
    # gemeten. Het cijfer dat telt gaat alleen over onze eigen winkels.
    aanroepen["n"] = 0
    categoriemeting._lees_met = alleen_vreemde_naam_erbij
    uit = categoriemeting.vergelijk_lezers(CAT, aantal=3)
    zo("de namenlijsten verschillen altijd", uit["aandeel_winkels"], 0.0)
    zo("maar over onze winkels zijn ze het altijd eens",
       uit["aandeel_onze_winkels"], 1.0)
    klopt("en dus is er groen licht", uit["mag_over"])

    print("\n== een leesfout telt als mislukt, niet als niets gevonden ==")
    categoriemeting._lees_met = lambda a, p: None
    categoriemeting._laatste_leesfout = "gemini-test: tokengrens bereikt"
    uit = categoriemeting.vergelijk_lezers(CAT, aantal=3)
    zo("niets bekeken", uit["bekeken"], 0)
    zo("drie keer mislukt", uit["mislukt"], 3)
    klopt("en geen groen licht op basis van nul metingen", "mag_over" not in uit)
    # Zonder de echte reden sta je te raden, en dat kostte op 16 september een
    # halve middag. De fout moet dus mee terug naar het scherm.
    klopt("de echte reden staat erbij",
          "tokengrens bereikt" in " ".join(uit["leesfouten"]))
    zo("en niet honderd keer dezelfde regel", len(uit["leesfouten"]), 1)
finally:
    categoriemeting._lees_met = echte_lees

print("\n== een model met zichzelf vergelijken wordt geweigerd ==")
zelfde = {"provider": "anthropic", "model": categoriemeting.MODEL}
uit = categoriemeting.vergelijk_lezers(CAT, aantal=3, goedkoop=zelfde, duur=zelfde)
klopt("dat levert een fout op en geen honderd procent", "fout" in uit)
klopt("en geen groen licht", "mag_over" not in uit)

print("\n== de kandidaat staat los van het huidige model ==")
klopt("er is een kandidaatmodel", categoriemeting.KANDIDAAT_MODEL)
klopt("en dat is niet het huidige",
      categoriemeting.KANDIDAAT_MODEL != categoriemeting.LEES_MODEL)

print("\n== er is meer dan een kandidaat om te proberen ==")
# Valt er een af, dan moet er een volgende getest kunnen worden zonder nieuwe
# versie. Anders staat het hele plan stil op een modelnaam.
klopt("er staan meerdere kandidaten klaar", len(categoriemeting.KANDIDATEN) >= 3)
klopt("elk met een provider en een model",
      all(k.get("provider") and k.get("model") and k.get("toonnaam")
          for k in categoriemeting.KANDIDATEN))
klopt("en geen enkele is het dure model",
      all(k["model"] != categoriemeting.MODEL for k in categoriemeting.KANDIDATEN))
sjabloon = open(os.path.join(APP, "templates", "admin_ranglijst.html")).read()
klopt("je kunt het model kiezen op de pagina", 'name="kandidaat"' in sjabloon)
klopt("en je kunt ook zelf een naam intypen", 'name="eigen_model"' in sjabloon)
klopt("met een verwijzing naar de echte modelnamen", "/admin/modellen" in sjabloon)

print("\n== een zelf ingetypte modelnaam wordt herkend ==")
# Op 16 september mislukten alle tien de leespogingen omdat de modelnaam die ik
# uit mijn hoofd had opgeschreven niet bestond onder deze sleutel. Namen
# verschillen per aanbieder en per account, dus intypen moet kunnen.
zo("gpt hoort bij openai",
   categoriemeting.kandidaat_uit_naam("gpt-4.1-mini")["provider"], "openai")
zo("gemini bij google",
   categoriemeting.kandidaat_uit_naam("gemini-2.0-flash")["provider"], "google")
zo("claude bij anthropic",
   categoriemeting.kandidaat_uit_naam("claude-haiku-4")["provider"], "anthropic")
zo("en de naam blijft ongewijzigd",
   categoriemeting.kandidaat_uit_naam("gemini-2.0-flash")["model"], "gemini-2.0-flash")
zo("met een dubbele punt kun je de aanbieder zelf zeggen",
   categoriemeting.kandidaat_uit_naam("google:iets-nieuws"),
   {"provider": "google", "model": "iets-nieuws"})
klopt("een lege invoer levert niets op",
      categoriemeting.kandidaat_uit_naam("") is None)
klopt("en een naam die nergens op lijkt ook niet",
      categoriemeting.kandidaat_uit_naam("zomaar-iets") is None)
klopt("en het beslissende cijfer staat erop", "aandeel_onze_winkels" in sjabloon)

print("\n== de vergelijking laat zien hoe ver hij is ==")
# Op 16 september stond er tien minuten lang alleen "bezig met vergelijken".
# Een scherm dat alleen "bezig" zegt is niet te onderscheiden van een scherm
# dat vastzit, en dan ga je op knoppen drukken die geld kosten.
import time as _t  # noqa: E402
categoriemeting._vgl_stand.update({"bezig": True, "nu": 3, "totaal": 6,
                                   "gestart_op": _t.time() - 90})
st = categoriemeting.vergelijkstand()
zo("hij weet bij welk antwoord hij is", st["nu"], 3)
zo("en hoeveel er in totaal zijn", st["totaal"], 6)
klopt("en hoe lang hij bezig is", "minuten" in st["verstreken"])
klopt("na anderhalve minuut is hij nog niet vastgelopen", st["vastgelopen"] is False)

categoriemeting._vgl_stand["gestart_op"] = _t.time() - (categoriemeting.VASTGELOPEN_NA_SECONDEN + 60)
klopt("maar na de grens wel", categoriemeting.vergelijkstand()["vastgelopen"])
klopt("en dan mag je opnieuw beginnen",
      categoriemeting.start_vergelijking("bestaat-niet", aantal=1) is True)
_t.sleep(0.4)
categoriemeting._vgl_stand.update({"bezig": False, "gestart_op": None,
                                   "nu": 0, "totaal": 0})

print("\n== een vergelijking die te lang duurt wordt afgekapt ==")
echte_max = categoriemeting.MAX_VERGELIJK_SECONDEN
echte_lees2 = categoriemeting._lees_met
try:
    categoriemeting.MAX_VERGELIJK_SECONDEN = 0
    categoriemeting._lees_met = lambda a, p: {"winkel_kon_genoemd": True,
                                              "winkels": [], "aanbevolen": []}
    uit = categoriemeting.vergelijk_lezers(CAT, aantal=3)
    zo("er is niets bekeken", uit["bekeken"], 0)
    klopt("en er staat waarom hij stopte", "afgekapt" in uit)
finally:
    categoriemeting.MAX_VERGELIJK_SECONDEN = echte_max
    categoriemeting._lees_met = echte_lees2

sjabloon2 = open(os.path.join(APP, "templates", "admin_ranglijst.html")).read()
klopt("de pagina toont de voortgang", "vergelijking.nu" in sjabloon2)
klopt("en meldt het als hij vastloopt", "vergelijking.vastgelopen" in sjabloon2)
klopt("en de knop gaat dan weer van slot",
      "not vergelijking.vastgelopen" in sjabloon2)

print("\n== zonder bewaarde antwoorden zegt hij dat gewoon ==")
uit = categoriemeting.vergelijk_lezers("bestaat-niet", aantal=3)
klopt("er komt een nette fout uit", "fout" in uit)

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
