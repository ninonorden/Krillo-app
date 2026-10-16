"""Welke zoekopdrachten AI zelf doet voordat het antwoordt (stap 191, 16 oktober 2026).

WAAROM. Goedgekeurd door Nino op 15 oktober. Een assistent met zoekfunctie
zoekt eerst zelf op internet en antwoordt daarna. Die zoekopdrachten zeggen
precies welke tekst er op welke pagina moet staan om in het antwoord te komen.
Peec laat ze zien; wij doen er een stap meer: bij elke zoekopdracht de pagina
van de winkel die er het best bij past, of "geen pagina" (dan schrijft Fix er
een, zie contentmotor.py).

HOE. Gemini met Google Search (grounding) geeft in het antwoord letterlijk mee
welke zoekopdrachten het deed (groundingMetadata.webSearchQueries) en welke
pagina's het las (groundingChunks). We stellen dezelfde koopvraag die de winkel
verloor. Alleen voor Fix-klanten, eens per maand, hoogstens MAX_VRAGEN verloren
vragen: Google rekent per vraag met zoeken ongeveer 3,5 cent, dus hoogstens
ongeveer 18 cent per klant per maand.

EERLIJK. Dit zijn de zoekopdrachten van Gemini met Google Search. ChatGPT zoekt
op zijn eigen manier; dat staat er ook zo bij. Niets geraden: geeft Gemini geen
zoekopdrachten terug, dan tonen we niets voor die vraag.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import db

SLEUTEL = "fanout:"
MAX_VRAGEN = 5
PRIJS_PER_VRAAG_EURO = float(os.environ.get("FANOUT_PRIJS_PER_VRAAG", "0.035"))
MODEL = os.environ.get("FANOUT_MODEL_GOOGLE", os.environ.get("MEET_MODEL_GOOGLE", "gemini-3.7-flash"))

# Woorden die niets zeggen over welke pagina past.
_STOP = set("""de het een en of van voor met in op te bij om aan uit naar over is zijn wat welke waar
hoe beste goedkope goede kopen koop online winkel webshop shop store buy best cheap good the a an and or
for with in on to of at what which where how is are nl be 2025 2026 review reviews""".split())


def _woorden(tekst):
    return {w for w in re.findall(r"[a-z0-9À-ɏ]+", (tekst or "").lower())
            if len(w) > 2 and w not in _STOP}


def beste_pagina(zoekopdracht, adressen):
    """Het adres van de winkel waarvan het pad de meeste woorden met de
    zoekopdracht deelt (minstens een), of None. Op het pad, niet op de inhoud:
    dat is goedkoop en voor een productpagina zegt het pad het meeste."""
    vraag = _woorden(zoekopdracht)
    beste, score = None, 0
    for u in adressen or []:
        pad = urlparse(u).path.replace("-", " ").replace("_", " ").replace("/", " ")
        s = len(vraag & _woorden(pad))
        if s > score or (s == score and s and beste and len(u) < len(beste)):
            beste, score = u, s
    return beste if score else None


def vraag_gemini(vraag, model=None):
    """(zoekopdrachten, bronnen [{"url", "titel"}]) van een Gemini-antwoord met Google Search."""
    import requests
    import kosten
    model = model or MODEL
    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        raise RuntimeError(rem["reden"])
    gestart = time.monotonic()
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GOOGLE_API_KEY"], "Content-Type": "application/json"},
        json={"contents": [{"role": "user", "parts": [{"text": vraag}]}],
              "tools": [{"google_search": {}}],
              "generationConfig": {"maxOutputTokens": 2000}},
        timeout=90)
    resp.raise_for_status()
    data = resp.json()
    kandidaat = (data.get("candidates") or [{}])[0]
    meta = kandidaat.get("groundingMetadata") or {}
    zoek = [q.strip() for q in meta.get("webSearchQueries") or [] if (q or "").strip()]
    bronnen = []
    for c in meta.get("groundingChunks") or []:
        web = c.get("web") or {}
        if web.get("uri"):
            # De uri is een doorverwijzing van Google (vertexaisearch...); de
            # titel is bij Google Search de domeinnaam van de bron. Die tonen we.
            bronnen.append({"url": web["uri"], "titel": (web.get("title") or "")[:120],
                            "domein": _domein(web.get("title") if "." in (web.get("title") or "")
                                              and " " not in (web.get("title") or "") else web["uri"])})
    gebruik = data.get("usageMetadata") or {}
    try:
        duur = int((time.monotonic() - gestart) * 1000)
        kosten.registreer_aanroep("google", model, gebruik.get("promptTokenCount", 0),
                                  gebruik.get("candidatesTokenCount", 0), soort="fanout", duur_ms=duur)
        kosten.registreer_vaste_kosten(soort="fanout-zoeken", provider="google", bedrag=PRIJS_PER_VRAAG_EURO)
    except Exception:
        pass
    return zoek, bronnen


def lees(webshop_url):
    try:
        return json.loads(db.get_instelling(SLEUTEL + (webshop_url or "")[:180]) or "null")
    except (TypeError, ValueError):
        return None


def _adressen(webshop_url):
    """De pagina's die we van de winkel kennen: de productpagina's uit de
    productronde (paginacheck), plus de gidsen die Fix schreef."""
    uit = []
    try:
        import paginacheck
        uit += list((paginacheck._lees_producten(webshop_url).get("paginas") or {}).keys())
    except Exception:
        pass
    return uit


def ronde(webshop_url, vragen, vraag_aan=None, adressen=None, nu=None):
    """Eens per maand: de zoekopdrachten van AI voor hoogstens MAX_VRAGEN
    verloren vragen. Geeft het opgeslagen beeld."""
    nu = nu or datetime.now(timezone.utc)
    maand = nu.strftime("%Y-%m")
    oud = lees(webshop_url)
    if oud and oud.get("maand") == maand:
        return oud
    if vraag_aan is None:
        if not os.environ.get("GOOGLE_API_KEY"):
            return oud
        vraag_aan = vraag_gemini
    adressen = _adressen(webshop_url) if adressen is None else adressen
    per_vraag = {}
    for vraag in (vragen or [])[:MAX_VRAGEN]:
        try:
            zoek, bronnen = vraag_aan(vraag)
        except Exception as e:
            print(f"Fan-out mislukt voor {webshop_url}: {str(e)[:150]}")
            continue
        if not zoek:
            continue
        eigen = _domein(webshop_url)
        per_vraag[vraag] = {
            "zoekopdrachten": [{"tekst": z, "pagina": beste_pagina(z, adressen)} for z in zoek[:6]],
            "bronnen": [b for b in bronnen if (b.get("domein") or _domein(b["url"])) != eigen][:5],
            "eigen_bron": any((b.get("domein") or _domein(b["url"])) == eigen for b in bronnen),
        }
    beeld = {"maand": maand, "op": nu.isoformat(), "assistent": "Gemini with Google Search", "vragen": per_vraag}
    db.zet_instelling(SLEUTEL + webshop_url[:180], json.dumps(beeld, ensure_ascii=False))
    return beeld


def _domein(url):
    h = re.sub(r"^[a-z]+://", "", (url or "").lower()).split("/")[0]
    return h[4:] if h.startswith("www.") else h


def voor_vraag(beeld, vraag):
    """Het stuk voor een vraag op het dashboard, of None."""
    if not beeld:
        return None
    return (beeld.get("vragen") or {}).get(vraag)
