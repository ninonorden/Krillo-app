"""Kant-en-klare oplossingen: AI-robots en gestructureerde gegevens (15 oktober 2026).

Goedgekeurde voorstellen 6, 7 en 10 (roadmap 248, plus de crawl- en schemacheck).

WAAROM. De paginacheck (paginacheck.py) zag al per pagina per AI-robot of hij
binnen mag, en of er productgegevens (schema.org) staan. Maar hij zei alleen
WAT er mis is. Een winkelier zonder ontwikkelaar loopt vast op het HOE. Voor
een Shopify-winkel is een geblokkeerde zoekrobot of een ontbrekend Product-blok
de vaakst voorkomende en minst bekende reden dat AI hem niet noemt. Hier per
probleem de oplossing, klaar om te plakken:
- robots.txt: welke zoekrobots van AI geweerd worden en precies welke regels
  erbij moeten (en waar dat in Shopify en WordPress staat);
- per productpagina: ontbreekt Product, prijs en voorraad (Offer), beoordelingen
  (AggregateRating) of veelgestelde vragen (FAQPage)? Een zin uitleg per ding,
  en een blok JSON-LD gevuld met wat er al op de pagina staat;
- de homepage: bedrijfsgegevens (Organization).

EERLIJK. We vullen alleen in wat op de pagina zelf staat (titel, omschrijving,
afbeelding, prijs uit de meta-tags). Wat we niet weten, staat er als
"FILL_IN" in, nooit verzonnen. Beoordelingen zetten we nooit zelf in een blok:
alleen echte reviews mogen erin, en die komen uit een review-app.
Geen AI-aanroep: kost niets.
"""
import json
import re
from urllib.parse import urlparse

# De robots die tellen voor GEVONDEN worden in AI-antwoorden (geen training).
ZOEKROBOTS = [
    ("OAI-SearchBot", "ChatGPT search"),
    ("ChatGPT-User", "ChatGPT when a user asks it to open a page"),
    ("PerplexityBot", "Perplexity"),
    ("Claude-SearchBot", "Claude search"),
    ("Googlebot", "Google, AI Overviews and Gemini"),
    ("Bingbot", "Bing and Copilot"),
]


def _types(html):
    """Alle @type's in de JSON-LD van de pagina, ook genest, plus de blokken zelf."""
    gevonden, blokken = set(), []

    def loop(n):
        if isinstance(n, dict):
            t = n.get("@type")
            for x in (t if isinstance(t, list) else [t]):
                if x:
                    gevonden.add(x)
            if t:
                blokken.append(n)
            for v in n.values():
                loop(v)
        elif isinstance(n, list):
            for v in n:
                loop(v)
    for ruw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or "", re.S | re.I):
        try:
            loop(json.loads(ruw.strip()))
        except ValueError:
            continue
    return gevonden, blokken


