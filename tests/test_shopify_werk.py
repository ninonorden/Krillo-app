"""Het aanpassen met een knop in een Shopify-winkel.

Dit bestand schrijft in de winkel van een klant. Dat is het spannendste wat
Krillo doet, dus de test gaat vooral over wat er NIET mag gebeuren:

- Werk van de eigenaar overschrijven. Staat er al een tekst, dan blijven wij
  eraf, ook als die tekst er tussen het voorstel en de knop bij gekomen is.
- Iets veranderen zonder dat de oude waarde bewaard is. Lukt het bewaren niet,
  dan mag er niet geschreven worden, want dan kan de klant niets terugzetten.
- In het overzicht zetten dat wij iets veranderd hebben terwijl het schrijven
  mislukte.
- Tekst aannemen die het scherm meestuurt. Wij gebruiken alleen wat wij zelf
  gemaakt hebben.
"""
import json
import os
import sys
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["SHOPIFY_API_KEY"] = "testklant"
os.environ["SHOPIFY_API_SECRET"] = "testgeheim"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


nep = types.ModuleType("payments")
nep.AUDIT_PRICE = nep.MONITORING_PRICE = nep.UITVOERING_PRICE = {"currency": "EUR", "value": "1"}
for naam in ("create_audit_payment", "create_monitoring_signup", "create_uitvoering_payment"):
    setattr(nep, naam, lambda *a, **k: {"error": "niet in deze test"})
nep.get_payment_status = lambda pid: None
nep.create_subscription = lambda cid: {}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {"ok": True}
sys.modules["payments"] = nep

import db
import shopify_werk

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

WINKEL = "testwinkel.myshopify.com"
SLEUTEL = "shpat_test"
KLANT = "https://testwinkel.nl"

# ------------------------------------------------------- een nagemaakte winkel

class NepWinkel:
    """Een Shopify-winkel in het geheugen. Onthoudt wat er geschreven wordt.

    Wij praten sinds de overstap alleen nog via GraphQL met Shopify, dus deze
    nagemaakte winkel antwoordt ook op vragen en mutaties in plaats van op
    adressen. De nummers houden wij binnenin gewoon als getal bij; naar buiten
    toe komen ze eruit als "gid://shopify/Product/1", precies zoals Shopify
    dat doet."""

    def __init__(self):
        self.producten = [
            {"id": 1, "title": "Wollen plaid grijs", "product_type": "Wonen",
             "vendor": "Huismerk", "tags": "wol,plaid", "body_html": "",
             "handle": "plaid", "variants": [{"price": "59.00"}],
             "images": [{"id": 11, "alt": "", "src": "https://x/1.jpg"},
                        {"id": 12, "alt": "Al ingevuld", "src": "https://x/2.jpg"}]},
            {"id": 2, "title": "Keramieken mok", "product_type": "Keuken",
             "vendor": "Huismerk", "tags": "mok", "handle": "mok",
             "body_html": "<p>" + ("Een uitgebreide beschrijving. " * 12) + "</p>",
             "variants": [{"price": "14.00"}],
             "images": [{"id": 21, "alt": "", "src": "https://x/3.jpg"}]},
        ]
        self.paginas = []
        self.geschreven = []
        # Wat er kapot moet gaan. In faalt_op zetten wij een naam van een
        # bewerking die een echte fout geeft, in klaagt_op een bewerking die
        # een keurige 200 teruggeeft met een klacht in userErrors. Dat tweede
        # geval is de valkuil van GraphQL en moet dus net zo goed als
        # mislukking gelden.
        self.faalt_op = set()
        self.klaagt_op = set()

    def zoek_product(self, pid):
        return next((p for p in self.producten if p["id"] == int(pid)), None)

    def zoek_afbeelding(self, pid, aid):
        product = self.zoek_product(pid)
        return next((a for a in product["images"] if a["id"] == int(aid)), None)

    def zoek_afbeelding_overal(self, aid):
        for product in self.producten:
            for afbeelding in product["images"]:
                if afbeelding["id"] == int(aid):
                    return afbeelding
        return None

    def product_naar_graphql(self, p):
        return {
            "id": f"gid://shopify/Product/{p['id']}",
            "title": p["title"], "handle": p["handle"],
            "descriptionHtml": p.get("body_html") or "",
            "productType": p["product_type"], "vendor": p["vendor"],
            "tags": [t for t in (p.get("tags") or "").split(",") if t],
            "media": {"nodes": [
                {"id": f"gid://shopify/MediaImage/{a['id']}", "alt": a["alt"],
                 "image": {"url": a["src"]}} for a in p["images"]]},
            "variants": {"nodes": p.get("variants") or []},
        }


