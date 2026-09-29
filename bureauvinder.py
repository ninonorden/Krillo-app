"""Bureaus vinden via de voettekst van winkels (stap 115, 28 september).

WAAROM DIT BESTAAT. Veel webshops noemen onderaan hun bureau: "webshop door X",
"made by X", "realisatie: X". Een bureau heeft tientallen winkels. Kunnen wij
een bureau laten zien "12 van jullie klanten staan in de Krillo Index, 9 worden
door ChatGPT niet genoemd", dan heeft dat bureau een reden om Krillo aan zijn
klanten te verkopen, en via /partners (stap 94) verdient het er 20 procent aan.
Een mail aan een bureau is tientallen winkels tegelijk.

HOE
- herken(html): zoekt in de voettekst een link naar een ander domein met een
  "gemaakt door"-achtige tekst erbij. Platforms (Shopify, Lightspeed, WooCommerce),
  keurmerken, betaaldiensten en sociale media tellen niet: dat zijn geen bureaus.
- ronde(): elk uur een klein aantal winkels uit de index langs (alleen de
  homepage), en bij bureaus met genoeg winkels een keer het algemene adres zoeken
  met de gewone adresvinder.
- /admin/bureaus: de bureaus met BUREAU_MIN of meer winkels, met hun pagina en de
  mail. De eerste HANDMATIG_EERST mails verstuurt Nino met de hand (een bureau
  is een grote kans, en wij willen eerst zien hoe ze reageren). Daarna kan
  BUREAUMAIL_AUTO=1 in Render, en gaan er hoogstens AUTO_PER_DAG per dag vanzelf.
- /bureau/<token>: de pagina voor het bureau. Niet in Google (noindex): het gaat
  over zijn klanten, en die pagina is voor hem.

REGELS: alleen gegevens die al openbaar in de index staan; alleen een algemeen
adres (info@); afmelden met een klik, en dan nooit meer.
"""
import os
import re
import secrets
from urllib.parse import urljoin, urlparse

import db

BUREAU_MIN = int(os.environ.get("BUREAU_MIN", "3"))
HANDMATIG_EERST = 10
AUTO_PER_DAG = 2
PER_RONDE = 15
ADRESSEN_PER_RONDE = 3

# Tekst bij de link die zegt: dit bureau maakte de site.
_KREDIET = re.compile(
    r"(made|designed|built|developed|created|crafted|realised|realized|powered)\s+(by|with)\b"
    r"|(website|webshop|webwinkel|webdesign|design|ontwerp|realisatie|ontwikkeling|development)\s*(door|by|:)"
    r"|(gemaakt|ontworpen|ontwikkeld|gerealiseerd|gebouwd)\s+door\b"
    r"|\b(webdesign|webdevelopment|webbureau|internetbureau|e-?commerce\s*bureau)\b",
    re.I)

# Geen bureau: platforms, betalen, keurmerken, sociale media, analytics.
_GEEN_BUREAU = (
    "shopify.", "myshopify.", "lightspeed", "woocommerce.", "wordpress.", "wix.", "squarespace.",
    "magento.", "adobe.", "shopware.", "ccvshop.", "mijnwebwinkel.", "jouwweb.", "webnode.", "strato.",
    "one.com", "hostnet.", "transip.", "mollie.", "paypal.", "klarna.", "stripe.", "adyen.", "ideal.",
    "thuiswinkel.", "webwinkelkeur.", "kiyoh.", "trustpilot.", "trustedshops.", "feedbackcompany.",
    "facebook.", "instagram.", "linkedin.", "twitter.", "x.com", "tiktok.", "youtube.", "pinterest.",
    "google.", "apple.", "postnl.", "dhl.", "sendcloud.", "myparcel.", "bol.com", "kvk.nl",
    "cookiebot.", "cookiecode.", "complianz.", "elementor.", "github.", "vercel.", "netlify.",
)


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
                    return cur.rowcount
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def maak_tabellen(cur):
    """Aangeroepen vanuit db.init_db."""
    cur.execute("""CREATE TABLE IF NOT EXISTS bureau_winkels (
                       webshop_url TEXT PRIMARY KEY,
                       bureau_site TEXT,
                       bureau_naam TEXT,
                       gekeken_op TIMESTAMPTZ NOT NULL DEFAULT now())""")
    cur.execute("CREATE INDEX IF NOT EXISTS bureau_winkels_site ON bureau_winkels (bureau_site)")
    cur.execute("""CREATE TABLE IF NOT EXISTS bureaus (
                       site TEXT PRIMARY KEY,
                       naam TEXT,
                       token TEXT UNIQUE,
                       email TEXT,
                       email_gezocht_op TIMESTAMPTZ,
                       stand TEXT NOT NULL DEFAULT 'nieuw',   -- nieuw, gemaild, overgeslagen, afgemeld
                       gemaild_op TIMESTAMPTZ,
                       met_de_hand BOOLEAN NOT NULL DEFAULT FALSE,
                       bekeken_op TIMESTAMPTZ)""")


