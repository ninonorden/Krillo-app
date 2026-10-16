"""Op koers naar de eerste klanten: een regel bovenaan het ochtendbericht (16 oktober 2026).

WAAROM. Het doel van Nino: 2 Watch en 2 Fix voor 31 oktober. Het
ochtendbericht telt veel losse dingen, maar zegt niet in een regel of we op
koers liggen. Deze regel zet de trechter van de laatste 7 dagen naast het doel:
echte mensen op hun uitslag, opvolgingen, antwoorden, proeven, en wie nu
betaalt (Watch en Fix apart, zonder testklanten en zonder lopende gratis
proef, zelfde telling als kanalen.py). Met de dagen die nog over zijn.
"""
from datetime import date

import db

DOEL = {"watch": 2, "fix": 2}
DEADLINE = date(2026, 10, 31)


def _een(opdracht):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(opdracht)
                return cur.fetchall()
    except Exception as e:
        print(f"Koers tellen mislukt: {e}")
        return None
    finally:
        conn.close()


def tellen():
    """{"mensen", "opvolgingen", "antwoorden", "proeven", "watch", "fix"} of None."""
    r = _een("""SELECT
        (SELECT count(*) FROM benadering WHERE mens_op > now() - interval '7 days'),
        (SELECT count(*) FROM benadering WHERE opvolg_stand = 'verstuurd' AND opvolg_op > now() - interval '7 days'),
        (SELECT count(*) FROM antwoorden WHERE ontvangen_op > now() - interval '7 days'
            AND coalesce(soort, '') NOT IN ('afmelden', 'helpdesk', 'automatisch')),
        (SELECT count(*) FROM klanten WHERE NOT is_test AND opgezegd_op IS NULL
            AND gratis_tot IS NOT NULL AND gratis_tot >= current_date),
        (SELECT count(*) FROM klanten WHERE NOT is_test AND opgezegd_op IS NULL
            AND (gratis_tot IS NULL OR gratis_tot < current_date) AND lower(coalesce(pakket, '')) = 'watch'),
        (SELECT count(*) FROM klanten WHERE NOT is_test AND opgezegd_op IS NULL
            AND (gratis_tot IS NULL OR gratis_tot < current_date) AND lower(coalesce(pakket, '')) = 'fix')""")
    if not r:
        return None
    m, o, a, p, w, f = r[0]
    return {"mensen": m, "opvolgingen": o, "antwoorden": a, "proeven": p, "watch": w, "fix": f}


def regel(t=None, vandaag=None):
    t = t if t is not None else tellen()
    if not t:
        return None
    vandaag = vandaag or date.today()
    dagen = (DEADLINE - vandaag).days
    if dagen < 0:
        return None
    gehaald = t["watch"] >= DOEL["watch"] and t["fix"] >= DOEL["fix"]
    stand = ("Doel gehaald." if gehaald else
             f"Nog {dagen} dag{'en' if dagen != 1 else ''}.")
    return (f"Op koers naar 2 Watch en 2 Fix voor 31 oktober: nu betalend Watch {t['watch']}, Fix {t['fix']}, "
            f"proeven {t['proeven']}. Laatste 7 dagen: {t['mensen']} echte mensen op hun uitslag, "
            f"{t['opvolgingen']} opvolgingen, {t['antwoorden']} antwoorden. {stand}")
