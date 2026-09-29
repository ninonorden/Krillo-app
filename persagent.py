"""De persagent: het maandelijkse persbericht gaat vanzelf naar de vakmedia (29 september).

WAAROM DIT BESTAAT. Nino, 29 september: "persbericht moet geautomatiseerd, jij
stuurt alles". Het persbericht stond klaar op /admin/persbericht, maar een
taak die elke maand met de hand moet, gebeurt niet. Een artikel in Emerce of
Twinkle is bereik bij precies de goede lezers, gratis, plus een link die
AI-assistenten meetellen.

REGELS
- Een keer per kalendermaand per land, alleen binnen kantooruren, en alleen
  als er NIEUWS is (een nieuwe nummer 1 of een stijger van 3 plekken of meer)
  uit een meting van de laatste 35 dagen. Geen nieuws, geen mail: een redactie
  die elke maand hetzelfde krijgt, zet ons op de spamlijst.
- Alleen naar het redactieadres dat de redactie zelf op haar site noemt voor
  persberichten (REDACTIES, met de bron en de datum waarop we keken).
- In het Nederlands: de ontvangers zijn Nederlandse en Vlaamse redacties (de
  uitzondering op "alles naar buiten in het Engels").
- Wie "stop" antwoordt (de antwoordagent zet dat als afmelden), krijgt nooit
  meer iets. Onderaan staat hoe.
- Eerst langs de controleagent. Na het versturen een melding aan Nino.
- PERSBERICHT_AUTO=uit in Render zet het stil.
"""
import os
from datetime import datetime, timedelta, timezone

import db

GEKEKEN = "2026-09-29"
REDACTIES = {
    "nl": [
        ("Emerce", "redactie@emerce.nl", "https://www.emerce.nl/over-emerce/contact"),
        ("Twinkle", "redactie@twinklemagazine.nl", "https://twinklemagazine.nl/contact/"),
        ("Ecommerce News", "redactie@ecommercenews.nl", "https://www.ecommercenews.nl/over-ons/"),
        ("RetailTrends", "redactie@retailtrends.nl", "https://retailtrends.nl/contact-retailnews"),
        ("Marketingfacts", "redactie@marketingfacts.nl", "https://www.marketingfacts.nl/colofon/"),
    ],
    "be": [
        ("RetailDetail", "redactie@retaildetail.be", "https://www.retaildetail.be/nl/contact/"),
    ],
}
VERS_DAGEN = 35


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
    cur.execute("""CREATE TABLE IF NOT EXISTS pers_verstuurd (
                       id SERIAL PRIMARY KEY, land TEXT NOT NULL, maand TEXT NOT NULL,
                       adres TEXT NOT NULL, op TIMESTAMPTZ NOT NULL DEFAULT now(),
                       UNIQUE (land, maand, adres))""")


def heeft_nieuws(ov, nu=None):
    """Is er iets te melden, uit een verse meting?"""
    nu = nu or datetime.now(timezone.utc)
    datum = ov.get("datum")
    if not datum:
        return False
    if datum.tzinfo is None:
        datum = datum.replace(tzinfo=timezone.utc)
    if datum < nu - timedelta(days=VERS_DAGEN):
        return False
    return any(c.get("nieuw_bovenaan") or c.get("stijger") for c in ov.get("categorieen") or [])


def afgemeld(adres):
    """Schreef deze redactie ooit 'stop' terug?"""
    return bool(_sql("SELECT 1 AS x FROM antwoorden WHERE lower(van) = %s AND soort = 'afmelden' LIMIT 1",
                     (adres.lower(),)))


def mail(persbericht):
    """Onderwerp en tekst: een korte persoonlijke regel boven het bericht."""
    regels = persbericht.split("\n")
    onderwerp = regels[0]
    tekst = ("Beste redactie,\n\n"
             "Hieronder het overzicht van deze maand uit de Krillo Index: welke webshops ChatGPT en Gemini "
             "aanraden. Vrij te gebruiken met bronvermelding. De volledige cijfers per categorie sturen we "
             "graag; antwoord gewoon op deze mail.\n\n"
             + persbericht
             + "\n\nMet vriendelijke groet,\n" + (os.environ.get("AFZENDER_NAAM") or "Nino") + "\nKrillo\n\n"
             "Liever geen persberichten van ons? Antwoord met 'stop', dan sturen we niets meer.")
    return onderwerp, tekst


def ronde(maak_overzicht, maak_persbericht, verstuur=None, melden=None, nu=None):
    """Een keer per maand per land. maak_overzicht(land) en maak_persbericht(ov)
    komen uit de app (bewaarde ranglijsten)."""
    if os.environ.get("PERSBERICHT_AUTO", "aan").lower() in ("uit", "0", "nee"):
        return {"verstuurd": 0, "reden": "uitgezet"}
    nu = nu or datetime.now(timezone.utc)
    maand = nu.strftime("%Y-%m")
    if verstuur is None:
        import emailing
        verstuur = emailing.send_persbericht
    import markten
    import tekstkeuring
    uit = {"verstuurd": 0, "landen": []}
    for land in markten.index_landen():
        redacties = REDACTIES.get(land) or []
        te_doen = [r for r in redacties
                   if not _sql("SELECT 1 AS x FROM pers_verstuurd WHERE land = %s AND maand = %s AND adres = %s",
                               (land, maand, r[1]))]
        if not te_doen:
            continue
        ov = maak_overzicht(land)
        if not ov or not heeft_nieuws(ov, nu):
            continue
        pb = maak_persbericht(ov)
        if not pb:
            continue
        onderwerp, tekst = mail(pb)
        keuring = tekstkeuring.keur(tekst, taal="nl")
        if not keuring["ok"]:
            if melden:
                melden("Persbericht tegengehouden",
                       f"De controleagent hield het persbericht voor {land} tegen: {'; '.join(keuring['fouten'])}.")
            continue
        gestuurd = []
        for naam, adres, _bron in te_doen:
            # Eerst vastleggen: nooit twee keer, ook niet als het versturen hapert.
            _sql("INSERT INTO pers_verstuurd (land, maand, adres) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                 (land, maand, adres))
            if afgemeld(adres):
                continue
            if verstuur(adres, onderwerp, tekst):
                gestuurd.append(naam)
                uit["verstuurd"] += 1
        uit["landen"].append({"land": land, "naar": gestuurd})
        if melden and gestuurd:
            melden(f"Persbericht verstuurd ({land.upper()})",
                   f"Het persbericht van {maand} ging naar: {', '.join(gestuurd)}. Onderwerp: {onderwerp}. "
                   f"Antwoorden komen binnen op /admin/antwoorden.")
    return uit
