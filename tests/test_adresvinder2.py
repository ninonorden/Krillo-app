"""De adresvinder leest de site grondiger, zonder te gokken.

WAAROM DEZE TEST BESTAAT

27 september: 263 winkels gemaild, maar 1299 winkels zonder mailadres, en nog
maar 4 in de rij. Het knelpunt was niet het aantal mails per dag maar de
adressen. De vinder miste adressen die er wel stonden:
- op de eigen contactlink van de winkel (/klantenservice/contact, /contact.html)
  in plaats van op de paden die wij raden;
- door Cloudflare verborgen (data-cfemail);
- uitgeschreven tegen spam ("info [at] winkel.nl");
- in de gestructureerde gegevens (JSON-LD), die wij met de scripts weggooiden;
- op dezelfde naam met een andere extensie (winkel.nl met info@winkel.com).
De regels blijven: alleen algemene adressen, geen namen, nooit gokken.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://krillo@/postgres?host=/tmp&port=5599")
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


import contactvinder as cv  # noqa: E402


def cf_codeer(adres, sleutel=0x5A):
    return format(sleutel, "02x") + "".join(format(ord(c) ^ sleutel, "02x") for c in adres)


D = "voorbeeldwinkel.nl"
print("\n== VERBORGEN EN UITGESCHREVEN ADRESSEN ==")
klopt("Cloudflare terugvertaald", cv._cloudflare(cf_codeer("info@voorbeeldwinkel.nl")) == "info@voorbeeldwinkel.nl")
html = f'<p>Mail: <a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{cf_codeer("info@voorbeeldwinkel.nl")}">[email protected]</a></p>'
klopt("data-cfemail op de pagina gevonden",
      [a["adres"] for a in cv._uit_pagina(html, "https://" + D, D)] == ["info@voorbeeldwinkel.nl"])
html = f'<a href="/cdn-cgi/l/email-protection#{cf_codeer("hallo@voorbeeldwinkel.nl")}">mail ons</a>'
klopt("Cloudflare-link gevonden",
      "hallo@voorbeeldwinkel.nl" in [a["adres"] for a in cv._uit_pagina(html, "https://" + D, D)])
for tekst in ("info [at] voorbeeldwinkel.nl", "info(at)voorbeeldwinkel(dot)nl",
              "info @ voorbeeldwinkel . nl", "info [at] voorbeeldwinkel [punt] nl"):
    klopt(f"uitgeschreven: {tekst}",
          "info@voorbeeldwinkel.nl" in [a["adres"] for a in cv._uit_pagina(f"<p>{tekst}</p>", "https://" + D, D)])
klopt("gewone zin met 'at' wordt geen adres",
      cv._uit_pagina("<p>We are at your service at voorbeeldwinkel</p>", "https://" + D, D) == [])
ld = '<script type="application/ld+json">{"@type":"Organization","email":"mailto:contact@voorbeeldwinkel.nl"}</script>'
klopt("adres uit gestructureerde gegevens",
      "contact@voorbeeldwinkel.nl" in [a["adres"] for a in cv._uit_pagina(ld, "https://" + D, D)])

print("\n== DEZELFDE NAAM, ANDERE EXTENSIE ==")
klopt("info@voorbeeldwinkel.com bij voorbeeldwinkel.nl is eigen domein",
      cv._bruikbaar("info@voorbeeldwinkel.com", D)["eigen_domein"])
klopt("een ander bedrijf niet", cv._bruikbaar("info@anderbedrijf.com", D) is None)
klopt("korte namen niet (ab.nl en ab.com kunnen twee bedrijven zijn)",
      cv._bruikbaar("info@ab.com", "ab.nl") is None)
klopt("een subdomein-truc niet", cv._bruikbaar("info@voorbeeldwinkel.evil.com", D) is None)

print("\n== DE REGELS BLIJVEN ==")
klopt("een naam blijft persoonlijk", not cv._bruikbaar("jan@voorbeeldwinkel.nl", D)["algemeen"])
klopt("klantcontact is algemeen", cv._bruikbaar("klantcontact@voorbeeldwinkel.nl", D)["algemeen"])
klopt("icloud van een eenmanszaak mag", cv._bruikbaar("info.voorbeeldwinkel@icloud.com", D) is not None)

print("\n== DE EIGEN LINKS VAN DE WINKEL EERST ==")
home = ('<a href="/klantenservice/contact-opnemen">Neem contact op</a>'
        '<a href="/producten">Producten</a><a href="https://elders.nl/contact">x</a>'
        '<a href="/p/privacyverklaring">Privacy</a>')
links = cv._contactlinks(home, "https://" + D, D)
klopt("contactlink gevonden, eigen domein, contact vooraan",
      links[:2] == ["https://voorbeeldwinkel.nl/klantenservice/contact-opnemen",
                    "https://voorbeeldwinkel.nl/p/privacyverklaring"])
klopt("links naar een ander domein niet", all("elders" not in l for l in links))

bezocht = []


class _A:
    def __init__(self, tekst, code=200):
        self.text, self.status_code = tekst, code


def nep_get(url, **k):
    bezocht.append(url)
    if url.rstrip("/") == "https://voorbeeldwinkel.nl":
        return _A(home)
    if url.endswith("/klantenservice/contact-opnemen"):
        return _A("<p>Mail ons: service [at] voorbeeldwinkel.nl</p>")
    return _A("niets", 404)


cv.requests.get = nep_get
uit = cv.zoek_adres("https://voorbeeldwinkel.nl")
klopt("het adres op de eigen contactpagina gevonden", uit["adres"] == "service@voorbeeldwinkel.nl")
klopt("met maar twee paginabezoeken", len(bezocht) == 2)

print("\n== IEDEREEN ZONDER ADRES KRIJGT NOG EEN KANS ==")
bron = lees("benadering.py")
klopt("nieuwe herkansingslijst", 'HERKANSING_SLEUTEL = "benadering_adres_herkansing_v2"' in bron)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de vinder leest de site grondiger, met dezelfde regels.")