def _meta(html, *namen):
    for naam in namen:
        m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(naam) + r'["\'][^>]+content=["\']([^"\']*)["\']',
                      html or "", re.I) or re.search(
            r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']' + re.escape(naam) + r'["\']',
            html or "", re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _h1(html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S | re.I)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None


def product_blok(html, url):
    """Een Product-blok gevuld met wat op de pagina staat; onbekend = FILL_IN."""
    naam = _meta(html, "og:title") or _h1(html) or "FILL_IN product name"
    blok = {"@context": "https://schema.org", "@type": "Product", "name": naam,
            "description": _meta(html, "og:description", "description") or "FILL_IN short description",
            "url": url}
    beeld = _meta(html, "og:image")
    if beeld:
        blok["image"] = beeld
    merk = _meta(html, "product:brand", "og:brand")
    if merk:
        blok["brand"] = {"@type": "Brand", "name": merk}
    blok["offers"] = {"@type": "Offer",
                      "price": _meta(html, "product:price:amount", "og:price:amount") or "FILL_IN",
                      "priceCurrency": _meta(html, "product:price:currency", "og:price:currency") or "EUR",
                      "availability": "https://schema.org/InStock", "url": url}
    return blok


def schema_check(html, url, is_product, is_home=False):
    """Lijst van {"wat", "uitleg", "fix"} (fix = JSON-LD of None). Leeg = goed."""
    if html is None:
        return []
    types, blokken = _types(html)
    uit = []
    if is_product:
        if "Product" not in types and "ProductGroup" not in types:
            uit.append({"wat": "Product data",
                        "uitleg": "AI cannot read the product name, price and stock as facts on this page. "
                                  "Add a Product block so it does not have to guess.",
                        "fix": json.dumps(product_blok(html, url), ensure_ascii=False, indent=2)})
        else:
            if "Offer" not in types and "AggregateOffer" not in types:
                uit.append({"wat": "Price and stock",
                            "uitleg": "The Product block has no price or availability (Offer). AI answers about "
                                      "price and stock skip pages without it.",
                            "fix": json.dumps({"@type": "Offer", "price": _meta(html, "product:price:amount") or "FILL_IN",
                                               "priceCurrency": _meta(html, "product:price:currency") or "EUR",
                                               "availability": "https://schema.org/InStock"}, indent=2)})
            if "AggregateRating" not in types and "Review" not in types:
                uit.append({"wat": "Reviews",
                            "uitleg": "There are no reviews in the product data. AI likes to name stores with "
                                      "visible ratings. Most review apps (Judge.me, Loox, Kiyoh) can add them "
                                      "for you; switch on their \"rich snippets\" setting. Never add ratings by hand.",
                            "fix": None})
    if "FAQPage" not in types and (is_product or is_home):
        uit.append({"wat": "Questions and answers",
                    "uitleg": "No FAQ block. Questions in the words of a buyer, with a short answer, are what AI "
                              "quotes most. Add three to five real questions.",
                    "fix": json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
                        {"@type": "Question", "name": "FILL_IN a buyer question",
                         "acceptedAnswer": {"@type": "Answer", "text": "FILL_IN short answer"}}]}, indent=2)})
    if is_home and "Organization" not in types and "OnlineStore" not in types and "LocalBusiness" not in types:
        host = urlparse(url).netloc
        uit.append({"wat": "Store details",
                    "uitleg": "No Organization block on the homepage. It tells AI who you are, where you sell "
                              "and how to reach you.",
                    "fix": json.dumps({"@context": "https://schema.org", "@type": "Organization",
                                       "name": _meta(html, "og:site_name") or host, "url": f"https://{host}",
                                       "logo": "FILL_IN link to your logo",
                                       "contactPoint": {"@type": "ContactPoint", "email": "FILL_IN"}}, indent=2)})
    return uit


def robots_fix(robots_tekst):
    """Welke AI-zoekrobots robots.txt weert, en de regels die erbij moeten.
    {"geweerd": [(bot, wie)], "regels": str} of None als alles open is."""
    import urllib.robotparser
    parser = urllib.robotparser.RobotFileParser()
    parser.parse((robots_tekst or "").splitlines())
    geweerd = [(b, w) for b, w in ZOEKROBOTS if not parser.can_fetch(b, "/") or not parser.can_fetch(b, "/products/x")]
    if not geweerd:
        return None
    regels = "\n\n".join(f"User-agent: {b}\nAllow: /" for b, _ in geweerd)
    return {"geweerd": geweerd, "regels": regels,
            "waar": "Put these lines at the TOP of robots.txt. Shopify: Online Store > Themes > Edit code > "
                    "add the template robots.txt.liquid. WordPress: Yoast or Rank Math > Tools > File editor."}


def site_fixes(webshop_url, robots_tekst, home_html=None):
    """Alles op siteniveau: robots en (als hij ontbreekt) een llms.txt."""
    import llmstxt
    uit = {"robots": robots_fix(robots_tekst)}
    try:
        naam, omschrijving = (llmstxt.naam_en_omschrijving(webshop_url) if home_html is None
                              else (_meta(home_html, "og:site_name") or urlparse(webshop_url).netloc,
                                    _meta(home_html, "og:description", "description") or ""))
        uit["llms_txt"] = llmstxt.maak_tekst(naam, webshop_url, omschrijving)
    except Exception as e:
        print(f"llms.txt maken mislukt voor {webshop_url}: {e}")
        uit["llms_txt"] = None
    return uit
