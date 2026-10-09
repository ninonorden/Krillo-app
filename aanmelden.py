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
from datetime import datetime, timedelta, timezone

import categorieen
import db
import scan_engine

SLEUTEL = "aanmelding:"          # aanmelding:<token> -> de stappen tot nu toe
PER_WINKEL = "aanmelding_url:"   # aanmelding_url:<winkel> -> token (voor na de betaling)
MAX_DOELEN = 3                   # zelfde als "Pick up to three questions to win" in het dashboard
MAX_KLANTWINKELS = 25            # het pakket Brands and agencies: tot 25 winkels
HERINNER_NA_UUR = 20             # een herinnering de volgende dag, niet midden in de nacht erna


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
        if k in ("url", "naam", "categorie", "land", "doelen", "plan", "voor", "stap", "periode",
                 "bureau", "klant_winkels") and v is not None:
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
        # Bureaus (stap 354): elke klantwinkel krijgt een eigen dashboard op
        # hetzelfde mailadres. Na het inloggen kiest het bureau welke winkel.
        if g.get("voor") == "klanten":
            for w in (g.get("klant_winkels") or [])[:MAX_KLANTWINKELS]:
                w = scan_engine.normalize_url(w)
                if w and w != url and db.get_or_create_klant(w, g.get("email")):
                    db.zet_klant_pakket(w, "merken")
        g["toegepast"] = datetime.now(timezone.utc).isoformat()
        _schrijf(token, g)
        return True
    except Exception as e:
        print(f"Aanmelding toepassen mislukt voor {url}: {e}")
        return False


def _alle():
    """[(token, gegevens)] van alle aanmeldingen."""
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT sleutel, waarde FROM instellingen WHERE sleutel LIKE %s", (SLEUTEL + "%",))
                uit = []
                for sleutel, waarde in cur.fetchall():
                    try:
                        uit.append((sleutel[len(SLEUTEL):], json.loads(waarde)))
                    except (TypeError, ValueError):
                        pass
                return uit
    finally:
        conn.close()


def _tijd(t):
    try:
        return datetime.fromisoformat(t)
    except (TypeError, ValueError):
        return None


STAPNAMEN = [("account", "account gemaakt"), ("profiel", "winkel ingevuld"), ("vragen", "profiel bevestigd"),
             ("voorproef", "vragen gekozen"), ("betalen", "naar de betaling")]


def telling(uren=24, nu=None):
    """Voor het ochtendbericht (stap 354): hoeveel mensen begonnen aan /start en
    tot welke stap ze kwamen. {"begonnen": n, "per_stap": [(naam, n)], "betaald": n}."""
    nu = nu or datetime.now(timezone.utc)
    rij = [g for _, g in _alle() if (_tijd(g.get("begonnen")) or nu) > nu - timedelta(hours=uren)]
    volgorde = [k for k, _ in STAPNAMEN]

    def hoever(g):
        return volgorde.index(g.get("stap")) if g.get("stap") in volgorde else 0
    per = [(naam, sum(1 for g in rij if hoever(g) >= i)) for i, (_, naam) in enumerate(STAPNAMEN)]
    return {"begonnen": len(rij), "per_stap": per, "betaald": sum(1 for g in rij if g.get("toegepast"))}


def te_herinneren(nu=None):
    """Wie /start begon, niet betaalde, en nog geen herinnering kreeg.

    Een keer, en pas na HERINNER_NA_UUR uur: wie twijfelt krijgt een dag. Niet
    als hetzelfde adres intussen klant is (dan betaalde hij via een andere weg)."""
    nu = nu or datetime.now(timezone.utc)
    uit = []
    for token, g in _alle():
        begonnen = _tijd(g.get("begonnen"))
        if not begonnen or g.get("toegepast") or g.get("herinnerd") or not g.get("email"):
            continue
        if not (nu - timedelta(days=7) < begonnen < nu - timedelta(hours=HERINNER_NA_UUR)):
            continue
        if db.klant_bij_email(g["email"]):
            continue
        uit.append((token, g))
    return uit


def markeer_herinnerd(token):
    g = _lees(token)
    if g is not None:
        g["herinnerd"] = datetime.now(timezone.utc).isoformat()
        _schrijf(token, g)