def _domein(url):
    try:
        return (urlparse(url).netloc or "").lower().split(":")[0].removeprefix("www.")
    except Exception:
        return ""


def _is_platform(domein):
    return any(stuk in domein for stuk in _GEEN_BUREAU)


def _schone_naam(tekst, domein):
    tekst = re.sub(r"\s+", " ", tekst or "").strip(" -|:·•")
    # Alleen de naam: "Webdesign door Pixelwerk" wordt "Pixelwerk".
    tekst = re.sub(r"^.*?\b(by|door|with)\b\s*", "", tekst, flags=re.I) if _KREDIET.search(tekst) else tekst
    tekst = tekst.strip(" -|:·•")
    if not tekst or len(tekst) > 40 or _KREDIET.fullmatch(tekst) or tekst.lower() in ("hier", "here", "link"):
        return domein
    return tekst


def herken(html, webshop_url):
    """Het bureau in de voettekst van deze winkel, of None.
    Geeft {"site": "https://bureau.nl", "naam": "Bureau"}."""
    if not html:
        return None
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    eigen = _domein(webshop_url)
    # Eerst de voettekst; heeft de site geen <footer>, dan het laatste stuk.
    delen = soup.find_all("footer") or []
    if not delen:
        links = soup.find_all("a")
        delen = [None]
        kandidaten = links[int(len(links) * 0.7):]
    for deel in delen:
        if deel is not None:
            kandidaten = deel.find_all("a")
        for a in kandidaten:
            href = (a.get("href") or "").strip()
            if not href.lower().startswith(("http://", "https://", "//")):
                continue
            domein = _domein(urljoin("https://x/", href))
            if not domein or domein == eigen or domein.endswith("." + eigen) or _is_platform(domein):
                continue
            tekst = a.get_text(" ", strip=True) or a.get("title") or ""
            ouder = a.parent.get_text(" ", strip=True)[:160] if a.parent is not None else ""
            if _KREDIET.search(tekst) or _KREDIET.search(ouder) or _KREDIET.search(a.get("title") or ""):
                return {"site": f"https://{domein}", "naam": _schone_naam(tekst, domein)}
    return None


def onthoud(webshop_url, gevonden):
    """Legt vast wat wij bij deze winkel zagen, ook als er niets was (dan komt
    hij niet elke ronde terug)."""
    site = (gevonden or {}).get("site")
    naam = (gevonden or {}).get("naam")
    _sql("""INSERT INTO bureau_winkels (webshop_url, bureau_site, bureau_naam) VALUES (%s, %s, %s)
            ON CONFLICT (webshop_url) DO UPDATE SET bureau_site = EXCLUDED.bureau_site,
                bureau_naam = EXCLUDED.bureau_naam, gekeken_op = now()""", (webshop_url, site, naam))
    if site:
        _sql("""INSERT INTO bureaus (site, naam, token) VALUES (%s, %s, %s)
                ON CONFLICT (site) DO NOTHING""", (site, naam, secrets.token_urlsafe(12)))


def nog_te_bekijken(limiet=PER_RONDE):
    """Winkels uit de index die wij nog niet op een bureau bekeken hebben.
    Afgemelde winkels niet: die willen niets meer van ons."""
    return [r["webshop_url"] for r in _sql(
        """SELECT DISTINCT u.webshop_url FROM categorie_uitkomsten u
           LEFT JOIN benadering b ON b.webshop_url = u.webshop_url
           WHERE NOT EXISTS (SELECT 1 FROM bureau_winkels w WHERE w.webshop_url = u.webshop_url)
             AND NOT coalesce(b.afgemeld, false)
           LIMIT %s""", (limiet,), alles=True) or []]


