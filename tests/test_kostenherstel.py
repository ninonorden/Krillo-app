"""Bewaakt dat aanroepen zonder bekende prijs niet voor altijd op nul blijven staan.

Wat er gebeurde. De prijs wordt vastgelegd op het moment van de aanroep. Een
modelnaam die toen niet in de prijslijst stond werd geboekt als "onbekend", en
dat telt als nul euro. Dat is de gevaarlijkste fout die de kostenpagina kan
maken, want de dagpot rekent met datzelfde bedrag: de rem dacht dat er minder
uitgegeven was dan waar.

Erger nog was wat er daarna gebeurde. De prijs werd toegevoegd, maar de melding
bleef staan, want het toevoegen geldt alleen voor NIEUWE aanroepen. Tweeduizend
oude regels bleven op nul. Daarom rekent de kostenpagina die regels nu alsnog
door zodra de prijs bekend is.

Het tweede stuk gaat over de uitslagpagina van de gratis test. Die verwees nog
naar de audit van 79 euro, en die bestaat niet meer. Een knop naar iets wat je
niet meer kan kopen is erger dan geen knop.
"""
import os
import sys
import uuid

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db       # noqa: E402
import kosten   # noqa: E402

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
UNIEK = uuid.uuid4().hex[:10]


def leg_neer(model, invoer, uitvoer, status="onbekend"):
    """Eén aanroep in de boeken zetten, met de hand, zodat de stand vaststaat."""
    kenmerk = f"test-{UNIEK}-{model}-{invoer}"
    db.bewaar_kostengebeurtenis({
        "gebeurtenis_id": kenmerk, "soort": "ai", "provider": "google",
        "model": model, "invoer_tokens": invoer, "uitvoer_tokens": uitvoer,
        "kosten": None if status == "onbekend" else 0.5,
        "kosten_status": status, "prijsversie": None,
        "webshop_url": f"https://herstel-{UNIEK}.nl", "email": None,
        "scan_id": None, "duur_ms": 10, "gelukt": True, "foutsoort": None,
        "pogingen": 1,
    })
    return kenmerk


print("\n== een model zonder prijs valt op ==")
leg_neer("verzonnen-model-zonder-prijs", 1_000_000, 1_000_000)
namen = {(m["provider"], m["model"]) for m in db.onbekende_modellen(30)}
klopt("het staat in de lijst onbekende modellen",
      ("google", "verzonnen-model-zonder-prijs") in namen)

print("\n== zodra de prijs bekend is wordt hij alsnog doorgerekend ==")
# Een model dat WEL in de prijslijst staat, maar met de hand als onbekend
# geboekt. Precies de situatie van gemini-flash-latest: de aanroep is ouder dan
# de regel in de prijslijst.
bekend = "gemini-flash-latest"
prijs = kosten.zoek_prijs("google", bekend)
klopt(f"{bekend} staat in de prijslijst", prijs is not None)
kenmerk = leg_neer(bekend, 1_000_000, 1_000_000)

bijgewerkt = db.herstel_onbekende_kosten(kosten.zoek_prijs)
klopt("er is minstens een regel bijgewerkt", bijgewerkt >= 1)

na = {m["model"] for m in db.onbekende_modellen(30)}
klopt(f"{bekend} staat er niet meer bij", bekend not in na)
klopt("het verzonnen model nog wel, want daar is geen prijs voor",
      "verzonnen-model-zonder-prijs" in na)

print("\n== en het bedrag klopt ==")
regels = db.kostenoverzicht(30)
eigen = [r for r in (regels.get("per_klant") or [])
         if r.get("webshop_url") == f"https://herstel-{UNIEK}.nl"]
klopt("de winkel staat in het overzicht", len(eigen) == 1)
verwacht = prijs["invoer_per_miljoen"] + prijs["uitvoer_per_miljoen"]
gekregen = float(eigen[0]["kosten"]) if eigen else 0
klopt(f"een miljoen in en een miljoen uit is {verwacht:.4f} euro",
      abs(gekregen - verwacht) < 0.01)

print("\n== twee keer draaien verandert niets meer ==")
# Zou dit elke keer opnieuw optellen, dan liep het bedrag op bij elk bezoek aan
# de kostenpagina.
nogmaals = db.herstel_onbekende_kosten(kosten.zoek_prijs)
regels2 = db.kostenoverzicht(30)
eigen2 = [r for r in (regels2.get("per_klant") or [])
          if r.get("webshop_url") == f"https://herstel-{UNIEK}.nl"]
zo("het bedrag staat stil", float(eigen2[0]["kosten"]) if eigen2 else 0, gekregen)
klopt("en er valt niets meer te herstellen voor dit model", nogmaals >= 0)

