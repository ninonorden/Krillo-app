"""Bewaakt dat de klantpagina niet half Nederlands en half Engels wordt.

Dit ging mis en het is precies het soort fout dat je zelf niet meer ziet. De
inhoud van de pagina komt uit de meting en is allang tweetalig, maar de kopjes
stonden hard in het sjabloon. Een Engelse winkel kreeg dus "Wat je deze week
doet" boven Engelse taken, en "verbeterpunt" naast Engelse uitleg.

Voor Shopify is dit geen schoonheidsfoutje. Een beoordelaar opent de app, ziet
een pagina in een taal die hij niet leest, en wijst hem af.

Het tweede stuk gaat over geld. Een winkel die via Shopify betaalt zag hier
"je betaalt 39 euro per maand" met een opzegknop die de incasso bij Mollie
opzegt. Die incasso bestaat voor zo'n winkel niet. Iemand die erop drukt denkt
dat hij het geregeld heeft terwijl Shopify hem blijft factureren. Dat is een
onjuiste mededeling over een betalingsverplichting.
"""
import html
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

from jinja2 import Environment, FileSystemLoader  # noqa: E402
import paginataal  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


env = Environment(loader=FileSystemLoader(TEMPLATES))
env.filters.setdefault("urlencode", lambda s: s)

PAGINAS = ("monitoring.html", "monitoring_details.html")


def context(taal, shopify=None, abonnement=True):
    t = paginataal.teksten(taal)
    return dict(
        t=t, paginataal=taal, shopify_beheer=shopify,
        status_labels={"ok": t["stand_ok"], "deels": t["stand_deels"],
                       "probleem": t["stand_probleem"]},
        webshop_url="https://voorbeeld.nl", klant_token="tok", voorbeeld=False,
        sleutel="K", taakstand=None, abonnement=abonnement,
        laatste=None, verschil=None, verloop=[], nieuwe_problemen=[],
        checks_by_categorie={}, uitvoering=None, wijzigingen=[],
        vermeldingen=None, controle=None, beweging=None, bronnen=None,
        verklaring=None, actieplan={"kop": "Kop", "acties": [], "rest": 0,
                                    "toelichting": ""},
        categorie_labels={}, categorieen={},
    )


def zichtbaar(pagina, **kw):
    """De tekst die een bezoeker echt leest, zonder opmaak en zonder script."""
    uit = env.get_template(pagina).render(**kw)
    kaal = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", uit, flags=re.S)
    return uit, html.unescape(re.sub(r"<[^>]+>", " ", kaal))


print("\n== beide talen kennen precies dezelfde sleutels ==")
nl = set(paginataal.TEKSTEN["nl"])
en = set(paginataal.TEKSTEN["en"])
zo("niets alleen in het Nederlands", sorted(nl - en), [])
zo("niets alleen in het Engels", sorted(en - nl), [])
klopt("en het zijn er niet een handvol", len(nl) > 100)

print("\n== het sjabloon gebruikt geen sleutel die niet bestaat ==")
# Zonder deze controle levert een typefout een lege plek op de pagina op, en
# dat zie je pas als een klant het meldt.
gebruikt = set()
for p in PAGINAS:
    gebruikt |= set(re.findall(r"\bt\.([a-zA-Z_][a-zA-Z0-9_]*)",
                               open(os.path.join(TEMPLATES, p)).read()))
zo("elke gebruikte sleutel bestaat", sorted(gebruikt - nl), [])
klopt("en er wordt er flink gebruik van gemaakt", len(gebruikt) > 100)

print("\n== geen gedachtestreepjes, in geen van beide talen ==")
streepjes = [f"{taal}:{k}" for taal, d in paginataal.TEKSTEN.items()
             for k, v in d.items() if isinstance(v, str) and ("—" in v or "–" in v)]
zo("nergens een gedachtestreepje", streepjes, [])

print("\n== een Engelse winkel ziet nergens Nederlands ==")
# Woorden die in het Engels niet bestaan. Bewust geen woorden als "week",
# "scan" of "per", want die zijn in beide talen goed en zouden een valse
# fout geven. "per month" is correct Engels en liet deze test eerst omvallen.
NEDERLANDS = re.compile(
    r"\b(je|jij|jouw|wij|niet|deze|welke|winkel|winkels|wordt|meting|metingen|"
    r"vraag|vragen|hoe|waarom|geen|meer|zijn|staat|hier|alle|ook|nog|maar|"
    r"genoemd|aanbevolen|verbeterpunt|abonnement|opzeggen|bekijken)\b",
    re.I)
for p in PAGINAS:
    _, tekst = zichtbaar(p, **context("en"))
    treffers = sorted({m.group(0).lower() for m in NEDERLANDS.finditer(tekst)})
    zo(f"{p} bevat geen Nederlands", treffers, [])

print("\n== de Nederlandse pagina is niet stilletjes veranderd ==")
for p in PAGINAS:
    _, tekst = zichtbaar(p, **context("nl"))
    klopt(f"{p} is nog gewoon Nederlands", NEDERLANDS.search(tekst) is not None)

print("\n== de taal van het document zelf klopt ==")
for p in PAGINAS:
    for taal in ("nl", "en"):
        ruw, _ = zichtbaar(p, **context(taal))
        klopt(f"{p} [{taal}] heeft de juiste lang", f'lang="{taal}"' in ruw)

print("\n== een winkel die via Shopify betaalt ==")
BEHEER = "https://krill-test.myshopify.com/admin/apps/abc"
ruw, tekst = zichtbaar("monitoring.html", **context("en", shopify=BEHEER))
klopt("krijgt GEEN opzegknop van ons", 'id="opzegKnop"' not in ruw)
klopt("wel een link naar de app in Shopify", BEHEER in ruw)
klopt("en leest dat het via Shopify loopt", "through Shopify" in tekst)
klopt("er staat nergens dat hij 39 euro aan ons betaalt", "39 euro" not in tekst)

print("\n== een winkel die via ons betaalt ==")
ruw, tekst = zichtbaar("monitoring.html", **context("nl", shopify=None))
klopt("krijgt wel de opzegknop", 'id="opzegKnop"' in ruw)
klopt("en leest wat hij betaalt", "39 euro per maand" in tekst)

print("\n== een winkel zonder abonnement krijgt geen opzegknop ==")
ruw, _ = zichtbaar("monitoring.html", **context("nl", abonnement=False))
klopt("geen opzegknop", 'id="opzegKnop"' not in ruw)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
