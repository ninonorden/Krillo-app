"""De badge-agent: de top van elke ranglijst krijgt een felicitatie en een badge.

WAAROM DIT BESTAAT (stap 89, 28 september, voorrang bij klanten binnenhalen).
De koude mail werkt voor winkels die iets te winnen hebben. De winkels bovenaan
kregen tot nu toe een mail die vooral zei wat ze missen. Voor hen is er een
betere, positieve reden om te schrijven: "je staat bovenaan, hier is het bewijs
voor je site". Wie de badge plaatst, laat elke bezoeker zien dat de Krillo Index
bestaat, en elke badge is een link terug naar de ranglijst (gratis bereik en
een link die zoekmachines en AI-assistenten meetellen). En de top heeft iets te
verliezen: dat is het verhaal van Watch.

DE BADGE ZEGT ALTIJD DE WAARHEID
- Het plaatje wordt bij elke weergave opnieuw opgebouwd uit de laatste meting.
- Zakt een winkel uit de top 5, dan toont hetzelfde plaatje alleen nog
  "Measured by the Krillo Index", zonder plek. Nooit een oude plek.

REGELS VOOR DE MAIL
- Alleen plek 1 tot en met 3, alleen als de winkel echt genoemd werd, en alleen
  in een ranglijst die groot genoeg is voor een openbare pagina.
- Per meting een keer, en hoogstens een keer per 90 dagen.
- Nooit naar afgemeld, bounce, klacht, of wie terugmailde; nooit binnen 30
  dagen na een andere extra mail (dezelfde rust als de bewegingsagent).
- Alleen als de benadering aanstaat en binnen kantooruren, met een dagmaximum.
"""
import html as _html
import os

import db