def ronde(haal=None, zoek_adres=None, limiet=PER_RONDE):
    """Een kleine ronde: winkels bekijken, en adressen zoeken voor bureaus die
    groot genoeg zijn. haal(url) geeft de html; zoek_adres(url) de uitkomst van
    de adresvinder. Beide in te vullen voor de test."""
    if haal is None:
        import requests
        import scan_engine

        def haal(url):
            if scan_engine.is_intern_adres(url):
                return None
            r = requests.get(url, headers=scan_engine.HEADERS, timeout=10, allow_redirects=True)
            return r.text if r.status_code < 400 else None
    if zoek_adres is None:
        import contactvinder
        zoek_adres = contactvinder.zoek_adres
    uit = {"bekeken": 0, "bureaus": 0, "adressen": 0}
    for url in nog_te_bekijken(limiet):
        try:
            gevonden = herken(haal(url), url)
        except Exception as e:
            print(f"Bureau zoeken mislukt voor {url}: {e}")
            gevonden = None
        onthoud(url, gevonden)
        uit["bekeken"] += 1
        uit["bureaus"] += 1 if gevonden else 0
    for b in _sql("""SELECT b.site FROM bureaus b WHERE b.email_gezocht_op IS NULL
                       AND (SELECT count(*) FROM bureau_winkels w WHERE w.bureau_site = b.site) >= %s
                     LIMIT %s""", (BUREAU_MIN, ADRESSEN_PER_RONDE), alles=True) or []:
        try:
            adres = (zoek_adres(b["site"]) or {}).get("adres")
        except Exception as e:
            print(f"Adres van bureau {b['site']} zoeken mislukt: {e}")
            adres = None
        _sql("UPDATE bureaus SET email = %s, email_gezocht_op = now() WHERE site = %s", (adres, b["site"]))
        uit["adressen"] += 1 if adres else 0
    return uit


def groepen(minimaal=None):
    """De bureaus met genoeg winkels in de index, grootste eerst."""
    return _sql("""SELECT b.*, count(w.webshop_url) AS winkels
                   FROM bureaus b JOIN bureau_winkels w ON w.bureau_site = b.site
                   GROUP BY b.site HAVING count(w.webshop_url) >= %s
                   ORDER BY (b.stand = 'nieuw') DESC, count(w.webshop_url) DESC""",
                (minimaal or BUREAU_MIN,), alles=True) or []


def bij_token(token):
    if not token:
        return None
    return _sql("SELECT * FROM bureaus WHERE token = %s", (token,))


def winkels_van(site):
    return [r["webshop_url"] for r in _sql(
        "SELECT webshop_url FROM bureau_winkels WHERE bureau_site = %s ORDER BY webshop_url",
        (site,), alles=True) or []]


def samenvatting(beelden):
    """Uit de klantbeelden van zijn winkels: hoeveel er in de index staan en
    hoeveel AI niet noemt. Winkels zonder meting tellen niet mee."""
    gemeten = [b for b in beelden if b]
    niet = [b for b in gemeten if not b.get("genoemd")]
    return {"winkels": len(gemeten), "niet_genoemd": len(niet),
            "rijen": sorted(gemeten, key=lambda b: (bool(b.get("genoemd")), -(b.get("positie") or 0)))}


def zet_stand(site, stand, met_de_hand=False):
    if stand not in ("nieuw", "gemaild", "overgeslagen", "afgemeld"):
        return None
    return _sql("""UPDATE bureaus SET stand = %s,
                       gemaild_op = CASE WHEN %s = 'gemaild' THEN now() ELSE gemaild_op END,
                       met_de_hand = met_de_hand OR %s
                   WHERE site = %s""", (stand, stand, met_de_hand, site))


def mag_automatisch():
    """Automatisch mailen pas na tien met de hand, en alleen met de schakelaar aan."""
    if os.environ.get("BUREAUMAIL_AUTO", "").strip() not in ("1", "ja", "aan", "true"):
        return 0
    stand = _sql("""SELECT count(*) FILTER (WHERE met_de_hand AND stand <> 'nieuw') AS hand,
                           count(*) FILTER (WHERE gemaild_op >= date_trunc('day', now())) AS vandaag
                    FROM bureaus""") or {}
    if int(stand.get("hand") or 0) < HANDMATIG_EERST:
        return 0
    return max(0, AUTO_PER_DAG - int(stand.get("vandaag") or 0))


def mail_tekst(naam, samen, link):
    """Onderwerp en alinea's van de mail aan een bureau. Engels, zoals al onze
    mails naar buiten. Alleen cijfers die op zijn pagina ook staan."""
    n, m = samen["winkels"], samen["niet_genoemd"]
    onderwerp = f"{n} of your clients are in the Krillo Index"
    alineas = [
        f"Hi {naam}," if naam and "." not in naam else "Hi,",
        f"Your name is in the footer of {n} webshops that are in the Krillo Index, our monthly ranking of "
        f"which stores ChatGPT and Gemini recommend when shoppers ask where to buy.",
        (f"{m} of them are not named by AI at all right now. " if m else
         "All of them are named, which is rare. ")
        + "Per store you can see the rank and who AI names instead on the page below.",
        "We pay agencies 20 percent of what their clients pay us, for 12 months. Your clients get a free check "
        "first, and with Fix we make the changes in their store, so there is no extra work for you.",
    ]
    return onderwerp, alineas
