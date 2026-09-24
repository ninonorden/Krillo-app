"""Alles wat moest kloppen voordat de benadering aan mag (24 september).

WAAROM DEZE TEST BESTAAT

Voor Nino de koude mail aanzette, liepen drie onafhankelijke controles de hele
keten na: de automatische stappen, de beloftes op de site, en hoe Fix echt in
de winkel van een klant terechtkomt. Wat ze vonden, en wat hier vastligt:

1. De opbouw verdubbelde het aantal mails elke dag, ook als de benadering UIT
   stond: aanzetten betekende meteen 100 per dag vanaf een nieuw domein.
2. De link in de mail kon op "nog niet gemeten" uitkomen (geen land, of een
   landlijst te kort voor een pagina), en de ranglijst laadde maar 100 rijen.
3. Twee rondes tegelijk konden dezelfde winkel twee keer mailen.
4. Een winkel die bleef mislukken stond elke ronde vooraan.
5. Een mislukte maandmail telde als verstuurd; een Mollie-storing bij een
   betaling verdween stil.
6. Afmelden haalde een winkel pas na een maand uit de index.
7. "Get my rank" gaf geen plek, en de uitslag was Nederlands op een Engelse site.
8. Beloftes zonder code erachter: een goedkeurknop, "met de reden", "Most
   chosen" zonder klanten, een tweede land voor 49 euro.
9. De vragenpagina in Shopify kreeg altijd een Nederlandse titel.
10. Duitsland stond op LIVE, uit Nederlandse vragen, met een lege pagina.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
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


app_bron = lees("app.py")
db_bron = lees("db.py")
index = lees("templates/index.html")

print("\n== 1. DE OPBOUW ==")
import benadering  # noqa: E402
klopt("hoogstens 40 per dag vanzelf", benadering.OPBOUW_DOEL == 40)
klopt("een week tussen verhogingen", benadering.OPBOUW_DAGEN == 7)
klopt("geen eigen meting per winkel meer", benadering.STANDAARD_METINGEN_PER_RONDE == 0)
klopt("een keer terug naar een veilige start",
      "_eenmalig(\"benadering_veilige_start_24sep\"" in db_bron)

print("\n== 2. DE LINK IN DE MAIL BESTAAT ==")
klopt("geen mail zonder land of met een te korte landlijst",
      'if not beeld.get("land") or (beeld.get("van") or 0) < MINIMUM_PER_LAND:' in app_bron)
klopt("de ranglijst laadt tot 1000 rijen",
      "db.ranglijst_per_land, slug, land, 1000)" in app_bron)

print("\n== 3 EN 4. NOOIT TWEE RONDES, NOOIT VAST ACHTERAAN ==")
import app as appmod  # noqa: E402
klopt("een slot op de ronde", isinstance(appmod._benadering_slot, type(__import__("threading").Lock())))
gedraaid = []
appmod._benadering_ronde_werk = lambda: gedraaid.append(1)
appmod._benadering_slot.acquire()
appmod._benadering_ronde()
appmod._benadering_slot.release()
klopt("loopt er al een, dan slaat de tweede over", gedraaid == [])
appmod._benadering_ronde()
klopt("anders draait hij gewoon", gedraaid == [1])
klopt("mislukt: achteraan in de rij", "db.achteraan_in_rij(webshop_url)" in lees("benadering.py"))

print("\n== 5. NIETS VERDWIJNT STIL ==")
klopt("Mollie drie keer opnieuw, dan een mail aan jou",
      "Betaling niet op te halen bij Mollie" in app_bron and "for wacht in (5, 20, 60):" in app_bron)
klopt("een mislukte maandmail telt niet als verstuurd en geeft een melding",
      "Maandbericht niet verstuurd" in lees("meldingen.py")
      and "if gelukt:\n            verslag[\"verstuurd\"] += 1" in lees("meldingen.py"))
klopt("opzeggen binnen veertien dagen: melding om terug te betalen",
      "Actie nodig: geld terug." in app_bron)

print("\n== 6. AFGEMELD IS METEEN UIT DE INDEX ==")
klopt("de ranglijst laat afgemelde winkels weg", "AND coalesce(b.afgemeld, FALSE) = FALSE" in db_bron)

print("\n== 7. DE GRATIS CHECK: EEN PLEK, IN HET ENGELS ==")
import checktaal  # noqa: E402
uitslag = {"url": "https://x.nl", "score": 60, "fix_previews": [{"titel": "Nederlands"}],
           "checks": [{"id": "https", "status": "goed", "titel": "Gebruikt de site een beveiligde verbinding?",
                       "uitleg": "De site gebruikt een beveiligde verbinding (https)."},
                      {"id": "faq", "status": "slecht", "titel": "Beantwoordt de pagina...",
                       "uitleg": "Nederlands"},
                      {"id": "sitemap", "status": "onbekend", "titel": "x", "uitleg": "y"}]}
en = checktaal.naar_het_engels(uitslag)
klopt("titels Engels", en["checks"][0]["titel"] == "Does the site use a secure connection?")
klopt("uitleg Engels bij goed", en["checks"][0]["uitleg"].startswith("The site uses"))
klopt("uitleg Engels bij een probleem", "questions and answers" in en["checks"][1]["uitleg"])
klopt("niet gemeten zegt dat", "did not score" in en["checks"][2]["uitleg"])
klopt("geen Nederlandse voorbeeldfixes mee", "fix_previews" not in en)
klopt("het cijfer blijft", en["score"] == 60)
klopt("alle dertien controles hebben een Engelse titel", len(checktaal.TITELS) == 13)
klopt("foutmeldingen Engels", checktaal.fout_in_het_engels(
      "We konden deze website niet bereiken. Check...").startswith("We could not reach"))
klopt("onbekende fout: nooit het Nederlands", "Onbekend" not in checktaal.fout_in_het_engels("Onbekend"))
klopt("de plek gaat mee in de uitslag", 'result["rang"] = _rang_voor_gratis_check(' in app_bron)
klopt("en staat bovenaan de uitslag", "if(data.rang){" in index and "Not in the index yet." in index)
klopt("de bronnenzin is Engels", "We looked at" in lees("bronnen.py")
      and "We bekeken" not in lees("bronnen.py"))

print("\n== 8. GEEN BELOFTES ZONDER CODE ==")
alles = index + lees("templates/faq.html") + lees("templates/dashboard.html") \
    + lees("templates/index_categorie.html") + lees("templates/zo-meten-we.html") \
    + lees("templates/voorwaarden.html")
for zin in ("YOU PRESS APPROVE", "After your approval", "four weeks later",
            "or the market", "with the reason", "Most chosen", "costs 49 euro per month extra",
            "A second country costs", "Reports in your own name", "tell you the moment",
            "Zo meten we bij Krillo", "about what your store sells"):
    klopt(f"niet meer: '{zin}'", zin not in alles)
klopt("Fix zegt eerlijk hoe het per platform gaat",
      "on Shopify through our app, elsewhere by our team with your access" in index)
klopt("de titel van /mijn-link is Engels",
      "<title>Get your link again | Krillo</title>" in lees("templates/mijn_link.html"))

print("\n== 9. SHOPIFY: DE VRAGENPAGINA IN DE TAAL VAN DE WINKEL ==")
import shopify_werk  # noqa: E402
klopt("Engelse winkel", shopify_werk.faq_titel({"taalcode": "en"}) == "Frequently asked questions")
klopt("Nederlandse winkel", shopify_werk.faq_titel({"taalcode": "nl"}) == "Veelgestelde vragen")
klopt("Duitse winkel", shopify_werk.faq_titel({"taalcode": "de"}) == "Häufig gestellte Fragen")
klopt("onbekend: Engels", shopify_werk.faq_titel({"taalcode": "pt"}) == "Frequently asked questions")
klopt("en die titel gaat mee naar Shopify",
      'titel = voorstel.get("titel") or FAQ_TITELS["nl"]' in lees("shopify_werk.py"))

print("\n== 10. ALLEEN LANDEN MET EIGEN VRAGEN STAAN LIVE ==")
klopt("de lijst van live landen filtert op vraaglanden", "toegestaan = {\"nl\", *vraaglanden.VRAAGLANDEN}" in db_bron)
klopt("en telt een land pas vanaf drie winkels in een categorie",
      "count(*) FILTER (WHERE winkels >= 3) AS categorieen" in db_bron)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de keten mag aan.")
