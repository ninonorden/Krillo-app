"""De logboeken van Render lezen (stap 144 deel 2, 15 oktober 2026).

WAAROM. Op 15 oktober zag Nino pas 's middags in Render dat de site sinds 2
uur 's nachts elk uur omviel. De klantblik (stap 236) kijkt naar de site van
buiten; dit kijkt naar binnen: elke ochtend de foutregels van de laatste 24
uur uit Render, gegroepeerd (dezelfde fout met een ander adres of getal telt
als een), de vijf meest voorkomende in het ochtendbericht. Met een tekst die
Nino zo aan Claude kan geven; Claude zoekt de oorzaak en neemt de reparatie
mee in de volgende zip. Zelf code aanpassen doet dit niet: dat blijft
nakijken en testen.

NODIG: RENDER_API_KEY in Render (Account Settings, API Keys). RENDER_SERVICE_ID
zet Render zelf. Zonder sleutel doet dit niets en zegt het ochtendbericht dat.
"""
import os
import re
from datetime import datetime, timedelta, timezone

API = "https://api.render.com/v1"
# 16 oktober: "BEGRENZING" eruit. Dat is de rem die werkt (een sitemap van
# eleiko was groter dan 5 MB en werd netjes afgekapt), geen fout. Hij stond
# bovenaan de foutenlijst en verdrong echte fouten.
ZOEK = ("Traceback", "Error", "mislukt", "Out of memory", "Instance failed", "WORKER TIMEOUT")
PER_ZOEK = 100
_eigenaar = {}


def aan():
    return bool(os.environ.get("RENDER_API_KEY") and os.environ.get("RENDER_SERVICE_ID"))


def _get(pad, params=None, get=None):
    if get is None:
        import requests
        get = requests.get
    r = get(API + pad, params=params or {}, timeout=20,
            headers={"Authorization": f"Bearer {os.environ.get('RENDER_API_KEY', '')}", "Accept": "application/json"})
    if getattr(r, "status_code", 500) >= 300:
        raise RuntimeError(f"Render API {r.status_code}")
    return r.json()


def _eigenaar_van(dienst, get=None):
    if dienst not in _eigenaar:
        d = _get(f"/services/{dienst}", get=get)
        _eigenaar[dienst] = (d.get("service") or d).get("ownerId")
    return _eigenaar[dienst]


def patroon(regel):
    """Dezelfde fout met een ander adres, getal of id telt als een."""
    t = re.sub(r"https?://\S+", "<adres>", regel or "")
    t = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", t)
    t = re.sub(r"\d+([.,]\d+)?", "<n>", t)
    return re.sub(r"\s+", " ", t).strip()[:200]


def haal(uren=24, get=None, nu=None):
    """[bericht] van de laatste uren, alleen regels die op een fout lijken. None zonder sleutel."""
    if not aan():
        return None
    nu = nu or datetime.now(timezone.utc)
    dienst = os.environ["RENDER_SERVICE_ID"]
    eigenaar = _eigenaar_van(dienst, get=get)
    berichten, gezien = [], set()
    for zoek in ZOEK:
        d = _get("/logs", {"ownerId": eigenaar, "resource": dienst, "text": zoek, "limit": PER_ZOEK,
                           "direction": "backward", "startTime": (nu - timedelta(hours=uren)).isoformat(),
                           "endTime": nu.isoformat()}, get=get)
        for l in d.get("logs") or []:
            sleutel = l.get("id") or (l.get("timestamp"), l.get("message"))
            if sleutel in gezien:
                continue
            gezien.add(sleutel)
            berichten.append(l.get("message") or "")
    return berichten


def samenvatting(berichten, top=5):
    """[(patroon, keer, voorbeeld)] meeste eerst."""
    groepen = {}
    for b in berichten or []:
        p = patroon(b)
        if not p:
            continue
        g = groepen.setdefault(p, [0, b])
        g[0] += 1
    return sorted(((p, n, v[:300]) for p, (n, v) in groepen.items()), key=lambda x: -x[1])[:top]


def ochtendregel(get=None):
    """(regel, tekst_voor_claude) of (regel, None)."""
    if not aan():
        return ("Render-logboeken: niet gekoppeld. Zet RENDER_API_KEY in Render (Account Settings, API Keys) "
                "en Claude leest elke ochtend de fouten mee", None)
    try:
        s = samenvatting(haal(get=get))
    except Exception as e:
        return (f"Render-logboeken lezen mislukt: {e}", None)
    if not s:
        return ("Render-logboeken: geen foutregels in 24 uur", None)
    totaal = sum(n for _, n, _ in s)
    # Met " | " en niet met regeleindes: het ochtendbericht is HTML en voegt die samen.
    tekst = "Fouten uit de Render-logboeken van de laatste 24 uur, meeste eerst: " + " | ".join(
        f"{n} keer: {v}" for _, n, v in s)
    return (f"Render-logboeken: {totaal} foutregels in 24 uur, {len(s)} soorten. Geef de tekst hieronder aan "
            "Claude", tekst)
