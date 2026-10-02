"""De llms.txt-generator voor Fix (2 oktober 2026, goedgekeurd door Nino).

WAAROM. Shopify-apps maken al met een klik een llms.txt; Krillo gaf alleen de
uitleg (toepasmodule.py). Een llms.txt is een kort bestand in gewone tekst dat
een AI-assistent in een keer vertelt wat de winkel is, wat hij verkoopt en waar
de belangrijkste pagina's staan.

WAT HIER EERLIJK BIJ HOORT (en op het scherm staat):
- Shopify en WordPress laten via hun koppeling geen los bestand in de hoofdmap
  zetten. Wij maken daarom een pagina (handle "llms-txt") met de inhoud, en de
  winkelier zet een keer een doorverwijzing van /llms.txt naar die pagina. Dat
  is een minuut werk en staat stap voor stap in de tekst bij het voorstel.
- llms.txt is een voorstel van een groep ontwikkelaars, geen standaard die
  ChatGPT of Gemini beloven te lezen. Het kost niets en kan geen kwaad; wij
  verkopen het niet als wondermiddel.

BIJHOUDEN. Elke keer dat de voorstellen gemaakt worden (bij Fix met Shopify
elke week vanzelf) maken wij de tekst opnieuw uit de producten en pagina's van
nu. Is hij anders dan wat er staat, dan komt er een voorstel om de pagina bij
te werken. Geen AI: alleen wat al in de winkel staat, dus niets verzonnen.
"""
import html as _html
import re

HANDLE = "llms-txt"
TITEL = "llms.txt"
MAX_PRODUCTEN = 40
MAX_PAGINAS = 12
# Pagina's die niets zeggen over wat de winkel verkoopt.
OVERSLAAN = re.compile(r"llms|privacy|cookie|terms|voorwaarden|disclaimer|algemene|cart|winkelwagen|"
                       r"account|login|checkout|afrekenen|404", re.I)


def _regel(tekst, lengte=160):
    tekst = re.sub(r"<[^>]+>", " ", str(tekst or ""))
    tekst = _html.unescape(tekst).replace("—", ",").replace("–", ",")
    tekst = " ".join(tekst.split())
    return tekst if len(tekst) <= lengte else tekst[:lengte].rsplit(" ", 1)[0] + "..."


def maak_tekst(naam, adres, omschrijving="", producten=None, paginas=None):
    """De inhoud van llms.txt in het afgesproken formaat (Markdown):
    # naam, > een zin, en dan lijsten met links.

    producten: [{"titel", "url", "soort", "tekst"}]; paginas: [{"titel", "url"}]."""
    adres = (adres or "").rstrip("/")
    naam = _regel(naam, 80) or adres.replace("https://", "").replace("http://", "")
    producten = [p for p in (producten or []) if p.get("titel") and p.get("url")][:MAX_PRODUCTEN]
    paginas = [p for p in (paginas or []) if p.get("titel") and p.get("url")
               and not OVERSLAAN.search((p.get("url") or "") + " " + (p.get("titel") or ""))][:MAX_PAGINAS]
    soorten = []
    for p in producten:
        s = _regel(p.get("soort"), 40)
        for deel in [x.strip() for x in s.split(",") if x.strip()]:
            if deel not in soorten:
                soorten.append(deel)
    zin = _regel(omschrijving, 240)
    if not zin:
        zin = (f"{naam} is an online store" + (f" selling {', '.join(soorten[:5])}" if soorten else "") + ".")
    delen = [f"# {naam}", "", f"> {zin}", "", f"Store: {adres}"]
    if soorten:
        delen += ["", "Product types: " + ", ".join(soorten[:10])]
    if paginas:
        delen += ["", "## Pages", ""] + [f"- [{_regel(p['titel'], 80)}]({p['url']})" for p in paginas]
    if producten:
        delen += ["", "## Products", ""]
        for p in producten:
            uitleg = _regel(p.get("tekst"), 120)
            delen.append(f"- [{_regel(p['titel'], 80)}]({p['url']})" + (f": {uitleg}" if uitleg else ""))
    return "\n".join(delen).strip() + "\n"


def als_html(tekst):
    """De tekst zoals hij op de pagina komt: letterlijk, in een <pre>."""
    return f"<pre>{_html.escape(tekst)}</pre>"


def uit_html(body):
    """Terug van de pagina naar de tekst, om te vergelijken."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", body or "", re.S | re.I)
    return _html.unescape(m.group(1)) if m else _regel(body, 100000)


STAPPEN = {
    "shopify": ("Last step, once: in Shopify go to Online Store, Navigation, URL Redirects, Create URL "
                "redirect. Redirect from /llms.txt to /pages/llms-txt. Save."),
    "wp": ("Last step, once: add a redirect from /llms.txt to /llms-txt/ with your redirect plugin (for "
           "example Redirection or Rank Math), or ask your host to place the file in the root of your site."),
}


def voorstel(platform, adres, naam, gebreken, link):
    """Een voorstel voor de llms.txt, of None als hij er al zo staat.

    gebreken["llms_producten"], ["llms_paginas"], ["llms_huidig"] (de tekst die
    nu op de pagina staat, of None als er geen pagina is)."""
    tekst = maak_tekst(naam, adres, gebreken.get("llms_omschrijving") or "",
                       gebreken.get("llms_producten"), gebreken.get("llms_paginas"))
    huidig = gebreken.get("llms_huidig")
    if huidig is not None and huidig.strip() == tekst.strip():
        return None
    bijwerken = huidig is not None
    return {
        "id": f"{platform}:llms",
        "soort": "llms",
        "titel": TITEL,
        "wat": "Update your llms.txt (new products or pages)" if bijwerken
        else "New llms.txt: a short file that tells AI what your store sells",
        "waar": STAPPEN.get(platform, STAPPEN["wp"]) if not bijwerken else "Page llms-txt",
        "link": link,
        "afbeelding": "",
        "oud": huidig or "",
        "nieuw": tekst,
        "nieuw_html": als_html(tekst),
    }


def naam_en_omschrijving(webshop_url):
    """De naam en een zin over de winkel uit wat Krillo al weet (index en
    winkelprofiel). Lege tekst als er niets is; dan valt maak_tekst terug op het
    domein en de productsoorten."""
    import db
    naam, omschrijving = "", ""
    try:
        naam = (db.winkel_kort(webshop_url) or {}).get("naam") or ""
    except Exception:
        pass
    try:
        profiel = db.get_winkelprofiel(webshop_url) or {}
        naam = naam or profiel.get("winkelnaam") or ""
        omschrijving = profiel.get("omschrijving") or ""
    except Exception:
        pass
    return naam, omschrijving
