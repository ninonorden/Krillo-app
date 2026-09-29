"""Drie agents voor klanten: behouden, overstappen en terugwinnen (28 september).

WAAROM DIT BESTAAT. Klanten binnenhalen is het halve werk; houden is de
andere helft. Bij kleine abonnementen haakt wie niets nieuws ziet stil af.

- BEHOUD (stap 99): een betalende klant die zijn pagina 21 dagen niet opende,
  krijgt zijn plek en de ENE vraag die hij het makkelijkst wint. Hoogstens een
  keer per 30 dagen.
- OVERSTAP (stap 130): een Watch-klant die 21 dagen klant is, krijgt een keer
  wat Fix voor hem zou doen, met zijn eigen cijfers. Overstappen blijft via een
  mail (hello@ zet hem dezelfde dag om, zonder dubbel betalen): een knop die
  een Mollie-abonnement omzet is geldcode, en die bouwen we pas als er
  Watch-klanten zijn om hem mee te testen.
- TERUGWIN (stap 152): wie opzegde en van wie daarna een nieuwe meting is,
  krijgt EEN keer zijn nieuwe plek. Geen korting, geen tweede mail.

REGELS: nooit testklanten; alleen met een echte plek uit de index (geen plek,
geen mail); afvinken VOOR het versturen (nooit twee keer); elke mail gaat door
de controleagent (emailing.send_klantbericht); alleen in kantooruren (de
uurronde regelt dat); hoogstens PER_RONDE per soort per ronde.
"""
import db

PER_RONDE = 5
BEHOUD_NA_DAGEN = 21
BEHOUD_RUST_DAGEN = 30
OVERSTAP_NA_DAGEN = 21
TERUGWIN_NA_DAGEN = 20


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
    """Aangeroepen vanuit db.init_db."""
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS laatst_bekeken_op TIMESTAMPTZ;")
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS behoud_op TIMESTAMPTZ;")
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS overstap_op TIMESTAMPTZ;")
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS terugwin_op TIMESTAMPTZ;")
    # Wanneer een agent voor het laatst keek. Zo komt een klant zonder plek of
    # zonder nieuwe meting morgen weer langs, en niet elk uur (en blokkeert hij
    # de rij niet voor de rest).
    cur.execute("ALTER TABLE klanten ADD COLUMN IF NOT EXISTS agent_gekeken_op TIMESTAMPTZ;")


def bekeken(klant_token):
    """De klant opende zijn eigen pagina (niet de demo, niet beheer)."""
    _sql("UPDATE klanten SET laatst_bekeken_op = now() WHERE klant_token = %s", (klant_token,))