PER_DAG = int(os.environ.get("BADGE_PER_DAG", "10"))
PER_RONDE = int(os.environ.get("BADGE_PER_RONDE", "3"))
MAIL_TOT_PLEK = 3
BADGE_TOT_PLEK = 5
MIN_IN_LIJST = 10
RUST_DAGEN = 90


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
                    return None
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def _kaal(url):
    return (url or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


# ------------------------------------------------------------------ de badge

def badge_gegevens(beeld, categorienaam=None):
    """Wat de badge mag zeggen: {"plek", "categorie", "land"} bij top 5 in een
    lijst die groot genoeg is en genoemd, anders None."""
    if not beeld or not beeld.get("positie"):
        return None
    if beeld["positie"] > BADGE_TOT_PLEK or (beeld.get("van") or 0) < MIN_IN_LIJST:
        return None
    if not (beeld.get("genoemd") or 0) > 0:
        return None
    return {"plek": beeld["positie"], "categorie": categorienaam or beeld.get("categorie"),
            "land": (beeld.get("land") or "").upper()}


def badge_svg(gegevens):
    """Het plaatje. Tekst in het plaatje zelf, geen lettertypen van buiten,
    zodat het overal werkt en niets op hun site trager maakt."""
    e = _html.escape
    if gegevens:
        boven = f"#{gegevens['plek']} in {gegevens['categorie']}"
        onder = f"Recommended by AI · Krillo Index {gegevens['land']}".strip()
    else:
        boven = "Krillo Index"
        onder = "AI visibility, measured monthly"
    breed = max(200, 14 + int(7.2 * max(len(boven), len(onder) * 0.82)))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{breed}" height="46" viewBox="0 0 {breed} 46" role="img" aria-label="{e(boven)}, {e(onder)}">
  <rect x="0.5" y="0.5" width="{breed - 1}" height="45" rx="9" fill="#FFFFFF" stroke="#E4E2DA"/>
  <rect x="0.5" y="0.5" width="5" height="45" rx="2" fill="#1B3FE0"/>
  <text x="16" y="20" font-family="-apple-system,Segoe UI,Arial,sans-serif" font-size="13" font-weight="700" fill="#0A0A0B">{e(boven)}</text>
  <text x="16" y="36" font-family="-apple-system,Segoe UI,Arial,sans-serif" font-size="10.5" fill="#4A4A55">{e(onder)}</text>
</svg>"""


def embedcode(basis_url, token, pagina_url, gegevens):
    alt = (f"#{gegevens['plek']} in {gegevens['categorie']}, Krillo Index" if gegevens else "Krillo Index")
    return (f'<a href="{pagina_url}" target="_blank" rel="noopener">'
            f'<img src="{basis_url}/badge/{token}.svg" alt="{_html.escape(alt)}" height="46"></a>')


# ------------------------------------------------------------------ de mail

def maak_mail(beeld, categorienaam=None, landnaam=None):
    """Onderwerp en alinea's van de felicitatie, of None als het niet mag."""
    g = badge_gegevens(beeld, categorienaam)
    if not g or g["plek"] > MAIL_TOT_PLEK:
        return None
    naam = _kaal(beeld.get("webshop_url"))
    cat = g["categorie"] or "your category"
    waar = f" in {landnaam}" if landnaam else ""
    onderwerp = f"{naam}: #{g['plek']} in {cat} in the Krillo Index"
    alineas = [
        "Hi,",
        f"Good news: in this month's Krillo Index, <strong>{naam} is #{g['plek']} of {beeld.get('van')}</strong> "
        f"in {cat}{waar}. When shoppers ask ChatGPT and Gemini where to buy, your store is one of the "
        f"names they give.",
        "If you like, show it on your site. Paste the code below anywhere, for example in your footer. "
        "The badge updates itself every month and only shows a rank while you are in the top 5, so it "
        "always tells the truth.",
    ]
    slot = ("Staying on top is the hard part: the stores below you are working on it too. Watch "
            "shows you every month where you stand and which questions you could still lose.")
    return {"onderwerp": onderwerp, "alineas": alineas, "slot": slot, "gegevens": g}


# ------------------------------------------------------------------ de ronde

def kandidaten(limiet=100):
    """Winkels met een adres die in hun nieuwste meting op plek 1 tot 3 staan
    en voor die meting nog geen felicitatie kregen."""
    return _sql(f"""
        SELECT b.webshop_url, b.email, u.ronde, u.positie
          FROM benadering b
          JOIN LATERAL (SELECT u.ronde, u.positie FROM categorie_uitkomsten u
                          JOIN categorie_rondes r ON r.id = u.ronde
                         WHERE u.webshop_url = b.webshop_url AND r.afgerond_op IS NOT NULL
                           AND coalesce(u.telbaar, 0) >= 3
                      ORDER BY u.ronde DESC LIMIT 1) u ON TRUE
         WHERE u.positie BETWEEN 1 AND {MAIL_TOT_PLEK}
           AND b.email IS NOT NULL AND b.email <> ''
           AND NOT b.afgemeld AND b.bounce_op IS NULL AND b.klacht_op IS NULL AND b.antwoord_op IS NULL
           AND coalesce(b.soort, 'winkel') = 'winkel'
           AND u.ronde <> coalesce(b.badge_ronde, 0)
           AND (b.badge_op IS NULL OR b.badge_op < now() - interval '{RUST_DAGEN} days')
           AND (b.seizoen_op IS NULL OR b.seizoen_op < now() - interval '30 days')
      ORDER BY u.positie, b.webshop_url
         LIMIT %s""", (limiet,), alles=True) or []


def vandaag_verstuurd():
    rij = _sql("SELECT count(*) AS n FROM benadering WHERE badge_op >= date_trunc('day', now())")
    return int((rij or {}).get("n") or 0)


def ronde(basis_url, bouw_beeld, categorienaam=None, landnaam=None, verstuur=None,
          binnen_kantooruren=True, aan=True):
    verslag = {"verstuurd": 0, "overgeslagen": 0}
    if not aan or not binnen_kantooruren:
        return verslag
    ruimte = min(PER_RONDE, max(0, PER_DAG - vandaag_verstuurd()))
    if not ruimte:
        return verslag
    if verstuur is None:
        import emailing
        verstuur = emailing.send_badge
    for w in kandidaten():
        if verslag["verstuurd"] >= ruimte:
            break
        url = w["webshop_url"]
        try:
            beeld = bouw_beeld(url)
        except Exception:
            beeld = None
        # Deze meting is bekeken, wat er ook uitkomt.
        _sql("UPDATE benadering SET badge_ronde = %s WHERE webshop_url = %s", (w["ronde"], url))
        mail = maak_mail(beeld, categorienaam(beeld) if (categorienaam and beeld) else None,
                         landnaam(beeld) if (landnaam and beeld) else None)
        if not mail:
            verslag["overgeslagen"] += 1
            continue
        token = db.get_benchmark_token(url)
        if not token:
            continue
        pagina = f"{basis_url}/index/{(beeld.get('land') or '').lower()}/{beeld.get('categorie')}"
        code = embedcode(basis_url, token, pagina, mail["gegevens"])
        _sql("UPDATE benadering SET badge_op = now(), seizoen_op = now() WHERE webshop_url = %s", (url,))
        if verstuur(w["email"], mail["onderwerp"], mail["alineas"], code, mail["slot"],
                    f"{basis_url}/uitkomst/{token}", afmeld_url=f"{basis_url}/afmelden/{token}"):
            verslag["verstuurd"] += 1
    return verslag