winkel = NepWinkel()


def _nummer_uit(gid):
    return int(str(gid).rstrip("/").split("/")[-1])


def nep_graphql(w, sleutel, vraag, variabelen=None):
    """De winkel die antwoordt zoals Shopify dat doet: data eruit bij een
    vraag, en bij een mutatie altijd ook een lijstje userErrors."""
    v = variabelen or {}

    def ok(gegevens):
        return {"gelukt": True, "gegevens": gegevens}

    def klacht(naam, veld, bericht):
        return ok({naam: {"userErrors": [{"field": [veld], "message": bericht}]}})

    if "query Producten" in vraag:
        if "producten" in winkel.faalt_op:
            return {"gelukt": False, "fout": "Shopify gaf 500: kapot"}
        return ok({"products": {
            "nodes": [winkel.product_naar_graphql(p) for p in winkel.producten],
            "pageInfo": {"hasNextPage": False, "endCursor": None}}})

    if "query Paginas" in vraag:
        return ok({"pages": {
            "nodes": [{"id": f"gid://shopify/Page/{p['id']}", "title": p["title"],
                       "handle": p["handle"], "body": p.get("body_html") or ""}
                      for p in winkel.paginas],
            "pageInfo": {"hasNextPage": False, "endCursor": None}}})

    if "query Foto" in vraag:
        afbeelding = winkel.zoek_afbeelding_overal(_nummer_uit(v["id"]))
        if afbeelding is None:
            return ok({"node": None})
        return ok({"node": {"id": v["id"], "alt": afbeelding["alt"]}})

    if "query Producttekst" in vraag:
        nummer = _nummer_uit(v["id"])
        if f"tekst:{nummer}" in winkel.faalt_op:
            return {"gelukt": False, "fout": "Shopify gaf 500: kapot"}
        product = winkel.zoek_product(nummer)
        if product is None:
            return ok({"product": None})
        return ok({"product": {"id": v["id"],
                               "descriptionHtml": product.get("body_html") or ""}})

    if "mutation ZetAlt" in vraag:
        bestand = v["bestanden"][0]
        nummer = _nummer_uit(bestand["id"])
        if "alt schrijven" in winkel.faalt_op:
            return {"gelukt": False, "fout": "Shopify gaf 500: kapot"}
        if "alt schrijven" in winkel.klaagt_op:
            return klacht("fileUpdate", "alt", "Alt text is too long")
        afbeelding = winkel.zoek_afbeelding_overal(nummer)
        afbeelding["alt"] = bestand["alt"]
        winkel.geschreven.append(("alt", nummer, afbeelding["alt"]))
        return ok({"fileUpdate": {"files": [{"id": bestand["id"], "alt": bestand["alt"]}],
                                  "userErrors": []}})

    if "mutation ZetTekst" in vraag:
        nummer = _nummer_uit(v["product"]["id"])
        if f"tekst schrijven:{nummer}" in winkel.faalt_op:
            return {"gelukt": False, "fout": "Shopify gaf 500: kapot"}
        if f"tekst schrijven:{nummer}" in winkel.klaagt_op:
            return klacht("productUpdate", "descriptionHtml", "Er ging iets mis")
        product = winkel.zoek_product(nummer)
        product["body_html"] = v["product"]["descriptionHtml"]
        winkel.geschreven.append(("tekst", nummer, product["body_html"]))
        return ok({"productUpdate": {"product": {"id": v["product"]["id"]},
                                     "userErrors": []}})

    if "mutation MaakPagina" in vraag:
        if "pagina maken" in winkel.klaagt_op:
            return klacht("pageCreate", "handle", "Handle bestaat al")
        nieuw = {"id": 99, "title": v["pagina"]["title"], "handle": v["pagina"]["handle"],
                 "body_html": v["pagina"]["body"], "published": v["pagina"]["isPublished"]}
        winkel.paginas.append(nieuw)
        winkel.geschreven.append(("pagina", 99, nieuw["body_html"]))
        return ok({"pageCreate": {"page": {"id": "gid://shopify/Page/99",
                                           "title": nieuw["title"],
                                           "handle": nieuw["handle"]},
                                  "userErrors": []}})

    if "mutation VerwijderPagina" in vraag:
        nummer = _nummer_uit(v["id"])
        winkel.paginas = [p for p in winkel.paginas if p["id"] != nummer]
        winkel.geschreven.append(("pagina weg", nummer, None))
        return ok({"pageDelete": {"deletedPageId": v["id"], "userErrors": []}})

    return {"gelukt": False, "fout": f"onbekende vraag: {vraag[:40]}"}


