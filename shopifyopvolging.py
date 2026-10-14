"""Opvolging na een installatie van de Shopify-app (14 oktober 2026).

WAAROM DIT BESTAAT. Sinds 14 oktober staat de app volledig zichtbaar in de
Shopify App Store. Wie hem installeerde, kreeg daarna nooit iets van ons: hij
opende de app een keer, zag misschien "your rank is on its way", en daarna
hoorde hij niets meer. Iemand die zelf een app installeert is de warmste
winkelier die er is (warmer dan elke koude mail), dus die laten we niet los.

Twee mails per winkel, elk hooguit een keer, alleen echte cijfers:
1. PLEKMAIL: zodra zijn plek in de index er is. "Je plek in <categorie> is
   binnen: #4 van 40" (of eerlijk "Not named yet"), met een vraag die hij
   verliest en wie er toen wel genoemd werd. Knop: open Krillo in je beheer.
2. OPVOLGMAIL: OPVOLG_NA_DAGEN na de plekmail, alleen als hij nog geen plan
   heeft. De gratis wijzigingen en Watch 14 dagen gratis. Geen korting.

Niet naar: winkels zonder mailadres, adressen van Shopify zelf (de
beoordelaars, *@shopify.com), het eigen adres van de beheerder, verwijderde
installaties en winkels die al betalen. Twijfel over betalen (Shopify
onbereikbaar) telt als betalen: liever een mail te weinig dan een verkoopmail
aan een klant.
"""
import os

import db

OPVOLG_NA_DAGEN = int(os.environ.get("SHOPIFY_OPVOLG_DAGEN", "4"))
PER_RONDE = int(os.environ.get("SHOPIFY_OPVOLG_PER_RONDE", "20"))


def maak_kolommen(cur):
    cur.execute("ALTER TABLE shopify_winkels ADD COLUMN IF NOT EXISTS plekmail_op TIMESTAMPTZ;")
    cur.execute("ALTER TABLE shopify_winkels ADD COLUMN IF NOT EXISTS opvolgmail_op TIMESTAMPTZ;")


def _sql(opdracht, waarden=None, alles=True):
    conn = db._get_connection()
    if conn is None:
        return [] if alles else None
    try:
        from psycopg2.extras import RealDictCursor
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opdracht, waarden)
                if cur.description is None:
                    return None
                return [dict(r) for r in cur.fetchall()] if alles else cur.fetchone()
    finally:
        conn.close()


def mag_mailen(email):
    email = (email or "").strip().lower()
    if "@" not in email or email.endswith("@shopify.com"):
        return False
    beheer = (os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL") or "").strip().lower()
    return not (beheer and email == beheer)


def app_link(winkel):
    """De app in het eigen Shopify-beheer van de winkelier."""
    sleutel = (os.environ.get("SHOPIFY_API_KEY") or "").strip()
    return f"https://{winkel}/admin/apps/{sleutel}" if sleutel else f"https://{winkel}/admin/apps"


def plekmail_html(winkel, beeld, categorienaam):
    import emailing
    v = emailing.veilig
    if beeld.get("nul"):
        titel = f"Your rank in {v(categorienaam)} is in"
        intro = (f"AI named {beeld.get('genoemde_winkels') or 0} stores in your category and not yours yet, "
                 f"in {beeld.get('telbaar') or 0} buying questions.")
        plek = "Not named yet"
    else:
        titel = f"You are #{beeld['positie']} of {beeld['van']} in {v(categorienaam)}"
        intro = (f"AI named you in {beeld.get('genoemd') or 0} of {beeld.get('telbaar') or 0} buying "
                 f"questions and really recommended you in {beeld.get('aanbevolen') or 0}.")
        plek = f"#{beeld['positie']} of {beeld['van']}"
    feiten = [("Store", v(emailing._kaal_adres(beeld.get("webshop_url") or winkel))), ("Your rank", plek)]
    if beeld.get("mediaan") is not None:
        feiten.append(("Category median", f"named in {beeld['mediaan']} of {beeld.get('telbaar') or 0}"))
    body = emailing._feiten(feiten)
    vraag = next((q for q in beeld.get("gemiste_vragen") or [] if q.get("concurrenten")), None)
    if vraag:
        body += emailing._p(f"One question you lose: <strong>{v(vraag['vraag'])}</strong>. "
                            f"AI named {v(', '.join(vraag['concurrenten'][:3]))} instead.")
    body += emailing._p("Open Krillo in your Shopify admin to see the stores around you and the first fixes. "
                        "The first 3 changes are free, and every change can be undone.")
    body += emailing._score_button(app_link(winkel), "Open Krillo")
    return titel, emailing._base_html(titel, intro, body)


def opvolgmail_html(winkel, beeld):
    import emailing
    titel = "Your 3 free fixes are still waiting"
    verloren = len(beeld.get("gemiste_vragen") or [])
    intro = (f"You lose {verloren} buying question{'s' if verloren != 1 else ''} in your category. "
             if verloren else "") + "Here is what Krillo can do about it."
    body = (emailing._p("We write the missing text AI needs to understand your store: image descriptions, "
                        "fuller product descriptions and a questions page. You see every change first, "
                        "and the first 3 are free and stay in your store whatever you decide.")
            + emailing._p("Watch shows every question you lose and who AI named instead, every month. It is "
                          "free for 14 days, then billed through Shopify. Cancel any time.")
            + emailing._score_button(app_link(winkel), "Get my free fixes")
            + emailing._p("Questions? Just reply to this email.", zacht=True))
    return titel, emailing._base_html(titel, intro, body)


def ronde(beeld_van, betaalt, send=None, categorienaam_van=None):
    """Een ronde. beeld_van(rij) -> klantbeeld of None; betaalt(rij) -> True/False/None.
    Geeft {"plekmail": n, "opvolgmail": n} terug."""
    import emailing
    send = send or emailing.send_email
    if categorienaam_van is None:
        import categorieen
        categorienaam_van = categorieen.naam_en
    uit = {"plekmail": 0, "opvolgmail": 0}
    rijen = _sql("""SELECT * FROM shopify_winkels
                     WHERE actief AND verwijderd_op IS NULL AND email IS NOT NULL
                       AND geinstalleerd_op < now() - interval '30 minutes'
                       AND (plekmail_op IS NULL
                            OR (opvolgmail_op IS NULL
                                AND plekmail_op < now() - make_interval(days => %s)))
                  ORDER BY geinstalleerd_op LIMIT %s""", (OPVOLG_NA_DAGEN, PER_RONDE)) or []
    for rij in rijen:
        if not mag_mailen(rij.get("email")):
            continue
        beeld = beeld_van(rij)
        if not beeld:
            continue
        if rij.get("plekmail_op") is None:
            titel, html = plekmail_html(rij["winkel"], beeld, categorienaam_van(beeld.get("categorie")))
            if send(rij["email"], titel, html):
                _sql("UPDATE shopify_winkels SET plekmail_op = now() WHERE winkel = %s", (rij["winkel"],))
                uit["plekmail"] += 1
            continue
        if betaalt(rij) is not False:
            # Betaalt, of we weten het niet: geen verkoopmail, en niet blijven proberen.
            _sql("UPDATE shopify_winkels SET opvolgmail_op = now() WHERE winkel = %s", (rij["winkel"],))
            continue
        titel, html = opvolgmail_html(rij["winkel"], beeld)
        if send(rij["email"], titel, html):
            _sql("UPDATE shopify_winkels SET opvolgmail_op = now() WHERE winkel = %s", (rij["winkel"],))
            uit["opvolgmail"] += 1
    return uit
