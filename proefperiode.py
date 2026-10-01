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
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS fix_aanbod_op TIMESTAMPTZ;")
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS activatie_op TIMESTAMPTZ;")


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


# ---------------------------------------------------------------------------
# HET FIX-AANBOD IN DE PROEF (30 september, het nieuwe idee bij dashboard 8).
#
# WAAROM. Wie in zijn proef van Watch drie of meer koopvragen op zijn lijst zet
# ("Add to my fixes"), laat zien dat hij wil dat het beter wordt. Dat is het
# moment om te vragen of wij het werk doen. Een keer per klant, alleen tijdens
# de proef, en alleen als hij nog niet opzegde. Geen korting en geen druk: de
# vragen die hij zelf koos, en wat Fix daarmee doet.
# ---------------------------------------------------------------------------
FIX_AANBOD_VANAF = 3


def fix_aanbod_kandidaten(vandaag=None):
    vandaag = vandaag or date.today()
    return _sql("""SELECT k.*, (SELECT count(*) FROM gekozen_vragen g WHERE g.webshop_url = k.webshop_url) AS gekozen
                     FROM klanten k
                    WHERE k.gratis_tot IS NOT NULL AND k.gratis_tot >= %s
                      AND k.fix_aanbod_op IS NULL AND k.opgezegd_op IS NULL AND NOT k.is_test
                      AND lower(coalesce(k.pakket, '')) = 'watch'
                      AND (SELECT count(*) FROM gekozen_vragen g WHERE g.webshop_url = k.webshop_url) >= %s""",
                (vandaag, FIX_AANBOD_VANAF), alles=True) or []


def fix_aanbod_mail(winkel, vragen, fix_prijs):
    # Elke vraag een eigen regel: de mail laat alleen <strong> door (zie
    # emailing.alina_s_veilig), dus geen <br> of opsommingstekens in HTML.
    alineas = ([f"You put {len(vragen)} buying questions on your list for <strong>{winkel}</strong>:"]
               + [f"\u201c{v}\u201d" for v in vragen[:5]] + [
               "With Watch you get the fix for each one written out, to do yourself. With Fix we put them "
               "live in your store for you, with access you give us and can take back any time. "
               "The old text is kept, so every change can be undone, and at the next monthly measurement you "
               "see the difference.",
               f"Fix is EUR {fix_prijs} a month and you can cancel any month. Want us to do it? Open the Plan "
               f"page of your dashboard and click Switch to Fix: no second payment. Rather do it yourself? Then "
               f"nothing changes."])
    return {"onderwerp": "Shall we put these fixes live for you?", "alineas": alineas}


def fix_aanbod_ronde(basis_url, verstuur=None, vandaag=None, fix_prijs=149, gekozen=None):
    """Een keer per proef: het aanbod voor Fix aan wie 3 of meer vragen koos."""
    if verstuur is None:
        import emailing
        verstuur = emailing.send_klantbericht
    if gekozen is None:
        gekozen = db.gekozen_vragen
    uit = {"fix_aanbod": 0}
    try:
        kandidaten = fix_aanbod_kandidaten(vandaag)
    except Exception as e:
        # De tabel met gekozen vragen bestaat pas na de eerste keuze.
        print(f"Fix-aanbod kandidaten ophalen mislukt: {e}")
        return uit
    for k in kandidaten:
        # Eerst afvinken: nooit twee keer.
        _sql("UPDATE klanten SET fix_aanbod_op = now() WHERE klant_token = %s", (k["klant_token"],))
        winkel = k["webshop_url"].replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        mail = fix_aanbod_mail(winkel, gekozen(k["webshop_url"]), fix_prijs)
        if verstuur(k["email"], mail["onderwerp"], mail["alineas"], f"{basis_url}/mijn/{k['klant_token']}/plan",
                    knop="Switch to Fix"):
            uit["fix_aanbod"] += 1
    return uit


