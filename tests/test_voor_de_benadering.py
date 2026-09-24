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

print("\n== 11. GROTE WINKEL BLOKKEERT DE SCANNER: WEL ZIJN PLEK ==")
appmod.run_scan = lambda url: {"error": "We konden deze website niet bereiken. Check..."}
appmod.db.bewaar_gratis_scan = lambda *a, **k: None
appmod._rang_voor_gratis_check = lambda url: {"positie": 1, "van": 42, "categorie": "Elektronica algemeen",
                                              "land": "the Netherlands", "genoemd": 23, "telbaar": 30,
                                              "link": "/index/nl/elektronica#p1"}
klant = appmod.app.test_client()
antw = klant.post("/api/scan", json={"url": "www.mediamarkt.nl"})
data = antw.get_json()
klopt("geen foutmelding maar een uitslag", antw.status_code == 200)
klopt("met de plek", data.get("rang", {}).get("positie") == 1)
klopt("zonder verzonnen cijfer", data.get("score") is None and data.get("checks") == [])
klopt("en eerlijk dat de site niet te lezen was", "could not reach" in (data.get("niet_gelezen") or ""))
klopt("de pagina toont dan alleen de plek", "if(data.score === null){" in index)
appmod._rang_voor_gratis_check = lambda url: None
antw = klant.post("/api/scan", json={"url": "onbekend.nl"})
klopt("niet in de index en niet te lezen: gewoon de Engelse fout",
      antw.status_code == 400 and antw.get_json()["error"].startswith("We could not reach"))

print("\n== 12. BELGIE GERICHT VULLEN ==")
import winkelvinder  # noqa: E402
gezocht = []
winkelvinder.bronnen.beschikbaar = lambda: True
winkelvinder.bronnen.zoek = lambda vraag, land=None, taal=None: gezocht.append((vraag, land, taal)) or [
    {"url": "https://www.speelgoedwinkel.be/"}, {"url": "https://nederlands.nl/"},
    {"url": "https://www.bol.com/"}]
toegevoegd = []
winkelvinder.db.voeg_benaderingen_toe = lambda regels: toegevoegd.extend(regels) or len(regels)
uit = winkelvinder.vul_land("be", [("speelgoed", "Speelgoed"), ("boeken", "Boeken"), ("vol", "Vol")],
                            {"speelgoed": 2, "boeken": 9, "vol": 30}, doel=15, max_zoekopdrachten=12)
klopt("alleen categorieen met te weinig Belgische winkels", len(gezocht) == 2)
klopt("de dunste eerst", gezocht[0][0] == "speelgoed webshop Belgie")
klopt("zoekt in Belgie", gezocht[0][1] == "BE" and gezocht[0][2] == "nl")
klopt("alleen .be-winkels erbij", {r[0] for r in toegevoegd} == {"https://speelgoedwinkel.be"})
klopt("met land BE", all(r[2] == "BE" for r in toegevoegd))
print("\n== 12b. ZONDER BRAVE: WINKELS VIA HET MODEL ==")
import categoriemeting  # noqa: E402
import kosten  # noqa: E402


class _Antw:
    def __init__(self, tekst):
        self.content = [type("B", (), {"text": tekst})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 10})()


class _Model:
    class messages:  # noqa: N801
        @staticmethod
        def create(**k):
            _Model.prompt = k["messages"][0]["content"]
            return _Antw('{"domeinen": ["https://www.echtewinkel.be/", "verzonnen.be", '
                         '"bol.com", "echtewinkel.be", "andere.nl"]}')


categoriemeting._client = lambda: _Model()
categoriemeting._domein_bestaat = lambda d: d != "verzonnen.be"
kosten.registreer_aanroep = lambda **k: None
winkelvinder.WINKELVINDER_BRON = "ai"
gezocht.clear()
toegevoegd.clear()
uit = winkelvinder.vul_land("be", [("speelgoed", "Speelgoed")], {"speelgoed": 0})
klopt("Brave wordt niet gebruikt", gezocht == [])
klopt("het model werd gevraagd, met het land erbij", "Belgie" in _Model.prompt and uit["via_ai"] == 1)
klopt("verzonnen domeinen vallen af (DNS)", "https://verzonnen.be" not in {r[0] for r in toegevoegd})
klopt("marktplaatsen en andere landen vallen af, dubbele ook",
      [r[0] for r in toegevoegd] == ["https://echtewinkel.be"])
