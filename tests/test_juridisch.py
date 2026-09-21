"""De juridische pagina's en het mailadres, sinds 21 september.

WAAROM DEZE TEST BESTAAT

Tot 21 september stonden de voorwaarden, het privacybeleid en het
herroepingsformulier in het Nederlands op een Engelse site. Erger: ze
beschreven producten die niet meer bestaan. Een eenmalige audit en een
"monitoring-abonnement" met een wekelijkse meting, terwijl de site Watch, Fix
en een pakket voor merken verkoopt, per maand. Voorwaarden die over iets anders
gaan dan wat iemand koopt zijn in een geschil niets waard, en ze laten een
koper twijfelen op het moment dat hij wil betalen.

Tegelijk ging het mailadres over van hallo@krillo.nl naar hello@krilloai.com.
Het oude adres ontvangt niets meer (ImprovMX gratis kent een domein). Een
achtergebleven hallo@krillo.nl op een foutmelding of in een mail betekent een
klant die ons mailt en nooit antwoord krijgt.

Deze test bewaakt:
- dat de drie pagina's Engels zijn en de pakketten en prijzen van nu noemen;
- dat de oude producten er niet meer in staan;
- dat nergens in de code of de sjablonen nog een @krillo.nl-adres staat;
- dat er geen gedachtestreep in staat (huisregel van Nino).
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import payments  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


def zichtbaar(html):
    """Alleen de tekst die een bezoeker leest: zonder style, script en tags."""
    html = re.sub(r"<(style|script)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


PAGINAS = ("voorwaarden.html", "privacybeleid.html", "herroepen.html")

print("\n== DE DRIE PAGINA'S ZIJN ENGELS ==")
for naam in PAGINAS:
    html = lees(f"templates/{naam}")
    tekst = zichtbaar(html)
    klopt(f"{naam}: lang=en", '<html lang="en">' in html)
    for nl in (" je ", " wij ", " het ", " een ", "Terug naar", "Algemene voorwaarden"):
        klopt(f"{naam}: geen Nederlands {nl.strip()!r} in de zichtbare tekst", nl not in tekst)
    klopt(f"{naam}: geen gedachtestreep", "—" not in html)

print("\n== DE VOORWAARDEN GAAN OVER WAT WE NU VERKOPEN ==")
v = zichtbaar(lees("templates/voorwaarden.html"))
for sleutel, pakket in payments.PAKKETTEN.items():
    euro = str(int(float(pakket["prijs"]["value"])))
    klopt(f"{pakket['naam']} staat erin met {euro} euro per maand",
          f"{euro} euro per month" in v)
for oud in ("audit", "monitoring", "39 euro", "every week we ask", "Every week we ask"):
    klopt(f"geen oud product of oude belofte: {oud!r}", oud not in v)
klopt("zegt dat een plek in de index niet te koop is", "Nobody can buy a place" in v)
klopt("zegt dat de categorie elke maand gemeten wordt", "every month" in v)

print("\n== NERGENS NOG EEN ADRES OP HET OUDE DOMEIN ==")
bestanden = [f for f in glob.glob(os.path.join(APP, "*.py")) + glob.glob(os.path.join(APP, "templates", "*.html"))]
oud = []
for f in bestanden:
    for i, regel in enumerate(open(f, encoding="utf-8"), 1):
        if re.search(r"[a-z0-9._-]+@(www\.)?krillo\.nl", regel):
            oud.append(f"{os.path.basename(f)}:{i}")
klopt(f"geen @krillo.nl meer (gevonden: {oud})", not oud)
klopt("de afzender valt terug op het nieuwe adres",
      'os.environ.get("SMTP_FROM_EMAIL", "hello@krilloai.com")' in lees("emailing.py"))
klopt("llms.txt noemt het nieuwe adres", "hello@krilloai.com" in lees("app.py"))
# Het toegangsadres is Engels, net als de site (besluit Nino, 21 september).
# In ImprovMX bestaat de alias access, niet toegang.
klopt("winkels geven toegang aan access@krilloai.com",
      "access@krilloai.com" in lees("emailing.py") and "toegang@krilloai.com" not in lees("emailing.py"))

print("\n== WAT DE CONTROLE VAN 21 SEPTEMBER VOND ==")
# Een aparte controle legde elke belofte uit deze pagina's naast de code. Dit
# zijn de punten waar de tekst of de code niet klopte, en die nu kloppen.

# 1. Zonder vinkje geen herinneringsmail. Dit draait echt tegen de database.
os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
import db  # noqa: E402
db.init_db()
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM zichtbaarheidstests WHERE email LIKE '%@jur-test.nl'")
        for adres, akkoord in (("zonder@jur-test.nl", False), ("met@jur-test.nl", True)):
            cur.execute("""INSERT INTO zichtbaarheidstests
                           (webshop_url, email, status, nieuwsbrief_akkoord, aangevraagd_op)
                           VALUES (%s, %s, 'klaar', %s, now() - interval '10 days')""",
                        (f"https://{adres.split('@')[0]}-jur.nl", adres, akkoord))
adressen = [l["email"] for l in db.leads_om_op_te_volgen(na_dagen=3, hoeveel=500)]
klopt("wie het vinkje leeg liet krijgt geen herinnering", "zonder@jur-test.nl" not in adressen)
klopt("wie het vinkje zette wel", "met@jur-test.nl" in adressen)
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM zichtbaarheidstests WHERE email LIKE '%@jur-test.nl'")

# 2. De herinnering belooft geen wekelijkse meting en zegt hoe je eraf komt.
import emailing  # noqa: E402
gevangen = {}
emailing.send_email = lambda naar, onderwerp, html, **k: gevangen.update(html=html) or True
for taal in ("en", "nl"):
    emailing.send_opvolging_gratis_test("a@b.nl", "https://winkel.nl", "https://krilloai.com", taal=taal)
    h = gevangen["html"]
    klopt(f"herinnering ({taal}) belooft geen wekelijkse meting",
          "every week" not in h and "elke week" not in h)
    klopt(f"herinnering ({taal}) zegt hoe je van alle mail af komt",
          "remove your address" in h or "halen je adres weg" in h)

# 3. De Shopify-mail zegt niet meer dat we niets aanraken wat je zelf schreef.
bron = lees("emailing.py")
klopt("geen 'did not touch anything you wrote yourself'",
      "did not touch anything you wrote yourself" not in bron)
klopt("geen 'niets aangeraakt wat jij zelf geschreven hebt'",
      "aangeraakt wat jij zelf geschreven hebt" not in bron)

# 4. Een adres met een naam erin telt niet als algemeen adres.
import contactvinder  # noqa: E402
for adres, algemeen in (("info@kaars.nl", True), ("jan.info@kaars.nl", False),
                        ("jan-shop@kaars.nl", False), ("klantenservice@kaars.nl", True)):
    klopt(f"{adres} algemeen={algemeen}",
          contactvinder._bruikbaar(adres, "kaars.nl")["algemeen"] is algemeen)

# 5. De homepage belooft niets wat de code anders doet.
home = lees("templates/index.html")
for zin in ("press approve", "the moment you drop", "Four weeks later we measure again"):
    klopt(f"homepage zegt niet meer {zin!r}", zin not in home)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de juridische pagina's kloppen met wat we verkopen.")
