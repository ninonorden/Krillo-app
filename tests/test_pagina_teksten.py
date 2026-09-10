"""De teksten op de klantgerichte pagina's.

Deze test bewaakt beloften. Wat hier fout gaat kost geen foutmelding maar een
klant die zijn geld terugvraagt, of erger, een belofte die we niet kunnen
waarmaken.
"""
import os
import sys
import types
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)
MAP = APP
os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, MAP)

fouten = []


def zo(o, g, v):
    if g != v:
        fouten.append(f"FOUT: {o}: kreeg {g!r}, verwacht {v!r}")
    else:
        print(f"  ok  {o}")


nep = types.ModuleType("payments")
nep.AUDIT_PRICE = nep.MONITORING_PRICE = nep.UITVOERING_PRICE = {}
for n in ("create_audit_payment", "create_monitoring_signup", "create_uitvoering_payment"):
    setattr(nep, n, lambda *a, **k: {})
nep.get_payment_status = lambda p: None
nep.create_subscription = lambda c: {}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {}
sys.modules["payments"] = nep

import app as krillo
env = Environment(loader=FileSystemLoader(os.path.join(MAP, "templates")))

BASIS = dict(webshop_url="https://winkel.nl", klant_token="abc", voorbeeld=False,
             actieplan={"kop": "x", "acties": [], "rest": 0}, laatste=None, verschil=None,
             verloop=[], nieuwe_problemen=[], checks_by_categorie={}, vermeldingen=None,
             controle=None, beweging=None, bronnen=None, verklaring=None, taakstand=None,
             sleutel="x", status_labels={}, wijzigingen=[])

print("\n== een klant met een abonnement ==")
h = env.get_template("monitoring.html").render(uitvoering=None, abonnement=True, **BASIS)
zo("ziet de opzegknop", 'id="opzegKnop"' in h, True)
zo("en de kop over deze week", "<h1>Wat je deze week doet</h1>" in h, True)

print("\n== een klant die alleen de uitvoering kocht ==")
u = {"stand": "opgeleverd", "notitie": None, "opgeleverd_op": None,
     "toegang_op": None, "id": 1, "email": "a@b.nl"}
h = env.get_template("monitoring.html").render(uitvoering=u, abonnement=False, **BASIS)
zo("ziet GEEN opzegknop", 'id="opzegKnop"' in h, False)
zo("leest niet dat hij 39 euro per maand betaalt",
   "Je betaalt 39 euro per maand" in h, False)
zo("leest dat er niets wordt afgeschreven", "Er loopt geen abonnement" in h, True)
zo("krijgt geen huiswerkkop", "<h1>Wat je deze week doet</h1>" in h, False)
zo("maar wat wij gedaan hebben", "Wat wij voor je gedaan hebben" in h, True)
zo("krijgt geen belofte van een wekelijkse meting",
   "We stellen deze week koopvragen" in h, False)

print("\n== de homepage belooft niets wat we niet kunnen ==")
h = open(os.path.join(MAP, "templates/index.html"), encoding="utf-8").read()
zo("geen verzonnen score in een AI-antwoord", "AI-leesbaarheid van 94 van 100" in h, False)
zo("geen 'wel genoemd' als eindstand van de animatie",
   "badgeEl.textContent = 'wel genoemd'" in h, False)
zo("het label zegt voorbeeld en niet live", "Live gesimuleerd" in h, False)
zo("de audit belooft niet dat hij het oplost",
   "een audit die de verbeterpunten voor je oplost" in h, False)
zo("het product van 149 euro staat in de gestructureerde gegevens",
   '"name": "Wij doen het", "price": "149"' in h, True)
zo("en in de navigatie", '#wij-doen-het' in h, True)
zo("de demo gebruikt hetzelfde aantal vragen als de rest",
   "4 van de 22 koopvragen" in h, False)

print("\n== llms.txt, wat AI over ons overneemt ==")
c = krillo.app.test_client()
t = c.get("/llms.txt").get_data(as_text=True)
zo("noemt het product van 149 euro", "Wij doen het: 149 euro" in t, True)
zo("zegt niet meer dat klanten het zelf regelen", "die dit zelf regelen" in t, False)
zo("verwijst naar het onderzoek", "/onderzoek" in t, True)

print("\n== voorwaarden en privacy ==")
v = open(os.path.join(MAP, "templates/voorwaarden.html"), encoding="utf-8").read()
zo("kent vier vormen", "vier vormen" in v, True)
zo("heeft een artikel over de uitvoering", "De uitvoering in je webshop" in v, True)
zo("noemt de terugdraairegeling", "draaien wij hem terug" in v, True)
zo("noemt aansprakelijkheid bij ons eigen werk", "een fout in ons eigen werk" in v, True)
zo("verwijst niet meer naar het opgeheven ODR-platform",
   "consumers/odr" in v, False)
zo("belooft geen weeklimiet die er niet is",
   "maximaal één keer per week per website" in v, False)

pb = open(os.path.join(MAP, "templates/privacybeleid.html"), encoding="utf-8").read()
zo("zegt dat ook de gratis scan naar ChatGPT gaat",
   "bij de gratis scan, de gratis zichtbaarheidstest en het monitoringabonnement" in pb, True)
zo("noemt Google Fonts", "Google Fonts" in pb, True)
zo("legt de toegang tot een webshop uit", "Als wij in je webshop werken" in pb, True)
zo("biedt een verwerkersovereenkomst aan", "verwerkersovereenkomst" in pb, True)
zo("noemt het herkomstlabel in de browser", "utm_source" in pb, True)

hr = open(os.path.join(MAP, "templates/herroepen.html"), encoding="utf-8").read()
zo("herroepen noemt de uitvoering", "uitvoering in je webshop" in hr, True)
zo("en het abonnement", "maandabonnement" in hr, True)

print("\n== de toegangsmail kent de platforms die op de site staan ==")
import emailing
for platform in ["Shopify", "WooCommerce", "Lightspeed", "Shopware", "CCV Shop", "PrestaShop"]:
    zo(f"{platform} heeft eigen stappen", platform in emailing.TOEGANG_UITLEG, True)

print("\n== de wekelijkse mail claimt geen oorzaak ==")
e = open(os.path.join(MAP, "emailing.py"), encoding="utf-8").read()
zo("geen 'je aanpassingen werken'", "Je aanpassingen werken" in e, False)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
