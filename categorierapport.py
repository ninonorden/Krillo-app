"""Het rapport per categorie als lokkertje (stap 137, 14 oktober 2026).

WAAROM. De ranglijsten krijgen bezoek (Search Console: duizenden vertoningen),
maar wie er komt en geen eigen winkel invult, is weer weg zonder dat we weten
wie hij was. Nu kan hij de ranglijst van die categorie als rapport per mail
krijgen: de top 10, de mediaan, drie echte koopvragen met wie AI daar noemde,
de bronnen die AI aanhaalt en hoe AI de nummer 1 omschrijft. Alles uit de
meting zelf, niets verzonnen.

Wie het aanvraagt is een warme lead: een winkelier, een bureau of een
journalist die zich voor juist deze categorie interesseert. Nino krijgt een
melding. Wie "elke maand" aanvinkt, staat apart vastgelegd (toestemming voor
latere mail is iets anders dan een rapport aanvragen).
"""
import secrets
from html import escape

import db


def maak_tabellen(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS rapport_aanvragen (
                       id SERIAL PRIMARY KEY,
                       email TEXT NOT NULL,
                       land TEXT NOT NULL,
                       categorie TEXT NOT NULL,
                       maandelijks BOOLEAN NOT NULL DEFAULT FALSE,
                       token TEXT NOT NULL,
                       aangevraagd_op TIMESTAMPTZ NOT NULL DEFAULT now(),
                       UNIQUE (email, land, categorie))""")


def leg_vast(email, land, categorie, maandelijks=False):
    """Geeft (token, nieuw) terug, of (None, False) als de database weg is."""
    conn = db._get_connection()
    if conn is None:
        return None, False
    try:
        with conn:
            with conn.cursor() as cur:
                maak_tabellen(cur)
                cur.execute("""INSERT INTO rapport_aanvragen (email, land, categorie, maandelijks, token)
                               VALUES (%s, %s, %s, %s, %s)
                               ON CONFLICT (email, land, categorie) DO UPDATE
                                 SET maandelijks = rapport_aanvragen.maandelijks OR EXCLUDED.maandelijks
                               RETURNING token, (xmax = 0) AS nieuw""",
                            (email.strip().lower()[:190], land, categorie[:80], bool(maandelijks),
                             secrets.token_urlsafe(16)))
                token, nieuw = cur.fetchone()
                return token, bool(nieuw)
    finally:
        conn.close()


def tel(dagen=7):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                maak_tabellen(cur)
                cur.execute("SELECT count(*) FROM rapport_aanvragen WHERE aangevraagd_op > now() - make_interval(days => %s)",
                            (dagen,))
                return cur.fetchone()[0]
    finally:
        conn.close()


def vragen_met_namen(antwoorden, maximaal=3):
    """Per vraag de winkels die AI noemde (geen platforms), uit de bewaarde
    antwoorden zonder tekst. Vragen met de meeste winkels eerst."""
    import json
    per = {}
    for a in antwoorden or []:
        g = a.get("genoemde_winkels") or {}
        if isinstance(g, str):
            try:
                g = json.loads(g)
            except ValueError:
                g = {}
        if not g.get("winkel_kon_genoemd", a.get("winkel_kon_genoemd")):
            continue
        namen = per.setdefault(a.get("vraag"), [])
        for w in g.get("winkels") or []:
            n = w.get("naam")
            if n and w.get("soort") != "platform" and n not in namen:
                namen.append(n)
    uit = [{"vraag": v, "namen": n} for v, n in per.items() if v and n]
    uit.sort(key=lambda x: -len(x["namen"]))
    return uit[:maximaal]


def _naam(r):
    naam = r.get("naam")
    if naam and not str(naam).startswith("http"):
        return naam
    return (r.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def rapport_html(categorienaam, landnaam, lijst, mediaan=None, vragen_met_namen=(), bronnen=(),
                 imago_een=None, pagina_url=""):
    """(onderwerp, html). lijst = de ranglijst van db.ranglijst_per_land."""
    import emailing
    rijen = [r for r in lijst.get("rijen") or [] if (r.get("genoemd") or 0) > 0][:10]
    telbaar = lijst.get("telbaar") or 0
    e = escape
    tabel = "".join(
        f'<tr><td style="padding:7px 0; border-top:1px solid #EEE; width:34px; font-weight:600;">{r["positie"]}</td>'
        f'<td style="padding:7px 0; border-top:1px solid #EEE;">{e(_naam(r))}</td>'
        f'<td style="padding:7px 0; border-top:1px solid #EEE; text-align:right; white-space:nowrap;">'
        f'named {r.get("genoemd") or 0} of {telbaar}</td></tr>' for r in rijen)
    body = emailing._p(f"The top {len(rijen)} of {e(categorienaam)} in {e(landnaam)}: the stores ChatGPT and "
                       f"Gemini name when shoppers ask where to buy, out of {len(lijst.get('rijen') or [])} "
                       f"stores we measured with {telbaar} buying questions.")
    body += f'<table role="presentation" width="100%" style="border-collapse:collapse; font-size:14px; margin:6px 0 18px;">{tabel}</table>'
    if mediaan is not None:
        body += emailing._p(f"The middle store of the category is named in {mediaan} of {telbaar} questions.")
    vb = [v for v in vragen_met_namen if v.get("vraag") and v.get("namen")][:3]
    if vb:
        body += emailing._p("<strong>Three of the questions we asked, and who AI named:</strong>")
        body += "".join(emailing._p(f"&ldquo;{e(v['vraag'])}&rdquo;: {e(', '.join(v['namen'][:3]))}") for v in vb)
    if bronnen:
        body += emailing._p("<strong>Sites AI cited in these answers:</strong> "
                            + e(", ".join(f"{b['naam']} ({b['aantal']}x)" for b in list(bronnen)[:5])))
    kenmerken = [k[0] if isinstance(k, (list, tuple)) else k for k in (imago_een or {}).get("kenmerken") or []][:4]
    if kenmerken and rijen:
        body += emailing._p(f"<strong>How AI describes #1, {e(_naam(rijen[0]))}:</strong> {e(', '.join(kenmerken))}.")
    body += emailing._p("Is your store in this category? The free check shows where you stand, the questions "
                        "you lose and who AI names instead. No account needed.")
    body += emailing._score_button("https://krilloai.com/#scan", "Check my store")
    if pagina_url:
        body += emailing._p(f'The full ranking: <a href="{e(pagina_url)}">{e(pagina_url)}</a>', zacht=True)
    titel = f"Who AI recommends: {categorienaam}, {landnaam}"
    return titel, emailing._base_html(titel, "From the Krillo Index, measured this month.", body)
