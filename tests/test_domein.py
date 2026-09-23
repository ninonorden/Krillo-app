"""De verhuizing naar krilloai.com.

WAAROM DEZE TEST BESTAAT

Op 18 september is Krillo verhuisd van krillo.nl naar krilloai.com. Bij het
voorbereiden daarvan bleek dat het oude adres op zeven plekken hardgecodeerd
stond, en elk daarvan faalt STIL:

- De canonical van elke pagina stond vast op www.krillo.nl. Een canonical die
  naar het oude domein wijst vertelt Google dat de echte pagina daar staat, en
  dan doet de hele verhuizing niets. Je ziet er niets van, de site werkt
  gewoon, en drie maanden later vraag je je af waarom het nieuwe domein niet
  in de zoekresultaten staat.
- De sitemap noemde adressen op www.krillo.nl. Search Console keurt een
  sitemap af die over een ander eigendom gaat dan waar hij ingediend wordt.
- robots.txt wees naar de sitemap van het oude domein.
- llms.txt, og:url en de gestructureerde gegevens idem.

Deze test controleert dat alles uit BASE_URL komt, dat het oude domein netjes
doorstuurt met een 301, en dat /.well-known daar BUITEN valt. Dat laatste is
geen detail: daar komen de controles binnen waarmee het certificaat van
krillo.nl vernieuwd wordt. Sturen wij die door, dan verloopt dat certificaat op
een dag en werkt juist de doorverwijzing niet meer.
"""
import os
import re
import sys

BASIS = "https://krilloai.com"
os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = BASIS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


import app  # noqa: E402

app.app.config["TESTING"] = True
k = app.app.test_client()

print("\n== HET OUDE DOMEIN STUURT DOOR ==")
for host in ("krillo.nl", "www.krillo.nl"):
    a = k.get("/", headers={"Host": host})
    zo(f"{host} geeft een 301 en geen 302", a.status_code, 301)
    zo(f"{host} komt uit op het nieuwe domein",
       a.headers.get("Location", "").rstrip("/"), BASIS)

# Een oude link naar een ranglijst hoort op DIE ranglijst uit te komen. Een
# doorverwijzing naar de voorpagina telt voor een zoekmachine als een pagina
# die verdwenen is, en dan ben je de positie kwijt die je juist wilde houden.
a = k.get("/index/nl/speelgoed", headers={"Host": "www.krillo.nl"})
zo("het pad blijft staan bij het doorsturen",
   a.headers.get("Location"), f"{BASIS}/index/nl/speelgoed")

a = k.get("/index?land=be", headers={"Host": "www.krillo.nl"})
zo("de zoekopdracht blijft ook staan",
   a.headers.get("Location"), f"{BASIS}/index?land=be")

print("\n== /.well-known GAAT ER BUITEN ==")
a = k.get("/.well-known/acme-challenge/proef", headers={"Host": "www.krillo.nl"})
klopt("de certificaatcontrole wordt NIET doorgestuurd", a.status_code != 301)

print("\n== robots.txt OP HET OUDE DOMEIN ANTWOORDT DIRECT ==")
# Google eist dat robots.txt op het oude domein direct 200 of 404 geeft. Kreeg
# hij een doorverwijzing, dan faalde de adreswijziging in Search Console met
# "kan de pagina niet ophalen" voor elke pagina. Gebeurd op 21 september.
for host in ("krillo.nl", "www.krillo.nl"):
    a = k.get("/robots.txt", headers={"Host": host})
    zo(f"robots.txt op {host} geeft 200 en geen doorverwijzing", a.status_code, 200)
    t = a.get_data(as_text=True)
    klopt(f"robots.txt op {host} laat Google overal bij", "Allow: /" in t)
    klopt(f"robots.txt op {host} wijst naar de sitemap op het nieuwe domein",
          f"Sitemap: {BASIS}/sitemap.xml" in t)
# En de rest van het oude domein stuurt nog steeds gewoon door.
zo("de homepage van het oude domein stuurt nog door",
   k.get("/", headers={"Host": "www.krillo.nl"}).status_code, 301)

print("\n== DE NOODREM: BASE_URL NOG OP HET OUDE DOMEIN ==")
# Wordt de code geupload voordat BASE_URL in Render omgezet is, dan zou
# krillo.nl naar krillo.nl sturen. Dat is een lus en de site is weg. De code
# hoort dat zelf te merken in plaats van te vertrouwen op de juiste volgorde.
_echte_basis = app.os.environ.get("BASE_URL")
try:
    app.os.environ["BASE_URL"] = "https://www.krillo.nl"
    a = k.get("/", headers={"Host": "www.krillo.nl"})
    zo("bij een oude BASE_URL wordt er NIET doorgestuurd", a.status_code, 200)
    a = k.get("/", headers={"Host": "krillo.nl"})
    zo("ook niet vanaf het kale oude domein", a.status_code, 200)
finally:
    if _echte_basis:
        app.os.environ["BASE_URL"] = _echte_basis

print("\n== HET NIEUWE DOMEIN STUURT NERGENS HEEN ==")
a = k.get("/", headers={"Host": "krilloai.com"})
zo("krilloai.com serveert gewoon de pagina", a.status_code, 200)

