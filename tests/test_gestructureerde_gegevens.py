"""De JSON-LD blokken op de site moeten geldig zijn.

Waarom deze test bestaat. Op 16 september kwam er een mail van Google Search
Console: "Parseerfout: ',' of '}' ontbreekt". Een kritiek probleem, en kritiek
betekent bij Google dat de pagina helemaal niet meer in de zoekresultaten komt
met die gegevens.

De oorzaak was een vraag in faq.html die zo geschreven stond:

    "name": "Wat houdt "wij doen het" in?"

Die aanhalingstekens midden in de tekst sluiten de waarde af. Voor een mens
leest het prima, voor een parser is het stuk. In index.html stond dezelfde
vraag wel goed, met \\" eromheen. Precies het soort fout dat je met het oog
overslaat en dat een machine meteen ziet.

Dubbel zuur voor dit bedrijf in het bijzonder: wij verkopen aan webshops dat
hun gegevens machine-leesbaar moeten zijn. Dan moeten die van ons het zeker
zijn.

Wat hier gecontroleerd wordt:

- Elk blok <script type="application/ld+json"> in elke template is geldige
  JSON, ook de blokken met Jinja erin.
- Elke Jinja-waarde binnen zo'n blok gaat door de filter tojson. Zonder die
  filter breekt een artikeltitel met een aanhalingsteken erin precies dezelfde
  fout opnieuw.
- Elk blok heeft een @context en een @type, want zonder die twee doet Google
  er niets mee.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import TEMPLATES  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


# Velden die wij zelf aanmaken en die geen aanhalingsteken of backslash kunnen
# bevatten. Alles wat een mens intypt hoort hier NIET bij en moet door tojson.
VEILIG_IN_TEKST = {"artikel.slug", "artikel.datum"}

BLOK = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
JINJA_WAARDE = re.compile(r"\{\{(.*?)\}\}", re.S)
JINJA_BLOK = re.compile(r"\{%.*?%\}", re.S)


def zonder_jinja(tekst):
    """Vervang de Jinja-stukken door iets dat JSON wel aankan.

    Een waarde die door tojson gaat levert zelf de aanhalingstekens, dus die
    wordt "x". Een waarde zonder tojson staat altijd binnen aanhalingstekens
    in de template, dus die wordt kale tekst.
    """
    tekst = JINJA_BLOK.sub("", tekst)

    def vervang(m):
        return '"x"' if "tojson" in m.group(1) else "x"

    return JINJA_WAARDE.sub(vervang, tekst)


print("== elk JSON-LD blok in elke template ==")
gevonden = 0
for naam in sorted(os.listdir(TEMPLATES)):
    if not naam.endswith(".html"):
        continue
    inhoud = open(os.path.join(TEMPLATES, naam), encoding="utf-8").read()
    for nummer, m in enumerate(BLOK.finditer(inhoud), start=1):
        gevonden += 1
        blok = m.group(1)
        regel = inhoud[:m.start()].count("\n") + 1
        waar = f"{naam} regel {regel}"

        # Elke Jinja-waarde moet door tojson. Anders sloopt een titel met een
        # aanhalingsteken erin het hele blok. Uitzondering: een handvol velden
        # die wij zelf maken en die per definitie geen aanhalingstekens kunnen
        # bevatten, zoals een slug of een datum. Die staan middenin een tekst
        # ("https://.../artikelen/{{ artikel.slug }}") en kunnen daar niet door
        # tojson, want dan komen er aanhalingstekens in de URL te staan.
        for stuk in JINJA_WAARDE.findall(blok):
            naam_veld = stuk.strip()
            klopt(f"{waar}: {{{{{naam_veld}}}}} is veilig",
                  "tojson" in stuk or naam_veld in VEILIG_IN_TEKST)

        try:
            data = json.loads(zonder_jinja(blok))
            print(f"  ok  {waar}: geldige JSON")
        except Exception as e:
            print(f"  FOUT {waar}: geen geldige JSON: {e}")
            fouten.append(f"{waar}: geen geldige JSON")
            continue

        klopt(f"{waar}: heeft @context", data.get("@context"))
        klopt(f"{waar}: heeft @type", data.get("@type"))

klopt("er zijn blokken gevonden", gevonden >= 5)
print(f"\n{gevonden} blokken gecontroleerd.")

print("\n== de fout van 16 september komt niet terug ==")
faq = open(os.path.join(TEMPLATES, "faq.html"), encoding="utf-8").read()
blokken = BLOK.findall(faq)
klopt("faq.html heeft een JSON-LD blok", blokken)
if blokken:
    klopt('de vraag over "wij doen het" staat met ontsnapte aanhalingstekens',
          '\\"wij doen het\\"' in blokken[0])

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
