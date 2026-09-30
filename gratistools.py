"""Gratis losse tools: kleine checks zonder account (stap 162, 28 september).

WAAROM DIT BESTAAT. Otterly groeide mede op een rij gratis GEO-tools, HubSpot
geeft een AI-check weg. Een tool trekt bezoekers zonder dat er een mail de deur
uit hoeft: wie "can ChatGPT read my store" zoekt, vindt de pagina, doet de check
en ziet daarna zijn eigen plek in de Krillo Index. Elke tool heeft een eigen
pagina met uitleg, zodat Google en AI-assistenten hem kunnen vinden.

WAT DE TOOLS DOEN
1. crawler_check: mag AI de winkel lezen? robots.txt per AI-robot, plus een
   noai/noindex-kop op de homepage, plus een beveiligingsscherm dat robots
   tegenhoudt.
2. productdata_check: heeft een productpagina de gegevens die AI overneemt?
   Product-gegevens in de code (naam, prijs, voorraad, merk, reviews, code).
3. index_check: staat de winkel in de Krillo Index, en op welke plek?

REGELS
- Geen AI-geld: alleen pagina's van de winkel zelf lezen, met dezelfde
  ophaler als de scan (die weigert interne adressen en gevaarlijke
  omleidingen).
- Nooit iets beloven: de check zegt wat hij zag, en wat hij niet kon zien.
- Een eenvoudige rem per bezoeker, zodat niemand ons als gratis robot gebruikt.
"""
import json
import os
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import db
import scan_engine

# De AI-robots die ertoe doen voor een winkel, met wie ze zijn en waarvoor.
ROBOTS = [
    ("OAI-SearchBot", "ChatGPT search", "Finds your pages for ChatGPT's search answers and shopping results."),
    ("ChatGPT-User", "ChatGPT, when a user asks", "Opens a page when someone in ChatGPT asks about it."),
    ("GPTBot", "OpenAI training", "Collects pages to train OpenAI models. Blocking it does not remove you from ChatGPT search."),
    ("Google-Extended", "Gemini", "Lets Google use your pages for Gemini. Normal Google search is not affected."),
    ("PerplexityBot", "Perplexity", "Finds your pages for Perplexity's answers."),
    ("ClaudeBot", "Claude", "Collects pages for Anthropic's Claude."),
    ("Applebot-Extended", "Apple Intelligence", "Lets Apple use your pages for its AI features."),
]
# Welke robots het zwaarst tellen voor gevonden worden (niet voor trainen).
BELANGRIJK = {"OAI-SearchBot", "ChatGPT-User", "Google-Extended", "PerplexityBot"}

TOOLS = {
    "ai-crawler-check": {
        "titel": "Can AI read your store?",
        "kort": "Checks whether ChatGPT, Gemini, Perplexity and Claude are allowed to read your webshop.",
        "invoer": "Your store address",
        "voorbeeld": "yourstore.com",
    },
    "product-data-check": {
        "titel": "Does your product page give AI the facts?",
        "kort": "Checks whether a product page carries the details AI assistants copy: price, stock, brand, reviews.",
        "invoer": "The address of one product page",
        "voorbeeld": "yourstore.com/products/your-product",
    },
    "supplier-text-check": {
        "titel": "Is your product text on other stores too?",
        "kort": "Checks whether your product texts appear word for word on other webshops. Copied supplier "
                "texts are a common reason AI names someone else.",
        "invoer": "Your store address or one product page",
        "voorbeeld": "yourstore.com",
    },
    "index-check": {
        "titel": "Is your store in the Krillo Index?",
        "kort": "Looks up your store's rank in the monthly Krillo Index.",
        "invoer": "Your store address",
        "voorbeeld": "yourstore.com",
    },
}

# Rem per bezoeker: hoogstens zoveel checks per tien minuten.
REM_PER_TIEN_MINUTEN = 12
_rem = {}


def mag_nu(bezoeker, nu=None):
    nu = nu or time.time()
    lijst = [t for t in _rem.get(bezoeker, []) if nu - t < 600]
    if len(lijst) >= REM_PER_TIEN_MINUTEN:
        _rem[bezoeker] = lijst
        return False
    lijst.append(nu)
    _rem[bezoeker] = lijst
    return True


def _schoon(url):
    url = scan_engine.normalize_url((url or "").strip())
    if not urlparse(url).netloc or "." not in urlparse(url).netloc:
        return None, "That does not look like a web address. Try yourstore.com."
    if scan_engine.is_intern_adres(url):
        return None, "That is not a public webshop address."
    return url, None


def _haal(url, ophalen=None):
    if ophalen is not None:
        return ophalen(url)
    try:
        return scan_engine.fetch(url, pogingen=1)
    except Exception:
        return None


