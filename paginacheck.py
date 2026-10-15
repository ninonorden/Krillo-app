"""AI-gereedheid per pagina (stap 255, 1 oktober 2026, goedgekeurd door Nino).

WAAROM. De dertien controles kijken vooral naar de homepage. Maar AI noemt een
winkel om zijn product- en categoriepagina's: daar staat wat hij verkoopt.
Otterly heeft zo'n controle per pagina vanaf 29 dollar. Hier: elke week, voor
betalende klanten, de homepage plus hoogstens vijf product- en
categoriepagina's, met per pagina hoogstens drie dingen om te doen.

PER PAGINA (dezelfde metingen als de dertien controles, geen tweede manier):
- staat de tekst in de pagina zelf (zonder scripts)?
- een hoofdkop (H1)?
- een titel en een omschrijving?
- op een productpagina: productgegevens die AI kan lezen (schema.org Product)?
2 oktober (goedgekeurd door Nino): nu ook PER PAGINA per AI-robot (GPTBot,
OAI-SearchBot, PerplexityBot, Googlebot): mag hij de pagina lezen volgens
robots.txt, krijgt hij de pagina als hij met zijn naam aanklopt (veel
beveiligingen weigeren op naam), en zegt de pagina zelf "noindex". Zie
crawlbaarheid() hieronder.

Geen AI, kost niets behalve het ophalen. Engels, zoals het dashboard.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import db

MAX_PAGINAS = 5


def _sql(opdracht, waarden=None, alles=False):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return [] if alles else None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opdracht, waarden)
                if cur.description is None:
                    return None
                return [dict(r) for r in cur.fetchall()] if alles else (
                    dict(cur.fetchone()) if cur.rowcount else None)
    finally:
        conn.close()


def maak_tabel():
    _sql("""CREATE TABLE IF NOT EXISTS paginachecks (
                webshop_url TEXT PRIMARY KEY,
                op TIMESTAMPTZ NOT NULL,
                uitkomst JSONB NOT NULL)""")


def is_productpagina(url):
    pad = urlparse(url).path.lower()
    return any(s in pad for s in ("/product", "/products/", "/artikel", "/p/"))


def keur_pagina(url, html):
    """Hoogstens drie acties voor een pagina, in het Engels. [] als alles goed is."""
    import scan_engine
    from bs4 import BeautifulSoup
    if html is None:
        return ["We could not load this page. Check that it opens without a login or a cookie wall."]
    acties = []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    woorden = len(soup.get_text(" ", strip=True).split())
    if woorden < 150:
        acties.append(f"Only {woorden} words are readable without scripts. Put the main text in the page "
                      f"itself, so AI can read it.")
    koppen = scan_engine.check_heading_structuur(html)
    if koppen["score"] < 50:
        acties.append("Give the page one main heading (H1) that says what it is.")
    elif koppen["score"] < 100:
        acties.append("Keep one main heading (H1); make the other big headings subheadings.")
    basis = scan_engine.check_basics(html)
    if basis["score"] < 100:
        acties.append("Add a clear page title and a description of one or two sentences.")
    if is_productpagina(url):
        data = scan_engine.check_structured_data(html)
        if data["score"] < 70:
            acties.append("Add product data (schema.org Product, with price and availability) so AI can "
                          "read the product without guessing.")
    return acties[:3]


# ---------------------------------------------------------------------------
# Crawlbaarheid per pagina per AI-robot (2 oktober). Otterly verkoopt dit als
# losse "Crawlability Checker". Wat wij doen, en wat niet:
# - robots.txt van de winkel lezen en per pagina per robot zeggen of hij mag;
# - de pagina ophalen met de naam van de robot. Een firewall die op naam
#   blokkeert (vaak bij Cloudflare-instellingen) zie je zo. Een firewall die op
#   het IP-adres van de echte robot controleert, zien wij NIET; dat staat erbij;
# - "noindex" in de pagina of in de kop X-Robots-Tag.
# ---------------------------------------------------------------------------
CRAWLERS = [
    ("OAI-SearchBot", "ChatGPT search",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"),
    ("GPTBot", "OpenAI training",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot"),
    ("PerplexityBot", "Perplexity",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
    ("Googlebot", "Google and Gemini",
     "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
]
# Robots die tellen voor gevonden worden (GPTBot is training: blokkeren mag).
VOOR_GEVONDEN = {"OAI-SearchBot", "PerplexityBot", "Googlebot"}


def _haal_als(url, agent):
    """(statuscode, html, kop X-Robots-Tag) met de naam van een robot, of (None, None, '')."""
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": agent, "Accept": "text/html"}, timeout=12,
                         allow_redirects=True)
        return r.status_code, (r.text if r.status_code < 400 else None), (r.headers.get("X-Robots-Tag") or "")
    except Exception:
        return None, None, ""


def _noindex(html, kop):
    laag = (html or "")[:30000].lower()
    meta = re.search(r'<meta[^>]+name=["\']robots["\'][^>]*>', laag)
    return "noindex" in (kop or "").lower() or bool(meta and "noindex" in meta.group(0))


def crawlbaarheid(webshop_url, paginas, robots_tekst=None, haal_als=None):
    """Per pagina per robot: {"bot", "wie", "robots": bool, "status": int|None, "open": bool}.
    Plus "noindex" per pagina. robots_tekst en haal_als zijn er voor de test.

    Geeft {pagina_url: {"robots": [...], "noindex": bool}}."""
    import urllib.robotparser
    import scan_engine
    basis = f"{urlparse(webshop_url).scheme}://{urlparse(webshop_url).netloc}"
    if robots_tekst is None:
        r = scan_engine.fetch(basis + "/robots.txt", pogingen=1)
        robots_tekst = r.text if (r is not None and r.status_code == 200) else ""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse((robots_tekst or "").splitlines())
    haal_als = haal_als or _haal_als
    uit = {}
    for u in paginas:
        rijen, noindex = [], False
        for bot, wie, agent in CRAWLERS:
            mag = bool(parser.can_fetch(bot, u))
            status, html, kop = haal_als(u, agent) if mag else (None, None, "")
            if html is not None and _noindex(html, kop):
                noindex = True
            rijen.append({"bot": bot, "wie": wie, "robots": mag, "status": status,
                          "open": mag and status is not None and status < 400})
        uit[u] = {"robots": rijen, "noindex": noindex}
    return uit


def crawl_acties(info):
    """Hoogstens een actie over robots voor een pagina, in het Engels."""
    if not info:
        return []
    if info.get("noindex"):
        return ["This page says 'noindex': search engines, and the AI that relies on them, are asked to "
                "leave it out. Remove the noindex if you want it found."]
    dicht = [r for r in info["robots"] if r["bot"] in VOOR_GEVONDEN and not r["open"]]
    if not dicht:
        return []
    door_robots = [r["bot"] for r in dicht if not r["robots"]]
    if door_robots:
        return [f"Your robots.txt keeps {', '.join(door_robots)} out of this page. Remove that Disallow line "
                f"so AI search can read it."]
    # Alleen een echte weigering (een foutcode) telt. Geen antwoord kan aan ons
    # liggen (netwerk), en dan zeggen wij niets in plaats van een vals alarm.
    geweigerd = [r for r in dicht if r["status"] is not None]
    if not geweigerd:
        return []
    return [f"This page refused {', '.join(r['bot'] for r in geweigerd)} (error {geweigerd[0]['status']}). "
            f"A firewall or bot protection is probably blocking it by name."]


def controleer(webshop_url, haal=None, robots_tekst=None, haal_als=None):
    """Haalt de homepage en hoogstens vijf pagina's op en keurt ze. haal: voor de test."""
    import scan_engine
    if haal is None:
        def haal(u):
            r = scan_engine.fetch(u, pogingen=1)
            return r.text if r is not None else None
    home = haal(webshop_url)
    paginas = [webshop_url] + (scan_engine.find_relevant_pages(webshop_url, home, limit=MAX_PAGINAS) if home else [])
    paginas = paginas[:MAX_PAGINAS + 1]
    # 15 oktober (fixkit.py): robots.txt een keer ophalen, voor de crawlcheck en
    # voor de kant-en-klare regels.
    if robots_tekst is None:
        try:
            basis = f"{urlparse(webshop_url).scheme}://{urlparse(webshop_url).netloc}"
            r = scan_engine.fetch(basis + "/robots.txt", pogingen=1)
            robots_tekst = r.text if (r is not None and r.status_code == 200) else ""
        except Exception:
            robots_tekst = ""
    try:
        crawl = crawlbaarheid(webshop_url, paginas, robots_tekst=robots_tekst, haal_als=haal_als)
    except Exception as e:
        print(f"Crawlbaarheid mislukt voor {webshop_url}: {e}")
        crawl = {}
    uit = []
    for u in paginas:
        html = home if u == webshop_url else haal(u)
        info = crawl.get(u)
        acties = (crawl_acties(info) + keur_pagina(u, html))[:3]
        # 15 oktober: per pagina wat er aan gestructureerde gegevens ontbreekt,
        # met een blok om te plakken (fixkit.py).
        try:
            import fixkit
            schema = fixkit.schema_check(html, u, is_productpagina(u), is_home=(u == webshop_url))
        except Exception as e:
            print(f"Schemacheck mislukt voor {u}: {e}")
            schema = []
        uit.append({"url": u, "pad": urlparse(u).path or "/", "acties": acties, "schema": schema,
                    "robots": (info or {}).get("robots") or [], "noindex": (info or {}).get("noindex", False)})
    try:
        import fixkit
        _site_fixes[webshop_url] = fixkit.site_fixes(webshop_url, robots_tekst, home)
    except Exception as e:
        print(f"Site-fixes mislukt voor {webshop_url}: {e}")
    return uit