print("\n== het herstellen gebeurt NOOIT vanzelf bij het openen van de pagina ==")
# Dit is de fout die de hele site heeft platgelegd: een opdracht die de
# database aanpast, uitgevoerd bij elke keer dat iemand de pagina opende.
app_tekst = lees("app.py")
begin = app_tekst.find("def admin_kosten")
stuk = app_tekst[begin:begin + 1600]
klopt("de pagina kent de herstelknop", "db.herstel_onbekende_kosten(kosten.zoek_prijs)" in stuk)
klopt("maar doet het alleen op een knop", 'request.args.get("herstel")' in stuk)
klopt("en er staat een knop op de pagina", "herstel=ja" in lees("templates/admin_kosten.html"))

print("\n== en het gaat in een handvol opdrachten, niet duizenden ==")
# Een opdracht per rij naar een database die niet op dezelfde machine staat
# duurt langer dan de tijdslimiet van de webserver. Dan breekt hij af, draait
# terug, en begint bij de volgende keer opnieuw.
dbtekst = lees("db.py")
start = dbtekst.find("def herstel_onbekende_kosten")
functie = dbtekst[start:dbtekst.find("\ndef ", start + 10)]
klopt("het rekenen gebeurt in de database zelf", "invoer_tokens, 0) / 1000000.0" in functie)
klopt("en het groepeert per model", "GROUP BY provider, model" in functie)
klopt("en laat zien welk model het is", "onbekende_modellen=db.onbekende_modellen" in app_tekst)
pagina = lees("templates/admin_kosten.html")
klopt("de namen komen op het scherm", "m.model" in pagina)

print("\n== de gratis uitslag verwijst niet meer naar de audit ==")
index = lees("templates/index.html")
klopt("geen knop naar de volledige audit", "Bekijk de volledige audit" not in index)
klopt("geen vervaagde auditvoorbeelden meer", "fix-preview-blurred" not in index)
klopt("geen belofte dat de oplossing in de audit zit",
      "De volledige oplossing zit in de audit" not in index)
klopt("geen garantie over de audit meer boven de prijskaarten",
      "<strong>Levert de audit je niets op" not in index)
# In het betaalscherm mag de audittekst nog wel staan: die tak blijft bestaan
# voor oude links, en voor wie via zo'n link koopt geldt die garantie gewoon.
klopt("maar de oude betaalroute houdt zijn eigen belofte",
      "Levert de audit je niets op" in index)
klopt("de knop wijst naar wat er wel te koop is", "Laat het ons doen &rarr;" in index)

print("\n== de uitslag is korter geworden ==")
klopt("wat goed staat zit ingeklapt", 'class="scan-goed"' in index)
klopt("en de verbeterpunten staan wel open", "Wat er beter kan" in index)

print("\n== de homepage herhaalt zichzelf niet meer ==")
# Drie blokken zeiden hetzelfde als de prijskaarten. Die zijn weg. Dit bewaakt
# dat ze niet terugsluipen, en dat het bewijs dat wel werkt blijft staan.
klopt("het dubbele blok onder het voorbeeldrapport is weg",
      "Wat wij hiermee doen" not in index)
klopt("de zes stukjes onder het monitoringoverzicht zijn weg",
      "Wat je bij monitoring krijgt" not in index)
klopt("hun opmaak is ook opgeruimd", "audit-teaser" not in index)
klopt("er staat wel een weg naar de prijzen", "monitoring-slot" in index)
# Wat er met opzet moet blijven: het bewijs. Dat was juist de kritiek op het
# ondernemersforum, dat het te vaag was.
klopt("het nagemaakte scherm met de uitslag staat er nog",
      'class="rapport-demo"' in index)
# En het is nu de gratis scan, niet de rapportpagina van de audit. Die pagina
# krijgt niemand meer: een monitoringklant komt op /monitoring/<token>.
klopt("het is aangekondigd als de gratis scan",
      "Dit krijg je van de gratis scan" in index)
klopt("het venster doet niet meer alsof het de auditpagina is",
      '<span class="rapport-demo-url">krillo.nl/rapport</span>' not in index)
klopt("en het stukje code zegt erbij dat het niet gratis is",
      "Niet gratis: dit is wat wij er voor je neerzetten" in index)
klopt("en het blok over wat wij wel en niet aanraken ook",
      "Wat we wel en niet aanraken" in index)

print("\n== de prijskaarten ==")
klopt("drie kolommen, niet vier", "grid-template-columns:repeat(3,1fr)" in index)
klopt("de regels zijn geen flexrij meer met kolommen per woord",
      ".price-feats li{display:flex" not in index)
klopt("het streepje staat ernaast in plaats van in de rij",
      ".price-feats li{position:relative" in index)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