# ---------------------------------------------------------------------------
# STAP 129, DE ACTIVATIEAGENT (1 oktober).
#
# WAAROM. Een proef die niemand gebruikt wordt nooit een betaling. Wie op dag 2
# van zijn proef zijn dashboard niet meer opende en nog geen enkele vraag op
# zijn lijst zette, heeft het "aha" nog niet gezien. Die krijgt een keer de
# drie koopvragen die hij verliest, met wie er wel genoemd werd, en een knop
# naar precies die pagina. Geen korting, geen druk: zijn eigen cijfers.
# ---------------------------------------------------------------------------
ACTIVATIE_NA_DAGEN = 2


def activatie_kandidaten(vandaag=None):
    vandaag = vandaag or date.today()
    # gratis_tot = start + 14, dus start = gratis_tot - 14; dag 2 = start + 2.
    grens = vandaag - timedelta(days=ACTIVATIE_NA_DAGEN) + timedelta(days=PROEF_DAGEN)
    try:
        return _sql("""SELECT k.* FROM klanten k
                        WHERE k.gratis_tot IS NOT NULL AND k.gratis_tot <= %s AND k.gratis_tot >= %s
                          AND k.activatie_op IS NULL AND k.opgezegd_op IS NULL AND NOT k.is_test
                          AND (k.laatst_bekeken_op IS NULL
                               OR k.laatst_bekeken_op < k.aangemaakt_op + interval '1 day')
                          AND NOT EXISTS (SELECT 1 FROM gekozen_vragen g WHERE g.webshop_url = k.webshop_url)""",
                    (grens, vandaag), alles=True) or []
    except Exception:
        # De tabel met gekozen vragen bestaat pas na de eerste keuze.
        return _sql("""SELECT k.* FROM klanten k
                        WHERE k.gratis_tot IS NOT NULL AND k.gratis_tot <= %s AND k.gratis_tot >= %s
                          AND k.activatie_op IS NULL AND k.opgezegd_op IS NULL AND NOT k.is_test
                          AND (k.laatst_bekeken_op IS NULL
                               OR k.laatst_bekeken_op < k.aangemaakt_op + interval '1 day')""",
                    (grens, vandaag), alles=True) or []


def activatiemail(winkel, beeld):
    """De drie verloren vragen, met wie er in plaats van jou genoemd werd."""
    vragen = [v for v in (beeld or {}).get("gemiste_vragen") or [] if v.get("vraag")][:3]
    if not vragen:
        return None
    alineas = [f"Your free Watch trial for <strong>{winkel}</strong> is running. Here are three buying questions "
               f"shoppers ask where AI named other stores and not you:"]
    for v in vragen:
        wie = ", ".join(n for n in (v.get("concurrenten") or [])[:2] if n)
        alineas.append(f"\u201c{v['vraag']}\u201d" + (f": AI named {wie}." if wie else "."))
    alineas.append("Your dashboard shows the full answer for each one, and what to change to win it. Click "
                   "\"Add to my fixes\" on the questions that matter most to you, and they go on your list.")
    return {"onderwerp": f"3 questions {winkel} is losing to other stores", "alineas": alineas}


def activatie_ronde(basis_url, bouw_beeld, verstuur=None, vandaag=None):
    if verstuur is None:
        import emailing
        verstuur = emailing.send_klantbericht
    uit = {"activatie": 0}
    for k in activatie_kandidaten(vandaag):
        # Eerst afvinken: nooit twee keer, ook niet als er geen vragen zijn.
        _sql("UPDATE klanten SET activatie_op = now() WHERE klant_token = %s", (k["klant_token"],))
        try:
            beeld = bouw_beeld(k["webshop_url"])
        except Exception:
            beeld = None
        winkel = k["webshop_url"].replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        mail = activatiemail(winkel, beeld)
        if mail and verstuur(k["email"], mail["onderwerp"], mail["alineas"],
                             f"{basis_url}/mijn/{k['klant_token']}/questions", knop="See my questions"):
            uit["activatie"] += 1
    return uit