# ------------------------------------------------------------------ 1. robots

def crawler_check(url, ophalen=None):
    url, fout = _schoon(url)
    if fout:
        return {"fout": fout}
    basis = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    robots = _haal(urljoin(basis, "/robots.txt"), ophalen)
    home = _haal(basis + "/", ophalen)
    uitkomst = {"winkel": urlparse(url).netloc, "robots": [], "opmerkingen": []}

    if robots is not None and robots.status_code in (401, 403, 429) or (
            robots is not None and 500 <= robots.status_code < 600):
        # Een robots.txt die een fout geeft, lezen robots als "alles verboden".
        for bot, wie, wat in ROBOTS:
            uitkomst["robots"].append({"bot": bot, "wie": wie, "wat": wat, "mag": False})
        uitkomst["opmerkingen"].append(
            f"Your robots.txt returned an error ({robots.status_code}). Most AI robots then treat the "
            f"whole site as off limits. Ask your host or security tool why the file is not reachable.")
    else:
        parser = urllib.robotparser.RobotFileParser()
        tekst = robots.text if (robots is not None and robots.status_code == 200) else ""
        parser.parse(tekst.splitlines())
        for bot, wie, wat in ROBOTS:
            mag = parser.can_fetch(bot, basis + "/") and parser.can_fetch(bot, basis + "/products/x")
            uitkomst["robots"].append({"bot": bot, "wie": wie, "wat": wat, "mag": bool(mag)})
        if not tekst:
            uitkomst["opmerkingen"].append("No robots.txt found. That is fine: robots may then read everything.")

    if home is None:
        uitkomst["opmerkingen"].append("We could not open your homepage, so we only checked robots.txt.")
    else:
        html = home.text or ""
        kop = (home.headers.get("X-Robots-Tag") or "").lower() if hasattr(home, "headers") else ""
        laag = html[:20000].lower()
        if scan_engine.lijkt_op_blokkadepagina(html):
            uitkomst["opmerkingen"].append(
                "Your homepage showed us a security check instead of the page. AI robots usually get the "
                "same wall, and then cannot read your store at all. Check your firewall or bot protection "
                "(for example Cloudflare's bot settings).")
        if "noai" in kop or 'content="noai' in laag or "noimageai" in laag:
            uitkomst["opmerkingen"].append("Your site asks AI not to use its content (a 'noai' tag).")
        if "noindex" in kop or ('name="robots"' in laag and "noindex" in laag.split('name="robots"', 1)[1][:120]):
            uitkomst["opmerkingen"].append("Your homepage says 'noindex': search engines, and the AI that "
                                           "relies on them, are asked to leave it out.")

    geblokt = [r for r in uitkomst["robots"] if not r["mag"] and r["bot"] in BELANGRIJK]
    if geblokt:
        uitkomst["oordeel"] = "blocked"
        uitkomst["kop"] = (f"{len(geblokt)} of the AI robots that find stores for shoppers "
                           f"cannot read your store.")
    elif any(not r["mag"] for r in uitkomst["robots"]):
        uitkomst["oordeel"] = "partly"
        uitkomst["kop"] = ("The robots that find stores for shoppers can read your store. You block "
                           "some training robots, which does not stop you from being recommended.")
    else:
        uitkomst["oordeel"] = "open"
        uitkomst["kop"] = "Every AI robot we checked may read your store."
    uitkomst["herstel"] = (
        "On Shopify: Online Store, Themes, Edit code, then robots.txt.liquid (create it from the "
        "template if it is not there) and remove the Disallow lines for these robots. On WordPress or "
        "WooCommerce: check your SEO plugin's robots.txt setting, or the robots.txt file on your server.")
    return uitkomst


# ------------------------------------------------------------------ 2. productgegevens

