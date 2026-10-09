"""De aanmeldroute /start (9 oktober 2026, stap 352).

Nino, na de onboarding van Peec: "bij hun moet je eerst inloggen, dat geeft
veel meer vertrouwen, en een gevoel dat ze moeten betalen om echt door te
gaan." De cijfers zeiden hetzelfde: van ongeveer 59 mensen die uit de koude
mail op "start" klikten, vulde niemand de kassa in. Een kassa als eerste
scherm is een te grote stap voor iemand die Krillo vijf minuten kent.

Daarom eerst een paar kleine stappen waarin de winkelier zelf iets doet
(mailadres, zijn winkel, zijn categorie, de vragen die hij wil winnen), dan
een stukje van zijn eigen uitslag, en pas daarna het pakket en de betaling.
Wat hij invult bewaren we meteen; na de betaling staat het in zijn dashboard,
zodat het werk niet verloren gaat.

Kost niets aan AI: alles komt uit de index die er al is. Een winkel die nog
niet in de index staat krijgt eerlijk te horen dat we hem meten zodra hij
begint.
"""
import json
import secrets
from datetime import datetime, timezone

import categorieen
import db
import scan_engine

SLEUTEL = "aanmelding:"          # aanmelding:<token> -> de stappen tot nu toe
PER_WINKEL = "aanmelding_url:"   # aanmelding_url:<winkel> -> token (voor na de betaling)
MAX_DOELEN = 3                   # zelfde als "Pick up to three questions to win" in het dashboard


def _lees(token):
    if not token or len(token) > 64:
        return None
    try:
        return json.loads(db.get_instelling(SLEUTEL + token) or "null")
    except (TypeError, ValueError):
        return None


def _schrijf(token, gegevens):
    gegevens["bijgewerkt"] = datetime.now(timezone.utc).isoformat()
    db.zet_instelling(SLEUTEL + token, json.dumps(gegevens))


def begin(email):
    """Stap 1: een nieuwe aanmelding met alleen het mailadres. Geeft het token."""
    token = secrets.token_urlsafe(18)
    _schrijf(token, {"email": email.strip().lower(), "begonnen": datetime.now(timezone.utc).isoformat()})
    return token


def lees(token):
    return _lees(token)


def zet(token, **velden):
    """Bewaar wat de winkelier in een stap koos. Alleen bekende velden."""
    g = _lees(token)
    if g is None:
        return None
    for k, v in velden.items():
        if k in ("url", "naam", "categorie", "land", "doelen", "plan", "voor", "stap") and v is not None:
            g[k] = v
    if g.get("url"):
        db.zet_instelling(PER_WINKEL + scan_engine.normalize_url(g["url"]), token)
    _schrijf(token, g)
    return g


def categorie_keuzes():
    """[(slug, Engelse naam)], op naam gesorteerd, zonder wat we niet meten."""
    return sorted(((s, categorieen.naam_en(s)) for s in categorieen.GELDIG
                   if s not in categorieen.NIET_MEETBAAR), key=lambda kv: kv[1].lower())


def profiel(url):
    """Wat we al weten van deze winkel: naam, categorie en land uit de index.

    {"url", "naam", "categorie", "land", "in_index"}. Staat hij er niet in,
    dan zijn categorie en land leeg en kiest de winkelier ze zelf."""
    url = scan_engine.normalize_url(url)
    naam = url.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
    uit = {"url": url, "naam": naam, "categorie": None, "land": None, "in_index": False}
    try:
        import klantbeeld
        kaal = url.replace("://www.", "://")
        for kandidaat in dict.fromkeys([url, kaal, kaal.replace("://", "://www.")]):
            beeld = klantbeeld.bouw(kandidaat, max_vragen=0)
            if beeld and beeld.get("categorie"):
                uit.update(categorie=beeld["categorie"], land=beeld.get("land") or "nl",
                           in_index=bool(beeld.get("land")), naam=beeld.get("naam") or naam)
                break
    except Exception as e:
        print(f"Profiel voor de aanmelding ophalen mislukt voor {url}: {e}")
    return uit


def vragen(categorie, aantal=12):
    """De koopvragen van de categorie zoals ze in de index staan."""
    if categorie not in categorieen.GELDIG:
        return []
    return [r["vraag"] for r in db.categorie_vragen(categorie)][:aantal]


def pas_toe(webshop_url):
    """Na de betaling: zet wat de winkelier in /start koos in zijn dashboard.

    Categorie en land (als hij die zelf koos of bevestigde) en de vragen die
    hij wil winnen. Nooit een fout naar de betaling: lukt iets niet, dan staat
    het in de log en kiest hij het in het dashboard opnieuw."""
    url = scan_engine.normalize_url(webshop_url or "")
    token = db.get_instelling(PER_WINKEL + url) if url else None
    g = _lees(token) if token else None
    if not g:
        return False
    try:
        slug, land = g.get("categorie"), (g.get("land") or "nl")
        if slug in categorieen.GELDIG and slug not in categorieen.NIET_MEETBAAR and land in ("nl", "be"):
            db.zet_klant_op_lijst(url, land=land)
            db.zet_categorie(url, slug)
            db.zet_land(url, land)
        for vraag in (g.get("doelen") or [])[:MAX_DOELEN]:
            db.zet_gekozen_vraag(url, vraag, True)
        g["toegepast"] = datetime.now(timezone.utc).isoformat()
        _schrijf(token, g)
        return True
    except Exception as e:
        print(f"Aanmelding toepassen mislukt voor {url}: {e}")
        return False