echte_graphql = shopify_werk._graphql
shopify_werk._graphql = nep_graphql

# ------------------------------------------------- nummers uit gid en terug

print("\n== van gid naar kenmerk en terug ==")
zo("het nummer uit een product-gid",
   shopify_werk._nummer("gid://shopify/Product/123"), 123)
zo("het nummer uit een foto-gid",
   shopify_werk._nummer("gid://shopify/MediaImage/456"), 456)
zo("een kaal nummer blijft een nummer", shopify_werk._nummer("789"), 789)
zo("niets erin geeft niets terug", shopify_werk._nummer(None), "")
zo("en er weer een gid van maken",
   shopify_werk._gid("Product", shopify_werk._nummer("gid://shopify/Product/123")),
   "gid://shopify/Product/123")
zo("een gid dat er al een is blijft heel",
   shopify_werk._gid("MediaImage", "gid://shopify/MediaImage/456"),
   "gid://shopify/MediaImage/456")
zo("het kenmerk houdt zijn oude vorm",
   f"shopify:alt:{shopify_werk._nummer('gid://shopify/Product/1')}:"
   f"{shopify_werk._nummer('gid://shopify/MediaImage/11')}", "shopify:alt:1:11")

# ------------------------------------------------------------- wat er mis is

print("\n== wat er ontbreekt ==")
gebreken = shopify_werk.zoek_gebreken(WINKEL, SLEUTEL)
zo("twee producten bekeken", gebreken["producten_bekeken"], 2)
zo("twee foto's zonder beschrijving", len(gebreken["zonder_alt"]), 2)
zo("de foto die er wel een heeft blijft buiten schot",
   any(r["afbeelding_id"] == 12 for r in gebreken["zonder_alt"]), False)
zo("een product zonder tekst", len(gebreken["dunne_tekst"]), 1)
zo("het product met een echte tekst telt niet mee",
   gebreken["dunne_tekst"][0]["product_id"], 1)
zo("er is nog geen pagina met vragen", gebreken["heeft_faq"], False)

winkel.paginas.append({"id": 5, "title": "Veelgestelde vragen", "handle": "faq",
                       "body_html": "<p>x</p>"})
zo("een bestaande vragenpagina wordt gezien",
   shopify_werk.zoek_gebreken(WINKEL, SLEUTEL)["heeft_faq"], True)
winkel.paginas.clear()

print("\n== HTML telt niet mee als tekst ==")
zo("lege opmaak is geen tekst",
   len(shopify_werk._kale_tekst("<div><p>&nbsp;</p><br></div>")) < 5, True)
zo("echte tekst wel",
   shopify_werk._kale_tekst("<p>Hallo <b>daar</b></p>"), "Hallo daar")

