"""Drie kleine punten van 24 september.

WAAROM DEZE TEST BESTAAT

1. Google Search Console meldde /mijn-link als "geindexeerd, hoewel
   geblokkeerd door robots.txt". De pagina heeft een noindex-tag, maar Google
   kan die tag alleen lezen als robots.txt hem de pagina laat ophalen. De
   Disallow moet er dus uit blijven en de noindex erin.
2. De artikelen zijn naar het Engels vertaald, maar de pagina's eromheen
   (kop, knoppen, "lezen", "Terug naar de website") stonden nog in het
   Nederlands, en beloofden een "scan op dertien punten" die de homepage niet
   meer aanbiedt.
3. Brave weigerde met een leeg tegoed elke zoekopdracht, en de code bleef het
   tientallen keren per ronde proberen. Nu stopt hij voor de rest van de dag,
   maar alleen bij een echt leeg tegoed, niet bij "even te snel".
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


print("\n== 1. /mijn-link: WEL OPHALEN, NIET INDEXEREN ==")
bron = lees("app.py")
i = bron.index("def robots_txt(")
robots = bron[i:bron.index("\n@app.route", i)]
klopt("geen Disallow meer voor /mijn-link", "Disallow: /mijn-link" not in robots)
klopt("de klantpagina's blijven wel dicht", "Disallow: /mijn/" in robots)
klopt("de pagina zelf zegt noindex",
      '<meta name="robots" content="noindex">' in lees("templates/mijn_link.html"))

print("\n== 2. DE ARTIKELPAGINA'S ZIJN ENGELS ==")
for naam in ("templates/artikel.html", "templates/artikelen.html"):
    s = lees(naam)
    klopt(f"{naam}: taal staat op Engels", '<html lang="en">' in s)
    for nl in ("Terug naar de website", "Gratis scan", " lezen<", "Lees verder",
               "Meer lezen", "dertien punten", "nl_NL", "nl-NL"):
        klopt(f"{naam}: geen '{nl.strip()}'", nl not in s)
import artikelen  # noqa: E402
klopt("de leestijd in de artikelen is Engels",
      all("minute" in a["leestijd"] for a in artikelen.ARTIKELEN)
      if hasattr(artikelen, "ARTIKELEN") else "minutes" in lees("artikelen.py"))
klopt("geen oud domein in de artikelen", "krillo.nl" not in lees("artikelen.py"))

print("\n== 3. BRAVE: LEEG TEGOED STOPT DE DAG, TE SNEL NIET ==")
import bronnen  # noqa: E402
import kosten  # noqa: E402
kosten.registreer_vaste_kosten = lambda **k: None


class Antwoord:
    def __init__(self, status, tekst):
        self.status_code, self.text = status, tekst


class Fout(Exception):
    def __init__(self, status, tekst):
        super().__init__(f"{status}")
        self.response = Antwoord(status, tekst)


pogingen = []


def zoeker_met(status, tekst):
    def z(vraag, land=None, taal=None):
        pogingen.append(vraag)
        raise Fout(status, tekst)
    return z


bronnen.MIN_INTERVAL = 0
bronnen._ZOEKERS[bronnen.ZOEK_AANBIEDER] = zoeker_met(
    429, '{"error":{"code":"RATE_LIMITED","detail":"Request rate limit exceeded"}}')
bronnen._op_tot[0] = None
bronnen.zoek("a")
bronnen.zoek("b")
klopt("een gewone 'te snel' blijft gewoon proberen", len(pogingen) == 2 and bronnen._op_tot[0] is None)

pogingen.clear()
bronnen._ZOEKERS[bronnen.ZOEK_AANBIEDER] = zoeker_met(402, "Payment required")
bronnen.zoek("c")
bronnen.zoek("d")
bronnen.zoek("e")
klopt("bij 402 maar een poging, daarna de dag stil", len(pogingen) == 1)
klopt("en het antwoord is dan een lege lijst, geen fout", bronnen.zoek("f") == [])

pogingen.clear()
bronnen._op_tot[0] = "2000-01-01"
bronnen.zoek("g")
klopt("de volgende dag probeert hij het weer", len(pogingen) == 1)

pogingen.clear()
bronnen._op_tot[0] = None
bronnen._ZOEKERS[bronnen.ZOEK_AANBIEDER] = zoeker_met(
    429, '{"error":{"code":"RATE_LIMITED","detail":"Request quota limit exceeded for plan"}}')
bronnen.zoek("h")
bronnen.zoek("i")
klopt("een 429 over het quotum stopt ook", len(pogingen) == 1)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: robots, artikelpagina's en het zoektegoed kloppen.")