winkelvinder.WINKELVINDER_BRON = "auto"
winkelvinder.bronnen.beschikbaar = lambda: False
os.environ["ANTHROPIC_API_KEY"] = "alleen-voor-de-test"
toegevoegd.clear()
winkelvinder.zoek_nieuwe_winkels(hoeveel_zoekopdrachten=1)
klopt("ook de gewone winkelvinder valt terug op het model zonder Brave", len(toegevoegd) >= 1)

import onderhoud  # noqa: E402
klopt("de nachtronde vult eerst de landen", "verslag[\"landen_vullen\"] = stap_landen_vullen()" in lees("onderhoud.py"))
klopt("drie landrondes per nacht extra", onderhoud.METEN_LAND_PER_NACHT == 3)
klopt("een landronde vanaf drie winkels", onderhoud.MINIMUM_LAND == 3)

print("\n== 13. BREVO: BOUNCES EN SPAMKLACHTEN (STAP 78) ==")
import db  # noqa: E402
db.init_db()
os.environ.pop("BREVO_WEBHOOK_SLEUTEL", None)
klopt("zonder sleutel in Render bestaat de route niet",
      klant.post("/webhooks/brevo/iets", json={"event": "spam", "email": "a@b.nl"}).status_code == 404)
os.environ["BREVO_WEBHOOK_SLEUTEL"] = "geheim-test"
klopt("met een verkeerde sleutel ook niet",
      klant.post("/webhooks/brevo/fout", json={"event": "spam", "email": "a@b.nl"}).status_code == 404)
B1, B2 = "https://bounce-test-78.nl", "https://klacht-test-78.nl"
for u, e in ((B1, "info@bounce-test-78.nl"), (B2, "info@klacht-test-78.nl")):
    db.voeg_benadering_toe(u)
    db.zet_benadering(u, stand="gemaild", email=e, gemaild=True)
appmod._meld_aan_beheer = lambda *a, **k: None
klopt("een harde bounce komt binnen",
      klant.post("/webhooks/brevo/geheim-test",
                 json={"event": "hard_bounce", "email": "INFO@bounce-test-78.nl"}).status_code == 200)
klant.post("/webhooks/brevo/geheim-test", json={"event": "spam", "email": "info@klacht-test-78.nl"})
r1, r2 = db.get_benadering(B1), db.get_benadering(B2)
klopt("de bounce staat bij de winkel", r1.get("bounce_op") is not None)
klopt("een bounce meldt de winkel niet af (hij blijft in de index)", not db.is_afgemeld(B1))
klopt("de klacht staat erbij", r2.get("klacht_op") is not None)
klopt("en een spamklacht is een afmelding", db.is_afgemeld(B2))
t = db.trechter_benadering()
klopt("het beheerscherm telt ze", t["bounces"] >= 1 and t["klachten"] >= 1)
klopt("en waarschuwt bij te veel", "Te hoog. Zet de mails per dag terug" in lees("templates/admin_benadering.html"))
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url IN (%s, %s)", (B1, B2))
        cur.execute("DELETE FROM winkelprofielen WHERE webshop_url IN (%s, %s)", (B1, B2))
conn.close()

print("\n== 14. DEELBEELD EN ICOON IN DE NIEUWE STIJL ==")
from PIL import Image  # noqa: E402
beeld = Image.open(os.path.join(APP, "static", "krillo-share-2026.png"))
klopt("het deelbeeld is 1200 bij 630", beeld.size == (1200, 630))
klopt("het oude deelbeeld is weg", not os.path.exists(os.path.join(APP, "static", "krillo-share.png")))
klopt("de homepage wijst naar het nieuwe", "static/krillo-share-2026.png" in index
      and 'og:image:width" content="1200"' in index)
klopt("geen Nederlandse deeltekst meer", "Check for free whether AI assistants" not in index)
antw = klant.get("/favicon.ico")
klopt("/favicon.ico geeft het nieuwe icoon", antw.status_code == 200
      and antw.data == open(os.path.join(APP, "static", "favicon.ico"), "rb").read())
klopt("de icoonlinks hebben een nieuw kenmerk, zodat oude caches het loslaten",
      "/static/favicon.png?v=2026" in index)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de keten mag aan.")
