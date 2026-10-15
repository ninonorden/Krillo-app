"""Overdag een categorie meten als de mailvoorraad te klein is (15 oktober 2026).

WAAROM. Op 15 oktober stonden er 7 winkels klaar om te mailen terwijl er
dagelijks tientallen uit moeten. De grootste blokkade: ruim 130 winkels met een
mailadres staan in een categorie die nog nooit gemeten is, en zonder ranglijst
kan er geen mail met hun plek uit. Meten gebeurde alleen 's nachts (drie
categorieen), en valt een nacht weg (zoals die van 14 op 15 oktober, door de
geheugencrashes), dan loopt de voorraad een dag achter zonder dat iets het
inhaalt.

Wat dit doet: overdag, hooguit eens per VOORRAAD_ELKE_MINUTEN, en alleen als
er minder winkels klaar staan dan er per dag gemaild mogen worden, meten we
EEN categorie extra: de categorie waar de meeste winkels met een mailadres op
wachten. Alleen als er een hele meting in de dagpot past (zelfde rem als de
nacht), en nooit tijdens het nachtwerk of een andere meting.

Kost: een meting is ongeveer zestig cent en een categorie wordt daarna dertig
dagen niet opnieuw gemeten. Dit haalt dus alleen werk naar voren; per maand
kost het niet meer.
"""
import os

import db

VOORRAAD_ELKE_MINUTEN = int(os.environ.get("VOORRAADMETING_ELKE_MINUTEN", "120"))
VROEGST, LAATST = 8, 20


def wachtend_per_categorie():
    """{categorie: aantal winkels met mailadres die nog nooit gemaild zijn}."""
    conn = db._get_connection()
    if conn is None:
        return {}
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT categorie, count(*) FROM benadering
                                WHERE categorie IS NOT NULL AND categorie <> 'overig'
                                  AND email IS NOT NULL AND email <> ''
                                  AND gemaild_op IS NULL AND afgemeld = FALSE
                                  AND coalesce(soort, 'winkel') = 'winkel'
                                  AND (hoort_bij IS NULL OR hoort_bij = webshop_url)
                                  AND stand IN ('adres', 'meten', 'gemeten')
                             GROUP BY categorie""")
                return {c: n for c, n in cur.fetchall()}
    except Exception as e:
        print(f"Voorraadmeting, wachtenden tellen mislukt: {e}")
        return {}
    finally:
        conn.close()


def kies(om_te_meten, wachtend):
    """De categorie uit de meetrij met de meeste wachtende winkels, of None.
    Een categorie zonder wachtende winkels helpt de voorraad niet: die wacht
    gewoon op de nacht."""
    kandidaten = [(wachtend.get(r["categorie"], 0), r["categorie"]) for r in om_te_meten
                  if wachtend.get(r["categorie"], 0) > 0]
    if not kandidaten:
        return None
    kandidaten.sort(key=lambda x: -x[0])
    return kandidaten[0][1]


def moet_nu(uur, klaar, per_dag, nacht_bezig, meting_bezig):
    """(ja/nee, reden). De goedkope voorwaarden, voor er iets geteld wordt."""
    if not (VROEGST <= uur < LAATST):
        return False, "buiten de uren"
    if nacht_bezig or meting_bezig:
        return False, "er loopt al een meting of het nachtwerk"
    if klaar is not None and per_dag and klaar >= per_dag:
        return False, f"voorraad genoeg ({klaar} klaar, {per_dag} per dag)"
    return True, None