def _winkel(url):
    return (url or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def _plek(beeld, categorienaam):
    return (f"<strong>{_winkel(beeld['webshop_url'])}</strong> is #{beeld['positie']} of {beeld['van']} "
            f"in {categorienaam}")


def behoud_kandidaten():
    return _sql(f"""SELECT * FROM klanten
                    WHERE NOT is_test AND opgezegd_op IS NULL
                      AND aangemaakt_op < now() - interval '{BEHOUD_NA_DAGEN} days'
                      AND coalesce(laatst_bekeken_op, aangemaakt_op) < now() - interval '{BEHOUD_NA_DAGEN} days'
                      AND (behoud_op IS NULL OR behoud_op < now() - interval '{BEHOUD_RUST_DAGEN} days')
                    ORDER BY aangemaakt_op LIMIT {PER_RONDE}""", alles=True) or []


def behoud_mail(beeld, vraag, categorienaam):
    """Plek plus de ene vraag die hij het makkelijkst wint. None zonder plek."""
    if not beeld or not beeld.get("positie"):
        return None
    alineas = [f"A quick update: {_plek(beeld, categorienaam)}, from the latest measurement."]
    if vraag and vraag.get("vraag"):
        wie = ", ".join((vraag.get("concurrenten") or [])[:2])
        alineas.append(f"The question you are closest to winning: \"{vraag['vraag']}\"."
                       + (f" AI named {wie} there." if wie else ""))
        alineas.append("On your page you see what to change for it, step by step.")
    else:
        alineas.append("On your page you see which questions you lose, and what to change.")
    return {"onderwerp": f"Your rank this month: #{beeld['positie']}", "alineas": alineas}


def overstap_kandidaten():
    return _sql(f"""SELECT * FROM klanten
                    WHERE NOT is_test AND opgezegd_op IS NULL AND lower(coalesce(pakket, '')) = 'watch'
                      -- Alleen via de site (Mollie): in de Shopify-app wissel je in de app zelf.
                      AND mollie_klant_id IS NOT NULL
                      AND overstap_op IS NULL
                      AND aangemaakt_op < now() - interval '{OVERSTAP_NA_DAGEN} days'
                      AND (agent_gekeken_op IS NULL OR agent_gekeken_op < now() - interval '1 day')
                    ORDER BY agent_gekeken_op NULLS FIRST, aangemaakt_op LIMIT {PER_RONDE}""", alles=True) or []


def overstap_mail(beeld, categorienaam, prijs_fix=149):
    if not beeld or not beeld.get("positie"):
        return None
    verloren = len(beeld.get("gemiste_vragen") or [])
    alineas = [f"You have been on Watch for three weeks. {_plek(beeld, categorienaam)}."]
    if verloren:
        alineas.append(f"There are {verloren} buying questions where AI names someone else. With Watch you "
                       f"make the changes for those yourself.")
    alineas.append(f"With Fix (EUR {prijs_fix} a month) we make them in your store for you: the product texts, "
                   f"the details AI reads, every change with the old text so anything can be undone.")
    alineas.append("Want to switch? Reply to this email and we switch you the same day, without paying twice.")
    return {"onderwerp": "What Fix would do for your store", "alineas": alineas}


def terugwin_kandidaten():
    return _sql(f"""SELECT * FROM klanten
                    WHERE NOT is_test AND opgezegd_op IS NOT NULL AND terugwin_op IS NULL
                      AND opgezegd_op < now() - interval '{TERUGWIN_NA_DAGEN} days'
                      AND opgezegd_op > now() - interval '120 days'
                      AND (agent_gekeken_op IS NULL OR agent_gekeken_op < now() - interval '1 day')
                    ORDER BY agent_gekeken_op NULLS FIRST, opgezegd_op LIMIT {PER_RONDE}""", alles=True) or []


def terugwin_mail(beeld, categorienaam, opgezegd_op):
    """Alleen als er NA het opzeggen gemeten is: anders is er geen nieuws."""
    if not beeld or not beeld.get("positie") or not beeld.get("gemeten_op") or not opgezegd_op:
        return None
    if beeld["gemeten_op"] <= opgezegd_op:
        return None
    alineas = [f"Since you stopped, we measured your category again. {_plek(beeld, categorienaam)}"
               + (f" (the month before: #{beeld['vorige_positie']})." if beeld.get("vorige_positie") else ".")]
    alineas.append("Your page still shows the questions you lose and what to change. If you want your rank "
                   "every month again, you can restart any time. This is the only email about it.")
    return {"onderwerp": f"Your store is now #{beeld['positie']}", "alineas": alineas}


def ronde(basis_url, bouw_beeld, categorienaam, verstuur=None, vraag_voor=None):
    """Een ronde van alle drie. bouw_beeld(url) geeft het klantbeeld."""
    if verstuur is None:
        import emailing
        verstuur = emailing.send_klantbericht
    uit = {"behoud": 0, "overstap": 0, "terugwin": 0, "overgeslagen": 0}

    def _doe(soort, kolom, klant, maak):
        _sql("UPDATE klanten SET agent_gekeken_op = now() WHERE klant_token = %s", (klant["klant_token"],))
        try:
            beeld = bouw_beeld(klant["webshop_url"])
        except Exception:
            beeld = None
        mail = maak(beeld) if beeld else None
        if not mail:
            # Geen plek of geen nieuws: niets versturen. Behoud rust dan 30
            # dagen; overstap en terugwin kijken morgen weer (agent_gekeken_op).
            if kolom == "behoud_op":
                _sql("UPDATE klanten SET behoud_op = now() WHERE klant_token = %s", (klant["klant_token"],))
            uit["overgeslagen"] += 1
            return
        # Afvinken VOOR het versturen: nooit twee keer, ook niet als er iets hapert.
        _sql(f"UPDATE klanten SET {kolom} = now() WHERE klant_token = %s", (klant["klant_token"],))
        link = f"{basis_url}/mijn/{klant['klant_token']}"
        if verstuur(klant["email"], mail["onderwerp"], mail["alineas"], link):
            uit[soort] += 1

    for k in behoud_kandidaten():
        _doe("behoud", "behoud_op", k, lambda b, url=k["webshop_url"]: behoud_mail(
            b, vraag_voor(url, b) if vraag_voor else ((b.get("gemiste_vragen") or [None])[0]), categorienaam(b)))
    for k in overstap_kandidaten():
        _doe("overstap", "overstap_op", k, lambda b: overstap_mail(b, categorienaam(b)))
    for k in terugwin_kandidaten():
        _doe("terugwin", "terugwin_op", k, lambda b, op=k["opgezegd_op"]: terugwin_mail(b, categorienaam(b), op))
    return uit
