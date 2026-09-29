"""Plekmelding: claim je plek (stap 166, 29 september).

WAAROM DIT BESTAAT. De winkelpagina's (stap 90) worden gevonden door eigenaars
die hun eigen winkel googelen. Die hadden maar een knop: de gratis check. Nu
kunnen ze met alleen hun mailadres een melding krijgen als hun plek verandert.
Wie dat doet vroeg er zelf om: de warmste lead die er is, en geen koude mail,
dus ook toegestaan in landen waar koude mail niet mag.

REGELS
- Dubbele bevestiging: eerst een mail met een bevestigingslink. Zonder
  bevestiging nooit een melding. Zo kan niemand een ander aanmelden.
- Een melding alleen als de plek echt verandert, hoogstens een per meting.
- Afmelden met een klik, in elke mail.
- Bij een bevestiging krijgt Nino een seintje: iemand claimde zijn plek.
"""
import secrets

import db

PER_RONDE = 20


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
    cur.execute("""CREATE TABLE IF NOT EXISTS plekmeldingen (
                       id SERIAL PRIMARY KEY,
                       token TEXT UNIQUE NOT NULL,
                       email TEXT NOT NULL,
                       webshop_url TEXT NOT NULL,
                       land TEXT, categorie TEXT,
                       positie INTEGER,
                       ronde INTEGER,
                       op TIMESTAMPTZ NOT NULL DEFAULT now(),
                       bevestigd_op TIMESTAMPTZ,
                       gemeld_op TIMESTAMPTZ,
                       afgemeld BOOLEAN NOT NULL DEFAULT FALSE,
                       UNIQUE (email, webshop_url))""")


def aanmelden(email, webshop_url, land, categorie, positie, ronde):
    """Geeft het token (nieuw of bestaand) of None. Een afgemelde komt niet terug
    via een nieuwe aanmelding zonder opnieuw te bevestigen."""
    token = secrets.token_urlsafe(16)
    rij = _sql("""INSERT INTO plekmeldingen (token, email, webshop_url, land, categorie, positie, ronde)
                  VALUES (%s, %s, %s, %s, %s, %s, %s)
                  ON CONFLICT (email, webshop_url) DO UPDATE SET afgemeld = FALSE,
                      bevestigd_op = CASE WHEN plekmeldingen.afgemeld THEN NULL ELSE plekmeldingen.bevestigd_op END
                  RETURNING token, bevestigd_op""",
               (token, email.lower()[:200], webshop_url, land, categorie, positie, ronde))
    return rij


def bevestig(token):
    rij = _sql("SELECT * FROM plekmeldingen WHERE token = %s", (token,))
    if not rij:
        return None
    if not rij.get("bevestigd_op"):
        _sql("UPDATE plekmeldingen SET bevestigd_op = now(), afgemeld = FALSE WHERE token = %s", (token,))
        rij["nieuw"] = True
    return rij


def afmelden(token):
    return _sql("UPDATE plekmeldingen SET afgemeld = TRUE WHERE token = %s", (token,))


def bevestigmail(winkel, link):
    return (f"Confirm: rank updates for {winkel}",
            [f"You asked for an email when the rank of <strong>{winkel}</strong> in the Krillo Index changes.",
             "Click below to confirm. If this was not you, ignore this email and nothing happens."])


def meldmail(winkel, categorienaam, nu, was, van):
    richting = "up" if nu < was else "down"
    return (f"{winkel} moved {richting}: now #{nu} in {categorienaam}",
            [f"The new measurement is in: <strong>{winkel}</strong> is now #{nu} of {van} in {categorienaam} "
             f"(it was #{was}).",
             "Your page shows which buying questions changed and who AI names instead."])


def ronde(basis_url, bouw_beeld, categorienaam, verstuur=None):
    """Bevestigde meldingen nalopen: is er een nieuwe meting en een andere plek?"""
    if verstuur is None:
        import emailing
        verstuur = emailing.send_opvolging
    uit = {"gemeld": 0, "bekeken": 0}
    rijen = _sql("""SELECT * FROM plekmeldingen WHERE bevestigd_op IS NOT NULL AND NOT afgemeld
                    ORDER BY coalesce(gemeld_op, op) LIMIT %s""", (PER_RONDE * 5,), alles=True) or []
    for r in rijen:
        if uit["gemeld"] >= PER_RONDE:
            break
        try:
            beeld = bouw_beeld(r["webshop_url"])
        except Exception:
            beeld = None
        uit["bekeken"] += 1
        if not beeld or not beeld.get("positie") or not beeld.get("ronde") or beeld["ronde"] == r.get("ronde"):
            continue
        was = r.get("positie")
        _sql("UPDATE plekmeldingen SET ronde = %s, positie = %s WHERE id = %s",
             (beeld["ronde"], beeld["positie"], r["id"]))
        if not was or was == beeld["positie"]:
            continue
        winkel = r["webshop_url"].replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        onderwerp, alineas = meldmail(winkel, categorienaam(beeld), beeld["positie"], was, beeld.get("van"))
        link = f"{basis_url}/index/{(beeld.get('land') or '').lower()}/{beeld['categorie']}/{winkel}"
        _sql("UPDATE plekmeldingen SET gemeld_op = now() WHERE id = %s", (r["id"],))
        if verstuur(r["email"], onderwerp, alineas, link, afmeld_url=f"{basis_url}/plekmelding/{r['token']}/stop"):
            uit["gemeld"] += 1
    return uit
