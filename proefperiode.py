"""Watch 14 dagen gratis proberen (stap 167, besluit Nino 29 september).

WAAROM DIT BESTAAT. Otterly en Peec zetten "Start free trial" overal op hun
site; Krillo vroeg meteen 49 euro. Van 26 mensen die hun uitkomst openden,
klikte er 1 naar de prijzen. Een gratis begin haalt de drempel weg.

HOE HET WERKT
- Alleen Watch per maand, en alleen voor een winkel en een mailadres die nog
  nooit klant waren (een keer proberen per winkel).
- De eerste betaling is 1 cent via Mollie: zo komt er een machtiging, en kan
  het abonnement na de proef vanzelf beginnen. Geen factuur voor die cent.
- Het abonnement (49 euro per maand) begint op dag 15 (PROEF_DAGEN + 1).
- Op dag 11 (HERINNER_DAGEN voor het einde) een mail: wat hij al zag, wanneer
  de eerste betaling komt, en hoe hij stopt. Wie opzegt voor dag 15 betaalt niets.
- Opzeggen tijdens de proef zet het Mollie-abonnement stop voordat er iets
  afgeschreven is (de bestaande opzegknop doet dat al).
"""
from datetime import date, datetime, timedelta, timezone

import db

PROEF_DAGEN = 14
HERINNER_DAGEN = 3
PROEF_BEDRAG = {"currency": "EUR", "value": "0.01"}


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
                    return cur.rowcount
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def maak_tabellen(cur):
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS gratis_tot DATE;")
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS proef_herinnerd_op TIMESTAMPTZ;")


def eerste_incasso(vandaag=None):
    """De dag waarop het abonnement begint: na de volle 14 gratis dagen."""
    return (vandaag or date.today()) + timedelta(days=PROEF_DAGEN + 1)


def laatste_gratis_dag(vandaag=None):
    return (vandaag or date.today()) + timedelta(days=PROEF_DAGEN)


# Wie telt als "had al Krillo" (29 september, aangescherpt). Alleen wie een
# ABONNEMENT had (Watch of Fix, of een eerdere proef). Iemand die ooit alleen de
# audit van 79 euro kocht heeft Watch nooit gehad en mag het dus gratis proberen.
# Rijen die Nino als test markeerde tellen niet mee, anders kan hij de proef
# met zijn eigen testwinkel nooit meer nalopen.
_HAD_ABONNEMENT = """(mollie_klant_id IS NOT NULL OR pakket IS NOT NULL OR gratis_tot IS NOT NULL)
                     AND NOT is_test"""


def proef_geweigerd_om(webshop_url, email, pakket, periode):
    """None als de proef mag, anders de reden: "pakket", "winkel" of "email".

    De reden gaat mee naar de site, zodat daar precies staat WAAROM. Nino kreeg
    "already had Krillo" met een nieuw mailadres en dacht dat het een fout was;
    het lag aan de winkel, en dat stond er niet."""
    if (pakket or "").lower() != "watch" or (periode or "maand") != "maand":
        return "pakket"
    if _sql(f"SELECT 1 AS x FROM klanten WHERE webshop_url = %s AND {_HAD_ABONNEMENT} LIMIT 1",
            (webshop_url,)):
        return "winkel"
    if email and _sql(f"SELECT 1 AS x FROM klanten WHERE lower(email) = %s AND {_HAD_ABONNEMENT} LIMIT 1",
                      ((email or "").lower(),)):
        return "email"
    return None


def mag_proef(webshop_url, email, pakket, periode):
    """Watch per maand, en winkel en adres hadden nog nooit een abonnement."""
    return proef_geweigerd_om(webshop_url, email, pakket, periode) is None


def zet_gratis_tot(webshop_url, tot):
    _sql("UPDATE klanten SET gratis_tot = %s WHERE webshop_url = %s", (tot, webshop_url))


def herinner_kandidaten(vandaag=None):
    vandaag = vandaag or date.today()
    return _sql("""SELECT * FROM klanten WHERE gratis_tot IS NOT NULL AND proef_herinnerd_op IS NULL
                     AND opgezegd_op IS NULL AND NOT is_test
                     AND gratis_tot <= %s AND gratis_tot >= %s""",
                (vandaag + timedelta(days=HERINNER_DAGEN), vandaag), alles=True) or []


def herinnermail(winkel, gratis_tot, prijs, beeld=None):
    datum = gratis_tot.strftime("%-d %B")
    alineas = [f"Your free Watch trial for <strong>{winkel}</strong> runs until {datum}."]
    if beeld and beeld.get("positie"):
        alineas.append(f"So far: you are #{beeld['positie']} of {beeld.get('van')} in your category, and your page "
                       f"shows the questions you lose and the fixes to win them.")
    alineas.append(f"If you do nothing, Watch continues at EUR {prijs} a month from the day after, and you can "
                   f"cancel any month. Not for you? Cancel on the Plan page of your dashboard before then, and you "
                   f"pay nothing.")
    return {"onderwerp": f"Your free trial ends on {datum}", "alineas": alineas}


def ronde(basis_url, bouw_beeld, verstuur=None, vandaag=None, prijs=49):
    """De herinnering, een keer per proef."""
    if verstuur is None:
        import emailing
        verstuur = emailing.send_klantbericht
    uit = {"herinnerd": 0}
    for k in herinner_kandidaten(vandaag):
        # Eerst afvinken: nooit twee keer.
        _sql("UPDATE klanten SET proef_herinnerd_op = now() WHERE klant_token = %s", (k["klant_token"],))
        try:
            beeld = bouw_beeld(k["webshop_url"])
        except Exception:
            beeld = None
        winkel = k["webshop_url"].replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        mail = herinnermail(winkel, k["gratis_tot"], prijs, beeld)
        if verstuur(k["email"], mail["onderwerp"], mail["alineas"], f"{basis_url}/mijn/{k['klant_token']}",
                    knop="Open my dashboard"):
            uit["herinnerd"] += 1
    return uit
