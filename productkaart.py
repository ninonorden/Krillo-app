"""Productkaart: welke producten van de winkel AI noemt, en bij welke vraag (2 oktober 2026).

Goedgekeurd door Nino (voorstel 4). Profound en Visibly AI hebben dit; voor een
kleine winkel is het de snelste weg naar "welke productpagina herschrijf ik".

HOE. De wekelijkse snelmeting (snelmeting.py) stelt elke week de vijf
belangrijkste koopvragen aan ChatGPT en Gemini. In die antwoorden zoeken wij nu
ook naar de PRODUCTEN van de winkel. De productlijst komt uit de sitemap van de
winkel (hoogstens MAX_PRODUCTEN), een keer per week opgehaald. Geen extra
AI-aanroep: het kost niets bovenop de snelmeting.

EERLIJK. Dit zijn vijf vragen per week, geen duizenden. Een product dat er niet
in staat is "niet genoemd in deze vijf vragen", niet "onzichtbaar voor AI". Zo
staat het ook op het dashboard. AI noemt vaak een winkel zonder product; dan is
de kaart leeg en zeggen wij dat.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, unquote

import db

MAX_PRODUCTEN = 200
VERS_DAGEN = 7
STOP = {"with", "voor", "from", "and", "the", "een", "met", "van", "set", "pack", "stuks", "size", "kleur",
        "color", "maat", "black", "white", "zwart", "wit", "nieuw", "new", "product", "products"}


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
    _sql("""CREATE TABLE IF NOT EXISTS productlijsten (
                webshop_url TEXT PRIMARY KEY,
                op TIMESTAMPTZ NOT NULL,
                producten JSONB NOT NULL)""")


def _plat(tekst):
    tekst = unicodedata.normalize("NFKD", str(tekst or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", tekst).split())


def naam_uit_url(url):
    """'.../products/houten-garage-rood' -> 'Houten garage rood'."""
    stuk = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    stuk = re.sub(r"\.(html?|php)$", "", stuk)
    stuk = re.sub(r"[-_]+", " ", stuk).strip()
    stuk = re.sub(r"\s\d{3,}$", "", stuk)   # een los artikelnummer aan het eind weg
    return stuk[:1].upper() + stuk[1:] if stuk else ""


def _locs(xml):
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "", re.I)


def uit_sitemap(webshop_url, haal):
    """Productadressen uit de sitemap. haal(url) -> tekst of None."""
    import paginacheck
    basis = webshop_url.rstrip("/")
    xml = haal(basis + "/sitemap.xml") or ""
    locs = _locs(xml)
    if "<sitemapindex" in xml.lower():
        kinderen = [l for l in locs if "product" in l.lower()] or locs[:1]
        locs = []
        for kind in kinderen[:2]:
            locs += _locs(haal(kind) or "")
    uit, gezien = [], set()
    for l in locs:
        if paginacheck.is_productpagina(l) and l not in gezien:
            gezien.add(l)
            naam = naam_uit_url(l)
            if naam:
                uit.append({"naam": naam, "url": l})
        if len(uit) >= MAX_PRODUCTEN:
            break
    return uit


def producten_van(webshop_url, haal=None, nu=None):
    """De productlijst van de winkel, hoogstens een keer per week opgehaald."""
    maak_tabel()
    nu = nu or datetime.now(timezone.utc)
    rij = _sql("SELECT op, producten FROM productlijsten WHERE webshop_url = %s", (webshop_url,))
    if rij and rij["op"] > nu - timedelta(days=VERS_DAGEN):
        p = rij["producten"]
        return json.loads(p) if isinstance(p, str) else p
    if haal is None:
        import scan_engine

        def haal(u):
            r = scan_engine.fetch(u, pogingen=1)
            return r.text if r is not None and r.status_code < 400 else None
    try:
        lijst = uit_sitemap(webshop_url, haal)
    except Exception as e:
        print(f"Productlijst ophalen mislukt voor {webshop_url}: {e}")
        lijst = []
    _sql("""INSERT INTO productlijsten (webshop_url, op, producten) VALUES (%s, %s, %s)
            ON CONFLICT (webshop_url) DO UPDATE SET op = EXCLUDED.op, producten = EXCLUDED.producten""",
         (webshop_url, nu, json.dumps(lijst)))
    return lijst


def _woorden(naam):
    return [w for w in _plat(naam).split() if len(w) >= 4 and not w.isdigit() and w not in STOP]


def genoemd_in(producten, antwoord):
    """Welke producten in een AI-antwoord staan. Een product telt als:
    - zijn adres in het antwoord staat, of
    - zijn hele naam erin staat, of
    - alle kenmerkende woorden van zijn naam (minstens twee) in een zin staan."""
    if not antwoord:
        return []
    plat = _plat(antwoord)
    zinnen = [_plat(z) for z in re.split(r"(?<=[.!?\n])\s+", antwoord)]
    uit = []
    for p in producten or []:
        naam = p.get("naam") or ""
        pad = urlparse(p.get("url") or "").path.rstrip("/")
        woorden = _woorden(naam)
        if (pad and len(pad) > 3 and pad.lower() in (antwoord or "").lower()) \
                or (len(_plat(naam).split()) >= 2 and f" {_plat(naam)} " in f" {plat} ") \
                or (len(woorden) >= 2 and any(all(f" {w} " in f" {z} " for w in woorden) for z in zinnen)):
            uit.append(naam)
    return uit


def kaart(webshop_url):
    """Voor het dashboard: de laatste snelmeting, per product bij welke vragen.

    {"gemeten": bool, "vragen": n, "genoemd": [{"naam", "url", "keer": [{"vraag", "assistent"}]}],
     "niet": [{"naam", "url"}] (hoogstens 8), "producten": n}"""
    import snelmeting
    snelmeting.maak_tabel()
    rijen = _sql("""SELECT vraag, assistent, producten FROM snelmetingen
                     WHERE webshop_url = %s
                       AND ronde_op = (SELECT max(ronde_op) FROM snelmetingen WHERE webshop_url = %s)""",
                 (webshop_url, webshop_url), alles=True) or []
    maak_tabel()
    rij = _sql("SELECT producten FROM productlijsten WHERE webshop_url = %s", (webshop_url,))
    lijst = (json.loads(rij["producten"]) if isinstance(rij["producten"], str) else rij["producten"]) if rij else []
    if not rijen:
        return {"gemeten": False, "vragen": 0, "genoemd": [], "niet": [], "producten": len(lijst)}
    per = {}
    for r in rijen:
        namen = r.get("producten") or []
        if isinstance(namen, str):
            namen = json.loads(namen)
        for n in namen:
            per.setdefault(n, []).append({"vraag": r["vraag"], "assistent": r["assistent"]})
    url_van = {p["naam"]: p["url"] for p in lijst}
    genoemd = [{"naam": n, "url": url_van.get(n), "keer": k} for n, k in
               sorted(per.items(), key=lambda x: -len(x[1]))]
    niet = [p for p in lijst if p["naam"] not in per][:8]
    return {"gemeten": True, "vragen": len({r["vraag"] for r in rijen}), "genoemd": genoemd, "niet": niet,
            "producten": len(lijst)}