# De oplossingen op siteniveau van de laatste controle (robots, llms.txt), tot bewaar().
_site_fixes = {}


def bewaar(webshop_url, uitkomst):
    maak_tabel()
    _sql("""INSERT INTO paginachecks (webshop_url, op, uitkomst) VALUES (%s, %s, %s)
            ON CONFLICT (webshop_url) DO UPDATE SET op = EXCLUDED.op, uitkomst = EXCLUDED.uitkomst""",
         (webshop_url, datetime.now(timezone.utc), json.dumps(uitkomst)))
    site = _site_fixes.pop(webshop_url, None)
    if site is not None:
        db.zet_instelling("fixkit:" + webshop_url[:180], json.dumps(site))


def laatste(webshop_url):
    maak_tabel()
    rij = _sql("SELECT op, uitkomst FROM paginachecks WHERE webshop_url = %s", (webshop_url,))
    if not rij:
        return None
    u = rij["uitkomst"]
    try:
        site = json.loads(db.get_instelling("fixkit:" + webshop_url[:180]) or "null")
    except (TypeError, ValueError):
        site = None
    return {"op": rij["op"], "paginas": json.loads(u) if isinstance(u, str) else u, "site": site}


# ---------------------------------------------------------------------------
# Stap 331 (15 oktober, goedgekeurd 8 oktober): alle productpagina's.
# De wekelijkse check hierboven kijkt naar de homepage en vijf pagina's. Een
# winkel met 400 producten weet dan niet welke productpagina AI overslaat.
# Alles in een keer ophalen past niet (512 MB, en het ziet eruit als een
# aanval op de winkel). Daarom: de productadressen uit de sitemap, en elke
# week PRODUCTEN_PER_WEEK ervan, eerst de nog nooit nagekeken, daarna de
# oudste. Na een paar weken is elke productpagina langs geweest.
# Geen AI, alleen ophalen en dezelfde keuring als hierboven (keur_pagina).
# ---------------------------------------------------------------------------
PRODUCTEN_PER_WEEK = 40
MAX_PRODUCTEN = 1000          # zoveel adressen onthouden we per winkel
PRODUCT_SLEUTEL = "productscore:"
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def productadressen(webshop_url, haal):
    """Productadressen uit /sitemap.xml (en hoogstens drie deelsitemaps met
    'product' in de naam, zoals bij Shopify en WooCommerce)."""
    basis = f"{urlparse(webshop_url).scheme}://{urlparse(webshop_url).netloc}"
    hoofd = haal(basis + "/sitemap.xml") or ""
    locs = _LOC.findall(hoofd)
    deel = [u for u in locs if u.lower().endswith(".xml") or "sitemap" in u.lower()]
    adressen = [u for u in locs if u not in deel]
    for u in [d for d in deel if "product" in d.lower()][:3]:
        adressen += _LOC.findall(haal(u) or "")
    gezien, uit = set(), []
    for u in adressen:
        if is_productpagina(u) and urlparse(u).netloc == urlparse(basis).netloc and u not in gezien:
            gezien.add(u)
            uit.append(u)
    return uit[:MAX_PRODUCTEN]


