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


# De echte module eerst inlezen, alleen om de BEDRAGEN over te nemen.
#
# Waarom: hieronder wordt payments vervangen door een nepmodule, zodat deze
# test niet bij Mollie langs hoeft. Die nepmodule was blijven staan in het
# oude prijstijdperk: hij kende alleen AUDIT_PRICE, MONITORING_PRICE en
# UITVOERING_PRICE, en dat zijn precies de drie producten die op 11 september
# vervallen zijn. Toen llms.txt zijn prijzen uit PAKKETTEN ging opbouwen viel
# deze test daardoor om met "module payments has no attribute PAKKETTEN",
# terwijl er niets mis was met de site.
#
# Door de bedragen uit de ECHTE module te halen kan dit nooit meer uit elkaar
# lopen: verandert een prijs, dan verandert die hier vanzelf mee.
import payments as _echte_payments  # noqa: E402

nep = types.ModuleType("payments")
nep.PAKKETTEN = _echte_payments.PAKKETTEN
nep.STANDAARD_PAKKET = _echte_payments.STANDAARD_PAKKET
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
import paginataal
env = Environment(loader=FileSystemLoader(os.path.join(MAP, "templates")))

BASIS = dict(webshop_url="https://winkel.nl", klant_token="abc", voorbeeld=False,
             actieplan={"kop": "x", "acties": [], "rest": 0}, laatste=None, verschil=None,
             verloop=[], nieuwe_problemen=[], checks_by_categorie={}, vermeldingen=None,
             controle=None, beweging=None, bronnen=None, verklaring=None, taakstand=None,
             sleutel="x", status_labels={}, wijzigingen=[],
             # De vaste teksten van de pagina. Sinds de pagina tweetalig is komen
             # die uit paginataal.py en niet meer uit het sjabloon zelf.
             t=paginataal.TEKSTEN["nl"], paginataal="nl", shopify_beheer=None,
             # Het werkblok in het dashboard heet zijn teksten wt (sinds 21 sep).
             wt=paginataal.TEKSTEN["nl"], beheer=None)

print("\n== een klant met een abonnement ==")
h = env.get_template("_werk.html").render(uitvoering=None, abonnement=True, **BASIS)
zo("ziet de opzegknop", 'id="opzegKnop"' in h, True)
zo("en de kop over zijn oplossingen",
   paginataal.TEKSTEN['nl']['titel_taken'] in h, True)
zo("en leest geen oud bedrag", "39 euro" in h, False)

print("\n== een klant die alleen de uitvoering kocht ==")
u = {"stand": "opgeleverd", "notitie": None, "opgeleverd_op": None,
     "toegang_op": None, "id": 1, "email": "a@b.nl"}
h = env.get_template("_werk.html").render(uitvoering=u, abonnement=False, **BASIS)
zo("ziet GEEN opzegknop", 'id="opzegKnop"' in h, False)
zo("leest niet dat hij per maand betaalt",
   "Je betaalt per maand" in h, False)
zo("leest dat er niets wordt afgeschreven", "Er loopt geen abonnement" in h, True)
zo("krijgt geen huiswerkkop", "Wat je deze week doet" in h, False)
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
zo("de maandpakketten staan in de gestructureerde gegevens",
   '"name": "Fix", "price": "149"' in h and '"name": "Watch", "price": "49"' in h, True)
# De navigatie is op 17 september teruggebracht tot vier links, precies zoals
# in het gekozen ontwerp. Wat bewaakt moet blijven is dat de prijzen bereikbaar
# zijn vanaf de bovenkant van de pagina.
zo("en in de navigatie", '#prijzen' in h, True)
zo("de demo gebruikt hetzelfde aantal vragen als de rest",
   "4 van de 22 koopvragen" in h, False)

print("\n== llms.txt, wat AI over ons overneemt ==")
c = krillo.app.test_client()
t = c.get("/llms.txt").get_data(as_text=True)
zo("noemt de maandpakketten", "Fix: 149 euro per maand" in t, True)
zo("zegt niet meer dat klanten het zelf regelen", "die dit zelf regelen" in t, False)
zo("verwijst naar het onderzoek", "/onderzoek" in t, True)

print("\n== voorwaarden en privacy ==")
# Sinds 21 september in het Engels. Dezelfde beloften worden bewaakt, nu in de
# taal waarin ze op de site staan.
v = open(os.path.join(MAP, "templates/voorwaarden.html"), encoding="utf-8").read()
zo("noemt de pakketten van nu", all(n in v for n in ("Watch", "Fix", "Brands and agencies")), True)
zo("heeft een artikel over werken in de winkel", "When we work in your store" in v, True)
zo("noemt de terugdraairegeling", "we roll it back" in v, True)
zo("noemt aansprakelijkheid bij ons eigen werk", "an error in our own work" in v, True)
zo("verwijst niet meer naar het opgeheven ODR-platform",
   "consumers/odr" in v, False)
zo("belooft geen weeklimiet die er niet is",
   "once per week per website" in v, False)
zo("belooft geen goedkeuringsknop die de code niet kent", "You press approve" in v, False)

pb = open(os.path.join(MAP, "templates/privacybeleid.html"), encoding="utf-8").read()
zo("zegt dat ook de gratis test naar ChatGPT gaat",
   "for the free visibility test and for the index" in pb, True)
zo("noemt Google Fonts", "Google Fonts" in pb, True)
zo("legt de toegang tot een webshop uit", "When we work in your store" in pb, True)
zo("biedt een verwerkersovereenkomst aan", "data processing agreement" in pb, True)
zo("noemt het herkomstlabel in de browser", "utm_source" in pb, True)
zo("noemt het doorsturen van mail", "ImprovMX" in pb, True)

hr = open(os.path.join(MAP, "templates/herroepen.html"), encoding="utf-8").read()
zo("herroepen noemt het werk in de winkel", "work we do in your store" in hr, True)
zo("en de eerste maand terug", "first month back" in hr, True)

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
