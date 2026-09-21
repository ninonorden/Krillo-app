"""Een klantscherm: het werk staat in het dashboard.

WAAROM DEZE TEST BESTAAT

Tot 21 september had een klant twee schermen. Het dashboard (/mijn/<token>)
met zijn positie, en een oud werkscherm (/monitoring/<token>) met de stand van
de uitvoering, de wijzigingen met de oude tekst, de teksten om te plakken en
opzeggen. Dat oude scherm stond in een andere stijl, had hardgecodeerde
Nederlandse knopteksten, noemde "monitoring" als product, en vertelde elke
abonnee dat hij "39 euro per maand" betaalde: het tarief van voor 17 september.
En alle mails wezen ernaar.

Daarnaast kreeg een betalende klant van wie de categorie nog niet gemeten was
op /mijn een foutpagina. Zijn enige werkende scherm was het oude.

Deze test bewaakt dat het nu een scherm is, dat het oude adres doorstuurt, en
dat geen enkele mail nog naar het oude scherm wijst.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES, lees  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402
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


db.init_db()
import app  # noqa: E402

app.app.config["TESTING"] = True
k = app.app.test_client()

print("\n== HET OUDE SCHERM BESTAAT NIET MEER ==")
klopt("monitoring.html is weg", not os.path.exists(os.path.join(TEMPLATES, "monitoring.html")))
klopt("het werkblok bestaat", os.path.exists(os.path.join(TEMPLATES, "_werk.html")))
dash = lees("templates/dashboard.html")
klopt("het dashboard voegt het werkblok in", '{% include "_werk.html" %}' in dash)
klopt("en stuurt niet meer naar een apart takenscherm", "Go to my tasks" not in dash)

print("\n== EEN KLANT ZONDER GEMETEN CATEGORIE KRIJGT GEEN FOUTPAGINA ==")
tok = db.get_or_create_klant("https://werkblok-zonder-meting.nl", "w@example.com")
a = k.get(f"/mijn/{tok}")
h = a.get_data(as_text=True)
zo("het dashboard laadt", a.status_code, 200)
klopt("met een eerlijke melding dat er nog niet gemeten is", "not been measured yet" in h)
klopt("en met zijn werk eronder", 'id="werk"' in h)

print("\n== HET OUDE ADRES STUURT DOOR ==")
a = k.get(f"/monitoring/{tok}")
zo("een 301", a.status_code, 301)
zo("naar het werkblok in het dashboard", a.headers.get("Location"), f"/mijn/{tok}#werk")
klopt("de detailpagina bestaat nog", k.get(f"/monitoring/{tok}/details").status_code == 200)
det = lees("templates/monitoring_details.html")
klopt("en wijst terug naar het dashboard", "/mijn/{{ klant_token }}#werk" in det)

print("\n== GEEN MAIL WIJST NOG NAAR HET OUDE SCHERM ==")
for bestand in ("app.py", "meldingen.py", "emailing.py"):
    bron = lees(bestand)
    # Alleen de route zelf en commentaar mogen het nog noemen.
    regels = [r for r in bron.splitlines()
              if "/monitoring/{" in r and not r.strip().startswith("#")
              and "@app.route" not in r]
    zo(f"{bestand} maakt geen links meer naar /monitoring/<token>", regels, [])

print("\n== HET WERKBLOK SPREEKT DE TAAL VAN HET DASHBOARD ==")
werk = lees("templates/_werk.html")
script = "".join(re.findall(r"<script>(.*?)</script>", werk, flags=re.S))
# Alle zichtbare tekst in het script komt uit wt. Hardgecodeerd Nederlands
# (zoals vroeger "Gekopieerd", "Opgezegd", "Weet je zeker") mag er niet in.
for woord in ("Gekopieerd", "Kopieer'", "Opgezegd", "Weet je zeker", "hallo@krillo.nl"):
    klopt(f"geen hardgecodeerd '{woord}' in het script", woord not in script)
gebruikt = set(re.findall(r"\bwt\.([a-zA-Z_][a-zA-Z0-9_]*)", werk))
for taal in ("nl", "en"):
    zo(f"elke tekst bestaat in {taal}", sorted(gebruikt - set(paginataal.TEKSTEN[taal])), [])

print("\n== GEEN OUD TARIEF EN GEEN OUDE PRODUCTNAAM MEER IN DE KLANTTEKSTEN ==")
fout = [f"{taal}:{s}" for taal, d in paginataal.TEKSTEN.items() for s, v in d.items()
        if isinstance(v, str) and ("39 euro" in v or "monitoring" in v.lower())]
zo("nergens '39 euro' of 'monitoring'", fout, [])

print("\n== DE BEHEERWEERGAVE LAAT HET ECHTE DASHBOARD ZIEN ==")
a = k.get("/admin/voorbeeld?key=testsleutel&url=https://werkblok-zonder-meting.nl",
          follow_redirects=True)
h = a.get_data(as_text=True)
zo("hij laadt", a.status_code, 200)
klopt("het is het dashboard, met het werkblok", 'class="werk"' in h)
klopt("en met het beheerblok", "Beheerweergave" in h)
klopt("en zonder opzegknop", 'id="opzegKnop"' not in h)

print("\n== HET OPENBARE VOORBEELD KRIJGT GEEN ECHT WERKBLOK ==")
# /demo is een echte winkel zonder klant. Daar hoort de uitleg, geen werk dat
# niet bestaat (besluit D8).
klopt("het werkblok hangt aan 'werkblok' en niet aan het voorbeeld",
      "{% if werkblok %}" in dash)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed: een klant heeft een scherm, en het oude adres stuurt door.")
