"""De warme lijst bovenaan het ochtendbericht (16 oktober 2026).

WAAROM. Nino: "we moeten nu echt klanten krijgen". Het ochtendbericht telt
alles, maar zegt niet bij welke vijf winkels vandaag de beste kans ligt. Dit
zijn hoogstens vijf winkels die de laatste 48 uur zelf iets deden, de warmste
eerst:
1. antwoordden op een mail (niet afmelden, geen automatisch antwoord);
2. begonnen op /start en betaalden niet;
3. keken als echt mens naar de prijzen na hun uitslag;
4. openden hun uitslag als echt mens (geen mailbeveiliging, zie mens_op).
Bestaande klanten staan er niet in. Alleen tellingen en adressen van winkels,
geen namen van personen.
"""
from datetime import datetime, timedelta, timezone

import db

MAX = 5
UREN = 48
GEWICHT = {"antwoord": 4, "start": 3, "prijzen": 2, "uitslag": 1}


def _sql(opdracht, waarden):
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(opdracht, waarden)
                return cur.fetchall()
    except Exception as e:
        print(f"Warme lijst ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def _kaal(url):
    u = (url or "").lower().replace("https://", "").replace("http://", "")
    return (u[4:] if u.startswith("www.") else u).rstrip("/")


def signalen(nu=None, start=None):
    """[(winkel, soort, wanneer, extra)] van de laatste UREN uur."""
    nu = nu or datetime.now(timezone.utc)
    sinds = nu - timedelta(hours=UREN)
    uit = []
    for url, op, stand in _sql("""SELECT webshop_url, ontvangen_op, stand FROM antwoorden
                                   WHERE ontvangen_op >= %s AND webshop_url IS NOT NULL
                                     AND coalesce(soort, '') NOT IN ('afmelden', 'helpdesk', 'automatisch')""",
                               (sinds,)):
        uit.append((url, "antwoord", op, "wacht op jou" if stand == "nieuw" else "afgehandeld"))
    for url, mens, prijzen in _sql("""SELECT webshop_url, mens_op, doorgeklikt_op FROM benadering
                                       WHERE mens_op >= %s AND NOT coalesce(afgemeld, FALSE)""", (sinds,)):
        if prijzen and prijzen >= sinds:
            uit.append((url, "prijzen", prijzen, None))
        else:
            uit.append((url, "uitslag", mens, None))
    if start is None:
        try:
            import aanmelden
            start = aanmelden._alle()
        except Exception:
            start = []
    try:
        import aanmelden
        namen = dict(aanmelden.STAPNAMEN)
        for _, g in start:
            b = aanmelden._tijd(g.get("begonnen"))
            if b and b >= sinds and not g.get("toegepast") and g.get("url"):
                uit.append((g["url"], "start", b, namen.get(g.get("stap"), "begonnen")))
    except Exception as e:
        print(f"Warme lijst, /start mislukt: {e}")
    return uit


ZIN = {"antwoord": "antwoordde op de mail", "start": "begon op /start, kwam tot: {extra}",
       "prijzen": "opende de uitslag en keek naar de prijzen", "uitslag": "opende de uitslag (echt mens)"}
WAAR = {"antwoord": "/admin/antwoorden", "start": "/admin/verkoop", "prijzen": "/admin/verkoop",
        "uitslag": "/admin/verkoop"}


def lijst(nu=None, signalen_lijst=None, is_klant=None):
    """[{"winkel", "soort", "zin", "waar"}], warmste eerst, hoogstens MAX, zonder klanten."""
    s = signalen(nu) if signalen_lijst is None else signalen_lijst
    is_klant = is_klant or (lambda u: bool(db.klant_bij_url(u)))
    beste = {}
    for url, soort, op, extra in s:
        k = _kaal(url)
        oud = beste.get(k)
        if not oud or (GEWICHT[soort], op) > (GEWICHT[oud[1]], oud[2]):
            beste[k] = (url, soort, op, extra)
    rijen = sorted(beste.values(), key=lambda r: (-GEWICHT[r[1]], -(r[2].timestamp() if r[2] else 0)))
    uit = []
    for url, soort, op, extra in rijen:
        try:
            if is_klant(url):
                continue
        except Exception:
            pass
        zin = ZIN[soort].format(extra=extra or "")
        if soort == "antwoord" and extra:
            zin += f" ({extra})"
        uit.append({"winkel": _kaal(url), "soort": soort, "zin": zin, "waar": WAAR[soort]})
        if len(uit) >= MAX:
            break
    return uit


def ochtendregel(rijen):
    """Een regel voor bovenaan, of None zonder warme winkels."""
    if not rijen:
        return None
    return ("Warme lijst, de beste kansen van vandaag (48 uur): "
            + "; ".join(f"{r['winkel']} {r['zin']}" for r in rijen)
            + ". Pak ze vandaag op: antwoorden op /admin/antwoorden, opvolging op /admin/verkoop")


def stel_opvolging_voor(rijen):
    """Een voorstel (akkoord met een tik in het ochtendbericht) om ook echte
    mensen op te volgen die alleen hun uitslag openden. Alleen als die er
    zijn en de schakelaar nog uit staat. Een nee houdt 30 dagen (voorstellen.py)."""
    n = sum(1 for r in rijen or [] if r["soort"] == "uitslag")
    if not n:
        return None
    try:
        import verkoopagent as va
        if va.ook_mens():
            return None
        import voorstellen
        return voorstellen.stel_voor(
            "warme lijst", "actie", "Volg ook echte mensen op die hun uitslag openden",
            waarom=(f"{n} winkel(s) op de warme lijst openden hun uitslag als echt mens maar klikten niet naar "
                    "de prijzen. Die krijgen nu geen opvolging. Met akkoord maakt de verkoopagent ook voor hen "
                    "een concept; jij keurt elk concept nog zelf goed op /admin/verkoop."),
            actie="verkoop_ook_mens")
    except Exception as e:
        print(f"Warme lijst, voorstel mislukt: {e}")
        return None
