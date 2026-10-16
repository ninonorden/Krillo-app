"""Zoekmachine en AI naast elkaar, per koopvraag (stap 240, 16 oktober 2026).

WAAROM. Goedgekeurd 1 oktober. Een winkelier denkt in Google: "ik sta toch
bovenaan?". Per koopvraag laten we nu ook zijn plek in de zoekresultaten zien,
naast wat ChatGPT en Gemini antwoorden. Twee nuttige uitkomsten:
- hoog in zoeken maar AI noemt je niet: de pagina is er, maar AI vindt hem
  niet goed genoeg om aan te raden (tekst, productgegevens, vermeldingen);
- niet in zoeken en ook niet in AI: eerst een pagina die de vraag beantwoordt.

EERLIJK. We gebruiken de zoekdienst die we al hebben (bronnen.zoek, Brave of
Google, staat in ZOEK_AANBIEDER), en noemen die bij naam. Brave is niet Google:
de plek kan anders zijn. Eens per maand, hoogstens MAX_VRAGEN vragen per
betalende klant, ongeveer een halve cent per vraag.
"""
import json
import re
from datetime import datetime, timezone

import db

SLEUTEL = "zoekplek:"
MAX_VRAGEN = 15


def _domein(url):
    h = re.sub(r"^[a-z]+://", "", (url or "").lower()).split("/")[0]
    return h[4:] if h.startswith("www.") else h


def plek_in(resultaten, webshop_url):
    """De positie (1, 2, ...) van de eerste uitkomst op het domein van de winkel, of None."""
    eigen = _domein(webshop_url)
    for i, r in enumerate(resultaten or [], start=1):
        d = _domein(r.get("url"))
        if d == eigen or d.endswith("." + eigen):
            return i
    return None


def lees(webshop_url):
    try:
        return json.loads(db.get_instelling(SLEUTEL + (webshop_url or "")[:180]) or "null")
    except (TypeError, ValueError):
        return None


def ronde(webshop_url, vragen, land="nl", taal="nl", zoek=None, nu=None):
    """Meet de vragen als het deze maand nog niet gebeurde. Geeft het opgeslagen beeld."""
    nu = nu or datetime.now(timezone.utc)
    maand = nu.strftime("%Y-%m")
    oud = lees(webshop_url)
    if oud and oud.get("maand") == maand:
        return oud
    if zoek is None:
        import bronnen
        if not bronnen.beschikbaar():
            return oud
        zoek = bronnen.zoek
    import bronnen as _b
    plekken = {}
    for vraag in (vragen or [])[:MAX_VRAGEN]:
        plekken[vraag] = plek_in(zoek(vraag, webshop_url=webshop_url, land=land, taal=taal), webshop_url)
    beeld = {"maand": maand, "dienst": getattr(_b, "ZOEK_AANBIEDER", "search").capitalize(), "plekken": plekken,
             "van": getattr(_b, "MAX_RESULTATEN", 10)}
    db.zet_instelling(SLEUTEL + webshop_url[:180], json.dumps(beeld, ensure_ascii=False))
    return beeld


def label(beeld, vraag, taal="en"):
    """De korte tekst bij een vraag, of None als die vraag niet gemeten is."""
    if not beeld or vraag not in (beeld.get("plekken") or {}):
        return None
    p = beeld["plekken"][vraag]
    dienst = beeld.get("dienst") or "Search"
    if p:
        return f"{dienst} #{p}"
    return (f"{dienst}: niet in de top {beeld.get('van') or 10}" if taal == "nl"
            else f"{dienst}: not in the top {beeld.get('van') or 10}")
