"""De index per land, de taalopbouw, het dashboard en de cijfers uit de database.

WAT HIER OP HET SPEL STAAT

De openbare index is het enige gratis kanaal waar Krillo klanten uit haalt. Gaat
hier iets stuk in de adressen, dan verdwijnen de pagina's uit Google en is er
geen verkeer meer. Daarom bewaakt deze test vooral SAAIE dingen: dat oude
adressen blijven werken, dat elke pagina zegt welke de echte is, en dat er geen
enkel verzonnen getal op staat.

DE DRIE REGELS DIE HIER VASTLIGGEN

1. NOOIT OMLEIDEN OP IP-ADRES. Google haalt de site meestal op vanuit de
   Verenigde Staten. Stuur je die bezoeker automatisch naar een Engelse pagina,
   dan ziet Google de Nederlandse index nooit. Elk land heeft een vast adres en
   het land van de bezoeker bepaalt alleen wat er voorgekozen staat.
2. OUDE ADRESSEN BLIJVEN WERKEN. /index/speelgoed stuurt permanent door naar
   /index/nl/speelgoed. Een 301 en geen 302, anders houdt Google beide aan.
3. GEEN VAST GETAL IN EEN SJABLOON. Alles komt uit de database. Een getal dat
   je met de hand invult klopt over twee maanden niet meer, en wij zijn juist
   het bedrijf dat anderen daarop controleert.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import db          # noqa: E402
import klantbeeld  # noqa: E402
import sitetaal    # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== de taalkeuze ==")
zo("het adres wint van de browser",
   sitetaal.kies_taal(pad_taal="nl", kop_taal="en-US,en"), "nl")
zo("zonder adres telt de browser", sitetaal.kies_taal(kop_taal="nl-NL,nl"), "nl")
zo("en anders de standaard", sitetaal.kies_taal(kop_taal="fr-FR,fr"), sitetaal.STANDAARD)
zo("een index van Nederland staat in het Nederlands", sitetaal.taal_van_land("nl"), "nl")
zo("een index van Belgie ook", sitetaal.taal_van_land("be"), "nl")
zo("een index van het VK in het Engels", sitetaal.taal_van_land("uk"), "en")
zo("nl-BE kiest Belgie voor",
   sitetaal.land_uit_kop("nl-BE,nl;q=0.9", ["nl", "be"]), "be")
zo("nl-NL kiest Nederland voor",
   sitetaal.land_uit_kop("nl-NL,nl;q=0.9", ["nl", "be"]), "nl")

print("\n== elke tekst bestaat in beide talen ==")
nl = set(sitetaal.T["nl"])
en = set(sitetaal.T["en"])
zo("geen sleutel alleen in het Nederlands", sorted(nl - en), [])
zo("geen sleutel alleen in het Engels", sorted(en - nl), [])
klopt("een onbekende taal valt terug en valt niet om",
      sitetaal.teksten("zz")["index_kop"] == sitetaal.T["en"]["index_kop"])

print("\n== elke sleutel in een sjabloon bestaat echt ==")
gebruikt = set()
for naam in ("index_overzicht.html", "index_categorie.html", "dashboard.html"):
    tekst = open(os.path.join(TEMPLATES, naam)).read()
    gebruikt |= set(re.findall(r"\bt\.([a-z_]+)", tekst))
ontbreekt = sorted(s for s in gebruikt if s not in nl)
zo("geen sjabloon gebruikt een tekst die niet bestaat", ontbreekt, [])

# ---------------------------------------------------------------------------
CAT = "perland-test"
NL = [f"https://plnl{n}.nl" for n in range(1, 5)]
BE = [f"https://plbe{n}.be" for n in range(1, 4)]
ALLE = NL + BE


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (ALLE,))
        cur.execute("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    conn.close()


db.init_db()
opruimen()
for u in NL:
    db.voeg_benadering_toe(u, naam=u.replace("https://", ""), land="NL", branche="t")
    db.zet_categorie(u, CAT)
for u in BE:
    db.voeg_benadering_toe(u, naam=u.replace("https://", ""), land="BE", branche="t")
    db.zet_categorie(u, CAT)

ronde = db.start_categorie_ronde(CAT, 30, len(ALLE))
db.bewaar_categorie_uitkomsten(ronde, CAT, [
    {"webshop_url": NL[0], "positie": 1, "genoemd": 9, "aanbevolen": 4, "beste_positie": 1},
    {"webshop_url": BE[0], "positie": 2, "genoemd": 8, "aanbevolen": 3, "beste_positie": 1},
    {"webshop_url": NL[1], "positie": 3, "genoemd": 6, "aanbevolen": 1, "beste_positie": 2},
    {"webshop_url": NL[2], "positie": 4, "genoemd": 3, "aanbevolen": 0, "beste_positie": 4},
    {"webshop_url": BE[1], "positie": 5, "genoemd": 1, "aanbevolen": 0, "beste_positie": 6},
    {"webshop_url": BE[2], "positie": 6, "genoemd": 0, "aanbevolen": 0, "beste_positie": None},
    {"webshop_url": NL[3], "positie": 7, "genoemd": 0, "aanbevolen": 0, "beste_positie": None},
], 28)
for vraag, namen in [
        ("waar koop ik online een testartikel", ["plnl1.nl", "plbe1.be"]),
        ("welke webshop verkoopt testartikelen", ["plnl1.nl", "plnl2.nl"]),
        ("wat is het beste merk testartikelen", [])]:
    db.bewaar_categorie_antwoord(
        ronde, CAT, vraag, "model-a", "antwoordtekst",
        {"winkel_kon_genoemd": bool(namen),
         "winkels": [{"naam": n, "positie": i + 1} for i, n in enumerate(namen)],
         "aanbevolen": namen[:1]})

print("\n== de ranglijst per land ==")
nlijst = db.ranglijst_per_land(CAT, "nl")
zo("alleen Nederlandse winkels", len(nlijst["rijen"]), 4)
zo("en opnieuw genummerd vanaf een",
   [r["positie"] for r in nlijst["rijen"]], [1, 2, 3, 4])
zo("de beste Nederlandse staat eerste", nlijst["rijen"][0]["webshop_url"], NL[0])
belijst = db.ranglijst_per_land(CAT, "be")
zo("Belgie heeft zijn eigen lijst", len(belijst["rijen"]), 3)
zo("met zijn eigen nummer een", belijst["rijen"][0]["webshop_url"], BE[0])
klopt("een winkel kan dus in twee landen een eigen positie hebben",
      nlijst["rijen"][0]["positie"] == 1 and belijst["rijen"][0]["positie"] == 1)

print("\n== de cijfers komen uit de database ==")
cijfers = db.index_cijfers()
klopt("er zijn categorieen geteld", (cijfers.get("categorieen") or 0) >= 1)
klopt("er zijn winkels geteld", (cijfers.get("winkels") or 0) >= 7)
klopt("er zijn antwoorden geteld", (cijfers.get("antwoorden") or 0) >= 3)
landen = {r["land"]: r for r in db.landen_in_index()}
klopt("Nederland staat als land in de index", "nl" in landen)
klopt("Belgie ook", "be" in landen)

print("\n== het dashboard ==")
beeld = klantbeeld.bouw(NL[1], land="nl")
zo("de winkel staat tweede in Nederland, niet derde zoals in de hele lijst",
   beeld["positie"], 2)
zo("van de vier Nederlandse", beeld["van"], 4)
klopt("er staan winkels boven hem", len(beeld["boven_mij"]) >= 1)
gemist = [v["vraag"] for v in beeld["gemiste_vragen"]]
klopt("de vraag waar hij niet in stond telt als gemist",
      "waar koop ik online een testartikel" in gemist)
klopt("de vraag waar hij wel in stond niet",
      "welke webshop verkoopt testartikelen" not in gemist)
klopt("de vraag die niet meetelde ook niet",
      "wat is het beste merk testartikelen" not in gemist)
eerste = beeld["gemiste_vragen"][0]
klopt("met de concurrent die wel genoemd werd", "plnl1.nl" in eerste["concurrenten"])
zo("een lege lijst geeft geen staven", klantbeeld.balkhoogtes([]), [])

# ---------------------------------------------------------------------------
import app as krillo  # noqa: E402
krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()

print("\n== de adressen ==")
zo("het overzicht bestaat", klant.get("/index").status_code, 200)
zo("het overzicht van Nederland ook", klant.get("/index/nl").status_code, 200)
zo("en van Belgie", klant.get("/index/be").status_code, 200)
zo("een categorie in Nederland", klant.get(f"/index/nl/{CAT}").status_code, 200)
zo("dezelfde categorie in Belgie", klant.get(f"/index/be/{CAT}").status_code, 200)
zo("een land dat wij niet meten geeft 404", klant.get("/index/de").status_code, 404)
zo("en een onzinland ook", klant.get("/index/zz/iets").status_code, 404)

print("\n== een te korte lijst is geen ranglijst ==")
KLEIN = "perland-klein"
db.voeg_benadering_toe("https://kleinwinkel.nl", naam="klein", land="NL", branche="t")
db.zet_categorie("https://kleinwinkel.nl", KLEIN)
kr = db.start_categorie_ronde(KLEIN, 30, 1)
db.bewaar_categorie_uitkomsten(kr, KLEIN, [
    {"webshop_url": "https://kleinwinkel.nl", "positie": 1, "genoemd": 3,
     "aanbevolen": 1, "beste_positie": 1}], 28)
zo("een categorie met een winkel krijgt geen pagina",
   klant.get(f"/index/nl/{KLEIN}").status_code, 404)
overzicht = klant.get("/index/nl").get_data(as_text=True)
klopt("en staat ook niet in het overzicht", f"/index/nl/{KLEIN}" not in overzicht)
conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (KLEIN,))
    cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (KLEIN,))
    cur.execute("DELETE FROM benadering WHERE webshop_url = %s", ("https://kleinwinkel.nl",))
conn.close()

print("\n== oude adressen blijven werken ==")
oud = klant.get(f"/index/{CAT}")
zo("een oud categorieadres stuurt door", oud.status_code, 301)
zo("permanent, naar het adres met land",
   oud.headers.get("Location"), f"/index/nl/{CAT}")

print("\n== er wordt nooit omgeleid op taal van de browser ==")
antwoord = klant.get("/index", headers={"Accept-Language": "nl-NL,nl;q=0.9"})
zo("een Nederlandse bezoeker krijgt gewoon de pagina", antwoord.status_code, 200)
antwoord = klant.get(f"/index/nl/{CAT}", headers={"Accept-Language": "en-US,en"})
zo("en een Engelse bezoeker op een Nederlandse index ook", antwoord.status_code, 200)
tekst = antwoord.get_data(as_text=True)
# EEN ADRES, EEN TAAL. De site staat in het Engels, ook de ranglijst van
# Nederland, en de taalkop van de browser verandert daar niets aan. Zou die kop
# wel meetellen, dan krijgt Google (die geen taalkop stuurt) iets anders te zien
# dan een Nederlandse bezoeker op hetzelfde adres. Nederlands kan alleen met een
# uitdrukkelijke ?taal=nl in het adres.
klopt("de pagina staat in het Engels", 'html lang="en"' in tekst)
nederlands = klant.get(f"/index/nl/{CAT}?taal=nl").get_data(as_text=True)
klopt("en met ?taal=nl in het Nederlands", 'html lang="nl"' in nederlands)

print("\n== wat een zoekmachine nodig heeft ==")
tekst = klant.get(f"/index/nl/{CAT}").get_data(as_text=True)
klopt("er staat een canonical",
      f'rel="canonical" href="https://www.krillo.nl/index/nl/{CAT}"' in tekst)
klopt("er staat een hreflang voor de Nederlandse markt", 'hreflang="en-NL"' in tekst)
klopt("en een naar het Belgische adres", f'/index/be/{CAT}' in tekst)

import json  # noqa: E402
blokken = re.findall(r'<script type="application/ld\+json">(.*?)</script>', tekst, re.S)
zo("er staan twee blokken gestructureerde gegevens", len(blokken), 2)
soorten = {json.loads(b)["@type"] for b in blokken}
zo("een ranglijst en een kruimelpad", sorted(soorten), ["BreadcrumbList", "ItemList"])
kruimel = [json.loads(b) for b in blokken if json.loads(b)["@type"] == "BreadcrumbList"][0]
zo("het kruimelpad heeft drie stappen", len(kruimel["itemListElement"]), 3)

print("\n== de sitemap en robots ==")
sitemap = klant.get("/sitemap.xml").get_data(as_text=True)
klopt("het overzicht staat erin", "https://www.krillo.nl/index<" in sitemap)
klopt("het land staat erin", "https://www.krillo.nl/index/nl<" in sitemap)
klopt("de categorie per land staat erin",
      f"https://www.krillo.nl/index/nl/{CAT}<" in sitemap)
klopt("het voorbeelddashboard staat erin", "https://www.krillo.nl/demo<" in sitemap)
klopt("met een lastmod", re.search(r"/index/nl/" + CAT + r"</loc><lastmod>\d{4}", sitemap))
robots = klant.get("/robots.txt").get_data(as_text=True)
klopt("klantpagina's blijven uit Google", "Disallow: /mijn/" in robots)
klopt("het beheer ook", "Disallow: /admin/" in robots)
klopt("de index juist niet", "Disallow: /index" not in robots)

print("\n== de cijfers op de homepage tellen de HELE categorie ==")
# Op de homepage stond "1 van de 4+" terwijl er vierentwintig winkels in die
# categorie staan, en het aantal niet-genoemde winkels werd geteld binnen de
# vier die getoond worden. Allebei te laag, en het is precies de meting die wij
# verkopen. De ranglijst wordt nu volledig opgehaald en er worden er vier
# getoond.
thuis2 = klant.get("/").get_data(as_text=True)
hele = db.ranglijst_per_land(CAT, "nl", limiet=500)
alle_winkels = len(hele.get("rijen", []))
stil = len([r for r in hele.get("rijen", []) if not (r["genoemd"] or 0)])
if f"/index/nl/{CAT}" in thuis2:
    klopt("het totaal aantal winkels staat er, niet het aantal getoonde rijen",
          f"of {alle_winkels}<" in thuis2 or f"of {alle_winkels} " in thuis2)
    klopt("en het aantal niet-genoemde winkels klopt met de hele lijst",
          stil == 0 or f"{stil} other stores" in thuis2)
    klopt("er staat geen plaatshouder met een plusje meer", "+</span>" not in thuis2)

print("\n== het dashboard schrijft winkels net zo op als de ranglijst ==")
# Op de ranglijst stond ilovespeelgoed.nl en op het dashboard, bij wie er vlak
# boven je staat, stond https://ilovespeelgoed.nl. Twee schermen die dezelfde
# winkel anders schrijven laten je twijfelen of het wel dezelfde winkel is.
dash = open(os.path.join(APP, "templates", "dashboard.html"), encoding="utf-8").read()
klopt("de buren staan zonder https ervoor",
      "r.naam or r.webshop_url | replace('https://','')" in dash)
# Zes metingen in september gaven zes keer SEP onder de staafjes, en dat zegt
# niets. De dag erbij zegt wel iets.
klopt("bij het verloop staat de dag en niet alleen de maand",
      "s.datum.strftime('%d %b')" in dash)

print("\n== het openbare voorbeeld en de klantlink ==")
zo("het voorbeelddashboard staat er", klant.get("/demo").status_code, 200)
demo = klant.get("/demo").get_data(as_text=True)
klopt("en zegt dat het een voorbeeld is", "this is an example" in demo.lower())
zo("een onbekende klantlink geeft 404", klant.get("/mijn/bestaatniet").status_code, 404)
zo("het formulier voor een nieuwe link bestaat", klant.get("/mijn-link").status_code, 200)
a = klant.post("/mijn-link", data={"email": "nietbekend@example.com"})
zo("een onbekend adres stuurt gewoon door", a.status_code, 302)
klopt("naar dezelfde melding als een bekend adres",
      "m=verstuurd" in a.headers.get("Location", ""))

print("\n== geen verzonnen getallen in de sjablonen ==")
for naam in ("index_overzicht.html", "index_categorie.html", "dashboard.html"):
    inhoud = open(os.path.join(TEMPLATES, naam)).read()
    klopt(f"{naam} heeft geen plaatshouder tussen haakjes",
          not re.search(r"\[\d[\d.,]*\]", inhoud))


print("\n== de homepage: nieuwe stijl, werkende scan ==")
thuis = klant.get("/").get_data(as_text=True)
# OPTIE B, 18 september 2026: één letter, Space Grotesk, zwaar en strak
# gespatieerd. De schreefletter van optie A is eruit.
klopt("de letter van optie B wordt geladen", "Space+Grotesk" in thuis)
klopt("de letters van optie A zijn weg",
      "Instrument+Serif" not in thuis and "family=Archivo" not in thuis
      and "family=Inter:" not in thuis)

# DIT IS HET BELANGRIJKSTE VAN DEZE TEST. De homepage is verbouwd terwijl de
# scan, de bestelschermen en de zichtbaarheidstest erin bleven staan. Die
# onderdelen hangen aan vaste id's in de opmaak. Raakt er een kwijt bij een
# volgende verbouwing, dan werkt de knop niet meer en merkt niemand het, want
# de pagina laadt gewoon.
for stuk in ("scanUrlInput", "scanButton", "scanResult", "checkoutOverlay",
             "checkoutSubmit", "zichtbaarheidBlok", "ztKnop", "ztEmail",
             "watchCheckoutBtn", "fixCheckoutBtn"):
    klopt(f"de homepage heeft nog {stuk}", f'id="{stuk}"' in thuis)

klopt("de index staat op de homepage", "idx-kaart" in thuis)
klopt("met de index van vandaag naast de belofte", "indexkaart" in thuis)
klopt("met een link naar de ranglijst zelf", "/index/nl/" in thuis)
klopt("en met een link naar de index in het menu", 'href="/index"' in thuis)

print("\n== de cijfers op de homepage zijn niet verzonnen ==")
import re as _re  # noqa: E402
blok = thuis[thuis.find("indexkaart"):thuis.find("idx-kaart")]
klopt("in het cijferblok staat geen plaatshouder", "[" not in blok)
klopt("het aantal categorieen komt uit de database",
      str(db.index_cijfers().get("categorieen")) in blok)

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
