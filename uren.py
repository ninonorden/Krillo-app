"""Hoeveel werk Krillo deze maand voor je deed (16 oktober 2026).

WAAROM. Fix kost 100 euro per maand meer dan Watch. Dat is alleen het geld
waard als de klant ziet hoeveel werk hem uit handen genomen wordt. Nino keurde
het idee goed: "About N hours of work this month, done for you". Het getal komt
uit wat er ECHT gebeurde (de tabel wijzigingen en de pagina's van de
contentmotor), met per soort werk een vaste, behoudende schatting van wat het
een winkelier zelf kost. Geen verzonnen totaal: geen werk, geen uren.

MINUTEN PER SOORT (zelf doen, ervaren winkelier, afgerond naar beneden):
- alt-tekst bij een foto: 3 minuten
- producttekst herschrijven: 20 minuten
- vragenpagina (FAQ) schrijven en plaatsen: 60 minuten
- llms.txt maken of bijwerken: 30 minuten
- koopgids schrijven (contentmotor): 90 minuten, plaatsen: 10 minuten
"""
from datetime import datetime, timezone

import db

MINUTEN = {"alt": 3, "tekst": 20, "faq": 60, "llms": 30, "gids": 10}
GIDS_SCHRIJVEN = 90


def soort_van(taak_id):
    delen = (taak_id or "").split(":")
    return delen[1] if len(delen) > 1 else delen[0]


def _wijzigingen(webshop_url, begin):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT taak_id FROM wijzigingen WHERE webshop_url = %s AND gedaan_op >= %s",
                            (webshop_url, begin))
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Uren, wijzigingen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def deze_maand(webshop_url, nu=None, wijzigingen=None, gidsen=None):
    """{"minuten", "uren" (afgerond op halve uren), "per_soort": {soort: aantal}}."""
    nu = nu or datetime.now(timezone.utc)
    begin = nu.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if wijzigingen is None:
        wijzigingen = _wijzigingen(webshop_url, begin)
    if gidsen is None:
        import contentmotor
        gidsen = contentmotor.deze_maand(webshop_url, nu)
    per, minuten = {}, 0
    for w in wijzigingen:
        s = soort_van(w.get("taak_id"))
        if s in MINUTEN:
            per[s] = per.get(s, 0) + 1
            minuten += MINUTEN[s]
    for _ in gidsen:
        per["gids_geschreven"] = per.get("gids_geschreven", 0) + 1
        minuten += GIDS_SCHRIJVEN
    return {"minuten": minuten, "uren": round(minuten / 30) / 2, "per_soort": per}


def zin(u, taal="en"):
    """De zin voor het dashboard en de maandmail, of None zonder werk."""
    if not u or u["minuten"] < 15:
        return None
    if taal == "nl":
        return f"Deze maand deed Krillo ongeveer {u['uren']:g} uur werk voor je winkel."
    return f"This month Krillo did about {u['uren']:g} hours of work for your store."