print("\n== ALLES KOMT UIT BASE_URL ==")
robots = k.get("/robots.txt").get_data(as_text=True)
klopt("robots.txt wijst naar de sitemap op het nieuwe domein",
      f"Sitemap: {BASIS}/sitemap.xml" in robots)
klopt("robots.txt noemt het oude domein niet meer",
      "krillo.nl" not in robots)

kaart = k.get("/sitemap.xml").get_data(as_text=True)
klopt("de sitemap gebruikt het nieuwe domein", f"<loc>{BASIS}/" in kaart)
klopt("de sitemap noemt het oude domein niet meer", "krillo.nl" not in kaart)

llms = k.get("/llms.txt").get_data(as_text=True)
klopt("llms.txt gebruikt het nieuwe domein", f"{BASIS}/" in llms)
klopt("llms.txt noemt geen adres op het oude domein",
      "https://www.krillo.nl" not in llms)

print("\n== GEEN ENKELE PAGINA WIJST NOG NAAR HET OUDE DOMEIN ==")
# Dit is de belangrijkste controle van dit bestand. Een canonical naar het oude
# domein maakt de hele verhuizing ongedaan, en je ziet het aan niets.
paginas = ["/", "/zo-meten-we", "/veelgestelde-vragen", "/over-ons",
           "/artikelen", "/voorwaarden", "/privacybeleid", "/herroepen",
           "/onderzoek", "/demo", "/index"]
for pad in paginas:
    a = k.get(pad, headers={"Host": "krilloai.com"})
    if a.status_code != 200:
        print(f"  (overgeslagen, {pad} gaf {a.status_code})")
        continue
    tekst = a.get_data(as_text=True)
    adressen = re.findall(r'https?://(?:www\.)?krillo\.nl[^\s"\'<>]*', tekst)
    zo(f"{pad} noemt geen adres op krillo.nl", adressen, [])
    # De canonical moet er zijn EN op het nieuwe domein staan.
    m = re.search(r'<link rel="canonical" href="([^"]+)"', tekst)
    if m:
        klopt(f"{pad} heeft een canonical op het nieuwe domein",
              m.group(1).startswith(BASIS))

print("\n== HET MAILADRES STAAT OP HET NIEUWE DOMEIN ==")
a = k.get("/over-ons", headers={"Host": "krilloai.com"}).get_data(as_text=True)
# Sinds 21 september is hello@krilloai.com het enige adres (besluit Nino).
# hallo@krillo.nl ontvangt niets meer, dus het mag nergens meer staan.
klopt("over-ons noemt het nieuwe mailadres", "hello@krilloai.com" in a and "hallo@krillo.nl" not in a)

print("\n== DE PRIJZEN IN llms.txt KOMEN UIT DE CODE ==")
import payments  # noqa: E402

for sleutel in ("watch", "fix", "merken"):
    bedrag = int(float(payments.PAKKETTEN[sleutel]["prijs"]["value"]))
    klopt(f"llms.txt noemt {bedrag} euro voor {sleutel}",
          f"{bedrag} euro per month" in llms)

print("\n== GEEN VERVALLEN PRODUCTEN MEER IN llms.txt ==")
# De audit van 79 euro en het monitoring-abonnement bestaan sinds 11 september
# niet meer. Ze stonden hier nog wel in, inclusief de onwaarheid "meet elke
# week opnieuw" die op 18 september al uit de veelgestelde vragen was gehaald.
klopt("geen audit van 79 euro meer", "79 euro" not in llms)
klopt("geen monitoring-abonnement meer", "monitoring-abonnement" not in llms)
klopt("niet meer 'elke week' meten", "elke week" not in llms and "every week" not in llms)
# Sinds 23 september Engels, zoals de site (taalregel: een adres, een taal).
klopt("llms.txt is Engels", "What Krillo does" in llms and "Wat Krillo doet" not in llms)
klopt("en zegt dat een platform geen positie inneemt",
      "does not take a position" in " ".join(llms.split()))
klopt("de index staat er wel in, want dat is het kernproduct",
      "/index" in llms)

print("\n== SEARCH CONSOLE KAN BEIDE EIGENDOMMEN VERIFIEREN ==")
# De oude code is voor www.krillo.nl, de nieuwe voor krilloai.com. Zolang de
# adreswijziging loopt moeten ze er allebei staan; zie de uitleg in index.html.
_thuis = k.get("/", headers={"Host": "krilloai.com"}).get_data(as_text=True)
klopt("de verificatie voor krillo.nl staat er nog",
      "-rhhZoHmZMYdIbtYgGXCj-Zg4FY0j0lSAQdJOPTtEwQ" in _thuis)
klopt("de verificatie voor krilloai.com staat erbij",
      "f9WynjVD3AdJuRowJY7s4cFcZEFKDNJybRKC9zz3XDQ" in _thuis)

print("\n== DE BEGINWAARDE VAN HET BESTELSCHERM ==")
thuis = lees("templates/index.html")
klopt("het bestelscherm begint niet op een vervallen product",
      "var currentType = 'uitvoering'" not in thuis)
klopt("het begint op hetzelfde pakket als de server",
      f"var currentType = '{payments.STANDAARD_PAKKET}'" in thuis)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed: de verhuizing is compleet en niets wijst nog naar krillo.nl.")