def _producten(html):
    """Alle Product-blokken uit de JSON-LD van een pagina."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    gevonden = []

    def loop(node):
        if isinstance(node, dict):
            t = node.get("@type")
            soorten = t if isinstance(t, list) else [t]
            if "Product" in soorten or "ProductGroup" in soorten:
                gevonden.append(node)
            for w in node.values():
                loop(w)
        elif isinstance(node, list):
            for x in node:
                loop(x)

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            loop(json.loads(tag.string or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
    return gevonden


def productdata_check(url, ophalen=None):
    url, fout = _schoon(url)
    if fout:
        return {"fout": fout}
    pagina = _haal(url, ophalen)
    if pagina is None or pagina.status_code >= 400:
        return {"fout": "We could not open that page. Check the address, or try again in a minute."}
    if scan_engine.lijkt_op_blokkadepagina(pagina.text):
        return {"fout": "The page showed us a security check instead of the product. AI robots often get "
                        "the same wall. Check your bot protection settings."}
    producten = _producten(pagina.text)
    p = producten[0] if producten else {}
    aanbod = p.get("offers") or {}
    if isinstance(aanbod, list):
        aanbod = aanbod[0] if aanbod else {}
    if isinstance(aanbod, dict) and aanbod.get("@type") == "AggregateOffer" and not aanbod.get("price"):
        aanbod = dict(aanbod, price=aanbod.get("lowPrice"))
    merk = p.get("brand")
    if isinstance(merk, dict):
        merk = merk.get("name")
    beschrijving = (p.get("description") or "").strip()
    punten = [
        ("Product details in the code", bool(producten),
         "AI assistants copy facts from these hidden product details (schema.org Product)."),
        ("Product name", bool(p.get("name")), "The exact name shoppers see."),
        ("Price", bool(aanbod.get("price") or aanbod.get("lowPrice")),
         "Without a price in the code, AI often skips a product when someone asks for a budget."),
        ("Currency", bool(aanbod.get("priceCurrency")), "So a price reads as euros, not just a number."),
        ("In stock or not", bool(aanbod.get("availability")),
         "AI avoids recommending what might be sold out."),
        ("Brand", bool(merk), "Many shopping questions name a brand."),
        ("Reviews or rating", bool(p.get("aggregateRating") or p.get("review")),
         "A rating is one of the strongest reasons for AI to name a store."),
        ("Product code (GTIN, EAN or SKU)", bool(p.get("gtin13") or p.get("gtin") or p.get("gtin8")
                                                  or p.get("gtin12") or p.get("gtin14") or p.get("sku")),
         "Lets AI match your product to the same item elsewhere."),
        ("A real description (80+ words)", len(beschrijving.split()) >= 80,
         "A short description gives AI nothing to quote when a shopper asks why this one."),
    ]
    goed = sum(1 for _, ok, _ in punten if ok)
    return {"pagina": url, "punten": [{"naam": n, "ok": ok, "waarom": w} for n, ok, w in punten],
            "goed": goed, "van": len(punten),
            "kop": (f"{goed} of {len(punten)} details AI looks for are on this page."
                    if producten else "We found no product details in the code of this page.")}


# ------------------------------------------------------------------ 3. index

def index_check(url):
    url, fout = _schoon(url)
    if fout:
        return {"fout": fout}
    try:
        import klantbeeld
        beeld = klantbeeld.bouw(url)
    except Exception:
        beeld = None
    if not beeld or not beeld.get("positie"):
        return {"gevonden": False, "winkel": urlparse(url).netloc,
                "kop": "Your store is not in the Krillo Index yet.",
                "uitleg": "We add stores category by category. Run the free check on our homepage and "
                          "we measure yours; you get the result by email."}
    import categorieen
    land = (beeld.get("land") or "").lower()
    return {"gevonden": True, "winkel": urlparse(url).netloc, "positie": beeld["positie"],
            "van": beeld.get("van"), "categorie": categorieen.naam_en(beeld["categorie"]),
            "land": land.upper(), "pagina": f"/index/{land}/{beeld['categorie']}" if land else "/index",
            "kop": f"#{beeld['positie']} of {beeld.get('van')} in {categorieen.naam_en(beeld['categorie'])}."}


def bewaar_gebruik(tool, url, oordeel):
    """Telt hoe vaak elke tool gebruikt wordt (ochtendbericht). Faalt nooit hard."""
    conn = db._get_connection()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS tool_gebruik (
                                   id SERIAL PRIMARY KEY, tool TEXT, url TEXT, oordeel TEXT,
                                   op TIMESTAMPTZ NOT NULL DEFAULT now())""")
                cur.execute("INSERT INTO tool_gebruik (tool, url, oordeel) VALUES (%s, %s, %s)",
                            (tool, (url or "")[:300], (oordeel or "")[:60]))
    except Exception as e:
        print(f"Toolgebruik bewaren mislukt: {e}")
    finally:
        conn.close()



# ------------------------------------------------------------------ 4. leverancierstekst (stap 217)
# IDEE 30 SEPTEMBER, door Nino goedgekeurd. Veel kleine winkels, vooral op
# Shopify, gebruiken de productteksten van hun leverancier. Honderd andere
# winkels hebben precies dezelfde tekst, en dan heeft AI geen reden om juist
# jouw winkel te noemen. Deze check maakt dat zichtbaar: van een paar producten
# een kenmerkende zin letterlijk opzoeken, en tellen op hoeveel andere sites
# hij staat. Een zin als "7 van je 10 productteksten staan woord voor woord op
# 40 andere winkels" vergeet een winkelier niet, en het is precies wat Fix oplost.
#
# Kosten: een zoekopdracht per product, hoogstens LEVERANCIER_PRODUCTEN per
# check, en hoogstens LEVERANCIER_PER_DAG checks per dag voor de hele site.
LEVERANCIER_PRODUCTEN = 5
LEVERANCIER_PER_DAG = int(os.environ.get("LEVERANCIER_PER_DAG", "60"))
_leverancier_teller = {"dag": "", "n": 0}


