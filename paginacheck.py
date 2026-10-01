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
Of AI-robots erbij mogen is een instelling voor de hele site; die staat al in de
dertien controles en de robotwacht, niet hier per pagina.

Geen AI, kost niets behalve het ophalen. Engels, zoals het dashboard.
"""
import json
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


def controleer(webshop_url, haal=None):
    """Haalt de homepage en hoogstens vijf pagina's op en keurt ze. haal: voor de test."""
    import scan_engine
    if haal is None:
        def haal(u):
            r = scan_engine.fetch(u, pogingen=1)
            return r.text if r is not None else None
    home = haal(webshop_url)
    paginas = [webshop_url] + (scan_engine.find_relevant_pages(webshop_url, home, limit=MAX_PAGINAS) if home else [])
    uit = []
    for u in paginas[:MAX_PAGINAS + 1]:
        html = home if u == webshop_url else haal(u)
        uit.append({"url": u, "pad": urlparse(u).path or "/", "acties": keur_pagina(u, html)})
    return uit


def bewaar(webshop_url, uitkomst):
    maak_tabel()
    _sql("""INSERT INTO paginachecks (webshop_url, op, uitkomst) VALUES (%s, %s, %s)
            ON CONFLICT (webshop_url) DO UPDATE SET op = EXCLUDED.op, uitkomst = EXCLUDED.uitkomst""",
         (webshop_url, datetime.now(timezone.utc), json.dumps(uitkomst)))


def laatste(webshop_url):
    maak_tabel()
    rij = _sql("SELECT op, uitkomst FROM paginachecks WHERE webshop_url = %s", (webshop_url,))
    if not rij:
        return None
    u = rij["uitkomst"]
    return {"op": rij["op"], "paginas": json.loads(u) if isinstance(u, str) else u}


def ronde(webshop_url):
    """Voor de wekelijkse ronde: controleren, teksten schrijven (stap 254), bewaren."""
    uitkomst = controleer(webshop_url)
    try:
        schrijf_teksten(webshop_url, uitkomst)
    except Exception as e:
        print(f"Paginateksten mislukt voor {webshop_url}: {e}")
    bewaar(webshop_url, uitkomst)
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