# ------------------------------------------------------------- toepassen

print("\n== een beschrijving bij een foto zetten ==")
voorstel = {"id": "shopify:alt:1:11", "soort": "alt", "wat": "Beschrijving bij een foto",
            "waar": "Wollen plaid grijs (foto)", "nieuw": "Grijze wollen plaid",
            "product_id": 1, "afbeelding_id": 11}
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, voorstel, KLANT)
zo("gelukt", uit["gelukt"], True)
zo("hij staat in de winkel", winkel.zoek_afbeelding(1, 11)["alt"], "Grijze wollen plaid")
bewaard = [w for w in db.get_wijzigingen(KLANT) if w["taak_id"] == "shopify:alt:1:11"]
zo("de wijziging is vastgelegd", len(bewaard), 1)
zo("met de oude waarde erbij", bewaard[0]["oude_waarde"], "")

print("\n== werk van de eigenaar blijft staan ==")
voorstel2 = dict(voorstel, id="shopify:alt:1:12", afbeelding_id=12,
                 nieuw="Wij weten het beter")
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, voorstel2, KLANT)
zo("wij slaan hem over", uit.get("overgeslagen"), True)
zo("en schrijven niets", winkel.zoek_afbeelding(1, 12)["alt"], "Al ingevuld")

print("\n== een tekst die er tussendoor bij kwam ==")
# De eigenaar vulde zelf een tekst in tussen het voorstel en de knop.
winkel.zoek_product(1)["body_html"] = "<p>" + ("Zelf geschreven tekst. " * 12) + "</p>"
tekstvoorstel = {"id": "shopify:tekst:1", "soort": "tekst", "wat": "Producttekst",
                 "waar": "Wollen plaid grijs", "nieuw": "Onze tekst",
                 "nieuw_html": "<p>Onze tekst</p>", "product_id": 1}
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, tekstvoorstel, KLANT)
zo("wij blijven eraf", uit.get("overgeslagen"), True)
zo("zijn tekst staat er nog",
   "Zelf geschreven" in winkel.zoek_product(1)["body_html"], True)

winkel.zoek_product(1)["body_html"] = ""
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, tekstvoorstel, KLANT)
zo("bij een lege tekst schrijven wij wel", uit["gelukt"], True)
zo("de nieuwe tekst staat erin", winkel.zoek_product(1)["body_html"], "<p>Onze tekst</p>")

print("\n== als het bewaren niet lukt, schrijven wij niet ==")
echte_bewaar = db.bewaar_wijziging
db.bewaar_wijziging = lambda **kw: False
winkel.zoek_product(2)["body_html"] = ""
voorstel3 = {"id": "shopify:tekst:2", "soort": "tekst", "wat": "Producttekst",
             "waar": "Keramieken mok", "nieuw": "Iets", "nieuw_html": "<p>Iets</p>",
             "product_id": 2}
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, voorstel3, KLANT)
zo("het wordt geweigerd", uit["gelukt"], False)
zo("met een uitleg die klopt", "terug" in uit["fout"], True)
zo("en er is niets geschreven", winkel.zoek_product(2)["body_html"], "")
db.bewaar_wijziging = echte_bewaar

print("\n== als het schrijven mislukt, staat er niets in het overzicht ==")
winkel.faalt_op.add("tekst schrijven:2")
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, voorstel3, KLANT)
zo("het mislukt", uit["gelukt"], False)
zo("de vastgelegde wijziging is weer weg",
   any(w["taak_id"] == "shopify:tekst:2" for w in db.get_wijzigingen(KLANT)), False)
winkel.faalt_op.clear()