def _kenmerkende_zin(tekst):
    """De langste gewone zin van 8 tot 25 woorden: lang genoeg om uniek te
    zijn, kort genoeg om letterlijk te zoeken. None als er geen is."""
    import html as htmlmod
    kaal = re.sub(r"<[^>]+>", " ", tekst or "")
    kaal = re.sub(r"\s+", " ", htmlmod.unescape(kaal)).strip()
    zinnen = [z.strip(" -•*") for z in re.split(r"(?<=[.!?])\s+", kaal)]
    goed = [z for z in zinnen if 8 <= len(z.split()) <= 25 and '"' not in z]
    if not goed:
        return None
    return max(goed, key=len).rstrip(".!?")


def _teksten_van(url, ophalen=None):
    """[(titel, tekst)] van een paar producten. Shopify geeft /products.json
    openbaar; anders de productgegevens van de pagina zelf."""
    basis = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    uit = []
    j = _haal(basis + "/products.json?limit=20", ophalen)
    if j is not None and j.status_code == 200:
        try:
            for p in (j.json().get("products") or []):
                if len(re.sub(r"<[^>]+>", " ", p.get("body_html") or "").split()) >= 20:
                    uit.append((p.get("title") or "", p.get("body_html") or ""))
        except ValueError:
            pass
    if not uit:
        pagina = _haal(url, ophalen)
        if pagina is not None and pagina.status_code < 400:
            for p in _producten(pagina.text):
                if len((p.get("description") or "").split()) >= 20:
                    uit.append((p.get("name") or "", p.get("description") or ""))
    return uit[:LEVERANCIER_PRODUCTEN]


def leverancierstekst_check(url, ophalen=None, zoek=None, vandaag=None):
    url, fout = _schoon(url)
    if fout:
        return {"fout": fout}
    import bronnen
    if zoek is None:
        if not bronnen.beschikbaar():
            return {"fout": "This check is not available right now. Try again tomorrow."}
        zoek = bronnen.zoek
    vandaag = vandaag or time.strftime("%Y-%m-%d")
    if _leverancier_teller["dag"] != vandaag:
        _leverancier_teller.update(dag=vandaag, n=0)
    if _leverancier_teller["n"] >= LEVERANCIER_PER_DAG:
        return {"fout": "This check is very busy today. Try again tomorrow."}
    teksten = _teksten_van(url, ophalen)
    if not teksten:
        return {"fout": "We could not find product texts to check. Paste the address of one product page "
                        "instead of the homepage."}
    _leverancier_teller["n"] += 1
    eigen = urlparse(url).netloc.replace("www.", "")
    rijen = []
    for titel, tekst in teksten:
        zin = _kenmerkende_zin(tekst)
        if not zin:
            continue
        try:
            resultaten = zoek(f'"{zin}"') or []
        except Exception:
            resultaten = []
        andere = []
        for r in resultaten:
            host = urlparse(r.get("url") or "").netloc.replace("www.", "")
            if host and host != eigen and not host.endswith(("shopify.com", "myshopify.com")) and host not in andere:
                andere.append(host)
        rijen.append({"titel": titel, "zin": zin, "andere": andere[:5], "aantal": len(andere)})
    if not rijen:
        return {"fout": "Your product texts are too short to check. That is a problem of its own: AI has "
                        "nothing to quote."}
    gekopieerd = sum(1 for r in rijen if r["aantal"])
    sites = len({h for r in rijen for h in r["andere"]})
    if gekopieerd:
        kop = (f"{gekopieerd} of {len(rijen)} product texts we checked appear word for word on other sites "
               f"({sites} {'site' if sites == 1 else 'sites'}).")
    else:
        kop = f"None of the {len(rijen)} product texts we checked were found word for word on other sites. Good."
    return {"winkel": eigen, "teksten": rijen, "gekopieerd": gekopieerd, "van": len(rijen), "kop": kop,
            "advies": ("AI has no reason to name your store for a text a dozen other stores also have. Rewrite "
                       "these in your own words: who the product is for, what makes it different, the facts a "
                       "buyer asks about. Fix does this for you." if gekopieerd else "")}
