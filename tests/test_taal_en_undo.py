"""Taal van de winkel, Undo, en tekens op het scherm.

WAAROM DEZE TEST BESTAAT

26 september, bij het opnemen van de video voor Shopify, zag Nino drie dingen:
1. Een Amerikaanse ontwikkelwinkel kreeg Nederlandse productteksten. De vraag
   aan Shopify vroeg ook de talen op (shopLocales), en daarvoor heeft Krillo
   het recht niet. Shopify weigerde de hele vraag, dus ook het land, en alles
   viel terug op Nederland. Nu komt de taal los, met terugvalwegen: de taal
   van de winkelpagina zelf, en anders het land.
2. Na drie wijzigingen en een klik op Undo stonden alle drie weer in de lijst,
   in plaats van alleen de teruggezette. En het scherm beloofde "apply it
   again whenever you want" aan een gratis winkel die dat niet meer kan.
3. Op het scherm stond "extra&#x27;s" in plaats van "extra's".
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
os.environ.setdefault("ADMIN_KEY", "testsleutel")
os.environ.setdefault("BASE_URL", "https://krilloai.com")
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


import shopify_app  # noqa: E402

WINKEL_DATA = {"shop": {"name": "Demo", "email": "a@b.com",
                        "primaryDomain": {"host": "demo.myshopify.com",
                                          "url": "https://demo.myshopify.com"},
                        "billingAddress": {"countryCodeV2": "US"},
                        "plan": {"partnerDevelopment": True, "displayName": "Developer Preview"}}}
vragen = []


def nep_graphql(talen_mogen, talen=None):
    def f(winkel, sleutel, vraag, variabelen=None, stil=False):
        vragen.append(vraag)
        if "shopLocales" in vraag:
            if not talen_mogen:
                return None  # Shopify: access denied
            return {"shopLocales": talen or []}
        klopt("de winkelvraag bevat geen shopLocales meer", "shopLocales" not in vraag)
        return WINKEL_DATA
    return f


print("\n== 1. ZONDER RECHT OP TALEN: HET LAND KOMT TOCH BINNEN ==")
shopify_app._graphql_eenvoudig = nep_graphql(False)
shopify_app._taal_van_etalage = lambda adres: None
g = shopify_app.winkelgegevens("demo.myshopify.com", "x")
klopt("de winkel wordt gewoon gelezen", g and g["naam"] == "Demo")
klopt("het land is US", g and g["land"] == "US")
klopt("zonder andere bron: Engels bij US", g and g["taal"] == "en")

print("\n== DE TAAL VAN DE WINKELPAGINA GAAT VOOR HET LAND ==")
shopify_app._taal_van_etalage = lambda adres: "de"
g = shopify_app.winkelgegevens("demo.myshopify.com", "x")
klopt("html lang wint van het land", g["taal"] == "de")

print("\n== MET RECHT OP TALEN: WAT SHOPIFY ZEGT WINT ==")
shopify_app._graphql_eenvoudig = nep_graphql(True, [{"locale": "fr", "primary": True},
                                                    {"locale": "en", "primary": False}])
g = shopify_app.winkelgegevens("demo.myshopify.com", "x")
klopt("de hoofdtaal van Shopify", g["taal"] == "fr")

print("\n== NEDERLAND EN BELGIE ZONDER BRON: NEDERLANDS ==")
shopify_app._graphql_eenvoudig = nep_graphql(False)
shopify_app._taal_van_etalage = lambda adres: None
WINKEL_DATA["shop"]["billingAddress"]["countryCodeV2"] = "BE"
klopt("BE geeft nl", shopify_app.winkelgegevens("demo.myshopify.com", "x")["taal"] == "nl")

print("\n== HTML LANG LEZEN ==")


class _A:
    def __init__(self, t):
        self.text = t


echt_get = shopify_app.requests.get
shopify_app.requests.get = lambda *a, **k: _A('<!doctype html><html class="x" lang="en-US"><head>')
import importlib  # noqa: E402
lezer = importlib.reload(shopify_app)._taal_van_etalage
klopt("en-US uit de pagina", lezer("demo.myshopify.com") == "en-US")
shopify_app.requests.get = lambda *a, **k: (_ for _ in ()).throw(OSError("dicht"))
klopt("mislukt is None, geen fout", lezer("demo.myshopify.com") is None)
shopify_app.requests.get = echt_get

print("\n== 2. UNDO ==")
scherm = lees("templates/shopify_app.html")
klopt("na toepassen gaan de toegepaste regels uit de lijst",
      "(d.gedaan || []).concat(d.overgeslagen || [])" in scherm and ".remove();" in scherm)
klopt("undo met de lijst uit beeld begint met een lege lijst",
      "if (voorstelBlok.style.display === 'none') { voorstellen.innerHTML = ''; }" in scherm)
klopt("geen belofte meer dat het altijd opnieuw kan",
      "apply it again whenever you want" not in scherm)
klopt("zijn de gratis op, dan zegt het scherm dat", "free changes are used, so applying it again" in scherm)
bron = lees("app.py")
klopt("de server vertelt bij undo of het opnieuw mag",
      "betaalt, plan, over = _shopify_tegoed(winkel, rij, webshop_url)" in bron)
import app as appmod  # noqa: E402
klopt("terugzetten geeft geen gratis wijziging terug (teller loopt alleen op)",
      "ooit = max(al_gedaan, int(rij.get(\"wijzigingen_ooit\") or 0))" in bron)

print("\n== 3. TEKENS ==")
klopt("&#x27; wordt een apostrof",
      appmod._zonder_opmaak("<p>zonder allerlei extra&#x27;s.</p>") == "zonder allerlei extra's.")
klopt("&amp; en &nbsp; blijven werken",
      appmod._zonder_opmaak("A&amp;B&nbsp;C") == "A&B C")

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: juiste taal, Undo doet wat hij zegt, nette tekens.")