print("\n== een klacht van Shopify telt net zo hard als een fout ==")
# GraphQL geeft ook bij een mislukte mutatie gewoon een 200 terug. Wat er mis
# ging staat binnenin, in userErrors. Wie daar niet naar kijkt vertelt de
# eigenaar dat het gelukt is terwijl er niets veranderd is.
winkel.klaagt_op.add("tekst schrijven:2")
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, voorstel3, KLANT)
zo("het geldt als mislukt", uit["gelukt"], False)
zo("de klacht zelf staat in de uitleg", "Er ging iets mis" in uit["fout"], True)
zo("ook nu staat er niets in het overzicht",
   any(w["taak_id"] == "shopify:tekst:2" for w in db.get_wijzigingen(KLANT)), False)
zo("en er is niets geschreven", winkel.zoek_product(2)["body_html"], "")
winkel.klaagt_op.clear()

winkel.klaagt_op.add("alt schrijven")
altvoorstel = {"id": "shopify:alt:2:21", "soort": "alt", "wat": "Beschrijving bij een foto",
               "waar": "Keramieken mok (foto)", "nieuw": "Witte keramieken mok",
               "product_id": 2, "afbeelding_id": 21}
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, altvoorstel, KLANT)
zo("ook bij een foto geldt een klacht als mislukt", uit["gelukt"], False)
zo("de foto is niet aangepast", winkel.zoek_afbeelding(2, 21)["alt"], "")
winkel.klaagt_op.clear()

print("\n== de pagina met vragen ==")
faq = {"id": "shopify:faq", "soort": "faq", "wat": "Nieuwe pagina met veelgestelde vragen",
       "waar": "Winkel, Pagina's", "nieuw": "Vraag\nAntwoord",
       "nieuw_html": "<h2>Vraag</h2><p>Antwoord</p>"}
uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, faq, KLANT)
zo("de pagina is gemaakt", uit["gelukt"], True)
zo("er staat er precies een", len(winkel.paginas), 1)
zo("hij staat online", winkel.paginas[0]["published"], True)

uit = shopify_werk.pas_toe(WINKEL, SLEUTEL, faq, KLANT)
zo("een tweede keer maakt geen tweede pagina", uit.get("overgeslagen"), True)
zo("het blijft er een", len(winkel.paginas), 1)

# ------------------------------------------------------------- terugzetten

print("\n== terugzetten ==")
w = [x for x in db.get_wijzigingen(KLANT) if x["taak_id"] == "shopify:alt:1:11"][0]
uit = shopify_werk.zet_terug(WINKEL, SLEUTEL, w, KLANT)
zo("gelukt", uit["gelukt"], True)
zo("de oude waarde staat er weer", winkel.zoek_afbeelding(1, 11)["alt"], "")

w = [x for x in db.get_wijzigingen(KLANT) if x["taak_id"] == "shopify:tekst:1"][0]
uit = shopify_werk.zet_terug(WINKEL, SLEUTEL, w, KLANT)
zo("de producttekst is terug", winkel.zoek_product(1)["body_html"], "")

w = [x for x in db.get_wijzigingen(KLANT) if x["taak_id"] == "shopify:faq"][0]
uit = shopify_werk.zet_terug(WINKEL, SLEUTEL, w, KLANT)
zo("de pagina is weer weg", len(winkel.paginas), 0)

zo("een wijziging die niet van ons is wordt geweigerd",
   shopify_werk.zet_terug(WINKEL, SLEUTEL, {"taak_id": "faq", "oude_waarde": ""},
                          KLANT)["gelukt"], False)

# --------------------------------------------------------- te druk bij Shopify

print("\n== als het te druk is, proberen wij het nog eens ==")
# Hier zetten wij de echte praatfunctie even terug, want juist die moet dit
# doen. Alleen het versturen zelf maken wij na. GraphQL zegt niet met een
# foutcode dat het te druk is, maar met een gewone 200 en THROTTLED in de
# foutenlijst. Wie alleen naar de foutcode kijkt, ziet dat dus nooit.


class NepAntwoord:
    def __init__(self, lichaam, code=200):
        self.status_code = code
        self.text = json.dumps(lichaam)
        self._lichaam = lichaam

    def json(self):
        return self._lichaam