def _lees_producten(webshop_url):
    try:
        return json.loads(db.get_instelling(PRODUCT_SLEUTEL + webshop_url[:180]) or "null") or {}
    except (TypeError, ValueError):
        return {}


def productronde(webshop_url, haal=None, per_week=None, nu=None):
    """Keurt de volgende portie productpagina's en bewaart alles. Geeft de stand."""
    import scan_engine
    per_week = PRODUCTEN_PER_WEEK if per_week is None else per_week
    nu = (nu or datetime.now(timezone.utc)).isoformat()
    if haal is None:
        def haal(u):
            r = scan_engine.fetch(u, pogingen=1)
            return r.text if (r is not None and getattr(r, "status_code", 200) == 200) else None
    stand = _lees_producten(webshop_url)
    oud = stand.get("paginas") or {}
    adressen = productadressen(webshop_url, haal)
    if not adressen:
        return stand or None
    # Nog nooit gekeurd eerst, dan de oudste keuring.
    volgorde = sorted(adressen, key=lambda u: (u in oud, (oud.get(u) or {}).get("op") or ""))
    for u in volgorde[:per_week]:
        html = haal(u)
        acties = keur_pagina(u, html)
        noindex = bool(html) and _noindex(html, "")
        if noindex:
            acties = ["This page tells search engines and AI not to index it (noindex). Remove that if "
                      "you want AI to find the product."] + acties[:2]
        oud[u] = {"op": nu, "acties": acties, "overgeslagen": html is None or noindex
                  or any(a.startswith("Only ") for a in acties)}
    # Alleen adressen die nog in de sitemap staan (verwijderde producten vallen weg).
    stand = {"op": nu, "totaal": len(adressen),
             "paginas": {u: oud[u] for u in adressen if u in oud}}
    db.zet_instelling(PRODUCT_SLEUTEL + webshop_url[:180], json.dumps(stand))
    return stand


def productscore(webshop_url):
    """Voor het dashboard: {"totaal", "gekeurd", "goed", "overgeslagen": [(pad, acties)],
    "te_doen": [(pad, acties)]} of None."""
    stand = _lees_producten(webshop_url)
    paginas = stand.get("paginas") or {}
    if not paginas:
        return None
    rijen = sorted(paginas.items())
    pad = lambda u: urlparse(u).path or u  # noqa: E731
    return {"totaal": stand.get("totaal") or len(paginas), "gekeurd": len(paginas),
            "goed": sum(1 for _, v in rijen if not v.get("acties")),
            "overgeslagen": [(pad(u), v.get("acties")) for u, v in rijen if v.get("overgeslagen")][:20],
            "te_doen": [(pad(u), v.get("acties")) for u, v in rijen
                        if v.get("acties") and not v.get("overgeslagen")][:20]}


def ronde(webshop_url):
    """Voor de wekelijkse ronde: controleren, teksten schrijven (stap 254), bewaren."""
    uitkomst = controleer(webshop_url)
    try:
        schrijf_teksten(webshop_url, uitkomst)
    except Exception as e:
        print(f"Paginateksten mislukt voor {webshop_url}: {e}")
    bewaar(webshop_url, uitkomst)
    try:
        productronde(webshop_url)
    except Exception as e:
        print(f"Productronde mislukt voor {webshop_url}: {e}")
    return uitkomst