class NepRequests:
    def __init__(self, antwoorden):
        self.antwoorden = list(antwoorden)
        self.aantal = 0

    def post(self, *a, **k):
        self.aantal += 1
        return self.antwoorden.pop(0)


shopify_werk._graphql = echte_graphql
shopify_werk.WACHT_BIJ_DRUKTE = 0
echte_requests = shopify_werk.requests

druk = NepAntwoord({"errors": [{"message": "Throttled",
                                "extensions": {"code": "THROTTLED"}}]})
goed = NepAntwoord({"data": {"pages": {"nodes": [], "pageInfo": {"hasNextPage": False}}}})
shopify_werk.requests = NepRequests([druk, goed])
uit = shopify_werk._graphql(WINKEL, SLEUTEL, "query Paginas { pages { nodes { id } } }")
zo("na het wachten lukt het alsnog", uit["gelukt"], True)
zo("en het is twee keer geprobeerd", shopify_werk.requests.aantal, 2)

shopify_werk.requests = NepRequests([druk, druk, druk])
uit = shopify_werk._graphql(WINKEL, SLEUTEL, "query Paginas { pages { nodes { id } } }")
zo("blijft het druk, dan melden wij dat gewoon", uit["gelukt"], False)
zo("wij blijven niet eindeloos doorgaan", shopify_werk.requests.aantal, 3)

fout = NepAntwoord({"errors": [{"message": "Field 'nonsens' doesn't exist"}]})
shopify_werk.requests = NepRequests([fout])
uit = shopify_werk._graphql(WINKEL, SLEUTEL, "query Paginas { pages { nonsens } }")
zo("een gewone fout in het antwoord is meteen een mislukking", uit["gelukt"], False)
zo("ook al gaf Shopify er een 200 bij", shopify_werk.requests.aantal, 1)

shopify_werk.requests = echte_requests
shopify_werk._graphql = nep_graphql

# ------------------------------------------------------------- het model

print("\n== zonder sleutel voor het model ==")
oud = os.environ.pop("ANTHROPIC_API_KEY", None)
uit = shopify_werk.maak_alt_voorstellen(WINKEL, SLEUTEL, gebreken, None)
zo("het meldt zich netjes", uit["gelukt"], False)
zo("met een reden", "ANTHROPIC" in (uit["fout"] or ""), True)
zo("en geen voorstellen", uit["voorstellen"], [])
if oud:
    os.environ["ANTHROPIC_API_KEY"] = oud

print("\n== wat het model teruggeeft wordt nagelopen ==")
os.environ["ANTHROPIC_API_KEY"] = "nep"


class NepClient:
    def __init__(self, antwoord):
        self.antwoord = antwoord


def nep_model(webshop_url):
    return NepClient(None), None


shopify_werk._model = nep_model
shopify_werk._vraag_json = lambda c, p, u, s, max_tokens=4000: [
    {"nummer": 0, "tekst": "Grijze wollen plaid"},
    {"nummer": 1, "tekst": ""},                 # leeg, moet eruit
    {"nummer": 99, "tekst": "Bestaat niet"},    # verwijst nergens naar
    {"tekst": "Zonder nummer"},                 # onbruikbaar
]
gebreken = shopify_werk.zoek_gebreken(WINKEL, SLEUTEL)
uit = shopify_werk.maak_alt_voorstellen(WINKEL, SLEUTEL, gebreken, None)
zo("alleen het bruikbare voorstel blijft over", len(uit["voorstellen"]), 1)
zo("met de juiste tekst", uit["voorstellen"][0]["nieuw"], "Grijze wollen plaid")
zo("en het juiste kenmerk", uit["voorstellen"][0]["id"].startswith("shopify:alt:"), True)

shopify_werk._vraag_json = lambda *a, **k: (_ for _ in ()).throw(ValueError("kapot"))
uit = shopify_werk.maak_alt_voorstellen(WINKEL, SLEUTEL, gebreken, None)
zo("een kapot antwoord van het model laat niets klappen", uit["gelukt"], False)
zo("en levert geen voorstellen op", uit["voorstellen"], [])

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