# ---------------------------------------------------------------------------
# Stap 254 (1 oktober, goedgekeurd door Nino): per pagina kant-en-klare tekst.
# AthenaHQ en Otterly geven per pagina concrete aanpassingen. Hier: voor
# hoogstens drie pagina's waar de titel, de omschrijving of de tekst tekortschiet,
# een nieuwe titel, een omschrijving en een eerste alinea, in de taal van de
# pagina, alleen uit wat er al op de pagina staat (niets verzinnen: geen prijzen,
# levertijden of keurmerken die er niet staan). Langs de kostenrem per klant.
# ---------------------------------------------------------------------------
TEKST_MODEL = "claude-haiku-4-5-20251001"
MAX_TEKSTEN = 3
OPDRACHT = """You improve one page of an online store so AI assistants (ChatGPT, Gemini) understand it.
Page address: {url}
Current title: {titel}
Current description: {omschrijving}
Text on the page (shortened):
{tekst}

Write in the SAME language as the page text. Use ONLY facts that are in the text above: no prices, delivery
times, ratings, awards or claims that are not there. Plain words, no hype, no em dashes, no exclamation marks.
Answer ONLY with JSON:
{{"titel": "a page title of at most 60 characters that says what is sold here",
  "omschrijving": "a description of at most 155 characters",
  "alinea": "a first paragraph of two or three sentences that says plainly what this page offers"}}"""


def _tekst_van(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    titel = soup.title.string.strip() if soup.title and soup.title.string else ""
    d = soup.find("meta", attrs={"name": "description"})
    omschrijving = d["content"].strip() if d and d.get("content") else ""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    return titel, omschrijving, " ".join(soup.get_text(" ", strip=True).split())[:2500]


def schrijf_teksten(webshop_url, paginas, haal=None, vraag=None):
    """Voegt aan hoogstens drie pagina's met tekstacties een "voorstel" toe.

    vraag: alleen voor de test (krijgt de opdracht, geeft de JSON-tekst)."""
    import kosten
    from beoordeling import _schoon_json
    if haal is None:
        import scan_engine

        def haal(u):
            r = scan_engine.fetch(u, pogingen=1)
            return r.text if r is not None else None
    gedaan = 0
    for p in paginas:
        if gedaan >= MAX_TEKSTEN:
            break
        if not any(("title" in a or "words are readable" in a) for a in p.get("acties") or []):
            continue
        if not kosten.mag_doorgaan(webshop_url=webshop_url).get("mag"):
            break
        html = haal(p["url"])
        if not html:
            continue
        titel, omschrijving, tekst = _tekst_van(html)
        if len(tekst.split()) < 15:
            continue  # te weinig om iets eerlijks uit te halen
        opdracht = OPDRACHT.format(url=p["url"], titel=titel or "(none)", omschrijving=omschrijving or "(none)",
                                   tekst=tekst)
        try:
            if vraag:
                ruw = vraag(opdracht)
            else:
                import ai_content
                import time
                client = ai_content._get_client()
                begin = time.time()
                antwoord = client.messages.create(model=TEKST_MODEL, max_tokens=600,
                                                  messages=[{"role": "user", "content": opdracht}])
                kosten.registreer_aanroep("anthropic", TEKST_MODEL, antwoord.usage.input_tokens,
                                          antwoord.usage.output_tokens, soort="paginateksten",
                                          webshop_url=webshop_url, duur_ms=int((time.time() - begin) * 1000))
                ruw = antwoord.content[0].text
            data = _schoon_json(ruw) or {}
        except Exception as e:
            print(f"Paginatekst mislukt voor {p['url']}: {e}")
            continue
        voorstel = {k: " ".join(str(data.get(k) or "").replace("—", ",").split())
                    for k in ("titel", "omschrijving", "alinea")}
        if voorstel["titel"] and voorstel["alinea"]:
            voorstel["titel"] = voorstel["titel"][:70]
            voorstel["omschrijving"] = voorstel["omschrijving"][:170]
            p["voorstel"] = voorstel
            gedaan += 1
    return paginas
