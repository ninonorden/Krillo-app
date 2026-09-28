"""De controleagent: elke nacht loopt Krillo zijn eigen klantweg na.

WAAROM DIT BESTAAT (stap 134, 28 september). Er zijn nog geen klanten, dus
niemand merkt het als een pagina kapot is, een mail niet meer weggaat of de
meting stilstaat. Tot de eerste klant het merkt. Deze agent doet elke nacht
wat een klant doet en kijkt wat de achterkant doet, en mailt Nino voor 8:00
als er iets mis is. Is alles goed, dan komt er niets (geen ruis).

WAT HIJ NAKIJKT
- De pagina's die een klant ziet: homepage, prijzen, demo met alle vijf
  pagina's, de index, privacy, FAQ, voorwaarden. Elke pagina moet laden EN de
  tekst bevatten die erop hoort (een lege pagina met 200 is ook kapot).
- Of de onderdelen er zijn: database, Mollie, Brevo, AI-sleutels, Shopify.
- Of het werk doorloopt: is er de laatste dagen gemeten, en gaat er mail uit
  als de benadering aanstaat.

WAT HIJ (NOG) NIET DOET: een echte testbetaling. Daarvoor is een testsleutel
van Mollie nodig (MOLLIE_TEST_KEY); dat is de volgende stap op de roadmap.
"""
import os
from datetime import datetime, timezone, timedelta

import db

# Pagina, en een stukje tekst dat er MOET staan. Engels, want de site is Engels.
PAGINAS = [
    ("/", "Check my store"),
    ("/#pricing", "Fix"),
    ("/demo", "Overview"),
    ("/demo/ranking", "Ranking"),
    ("/demo/questions", "All buying questions"),
    ("/demo/fixes", "Start Fix"),
    ("/demo/plan", "Start Watch"),
    ("/index", "Krillo"),
    ("/privacy", "Privacy"),
    ("/faq", "?"),
    ("/voorwaarden", "Krillo"),
    ("/robots.txt", "User-agent"),
]

# Zoveel dagen mag er tussen twee afgeronde metingen zitten.
MAX_DAGEN_ZONDER_METING = 3
# Zoveel werkdagen zonder verstuurde mail terwijl de benadering aanstaat.
MAX_DAGEN_ZONDER_MAIL = 2


def _vraag(sql, waarden=None):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, waarden)
                rij = cur.fetchone()
                return rij[0] if rij else None
    finally:
        conn.close()


def _oud(tijd, nu, dagen):
    if tijd is None:
        return True
    if tijd.tzinfo is None:
        tijd = tijd.replace(tzinfo=timezone.utc)
    return nu - tijd > timedelta(days=dagen)


def controleer(app, nu=None):
    """Loopt alles na. Geeft {"goed": [...], "fout": [...]} terug."""
    nu = nu or datetime.now(timezone.utc)
    goed, fout = [], []

    # 1. De pagina's, zoals een bezoeker ze ziet.
    klant = app.test_client()
    for pad, moet in PAGINAS:
        try:
            r = klant.get(pad.split("#")[0])
            tekst = r.get_data(as_text=True)
            if r.status_code != 200:
                fout.append(f"Pagina {pad} geeft {r.status_code}.")
            elif moet not in tekst:
                fout.append(f"Pagina {pad} laadt, maar '{moet}' staat er niet op.")
            else:
                goed.append(f"Pagina {pad}")
        except Exception as e:
            fout.append(f"Pagina {pad} geeft een fout: {type(e).__name__}: {e}")

    # 2. De onderdelen.
    try:
        if _vraag("SELECT 1") == 1:
            goed.append("Database")
        else:
            fout.append("De database antwoordt niet.")
    except Exception as e:
        fout.append(f"Database: {e}")
    for naam, sleutel, waarom in (
            ("Mollie", "MOLLIE_API_KEY", "zonder kan niemand betalen"),
            ("Brevo", "BREVO_API_KEY", "zonder gaat er geen enkele mail uit"),
            ("OpenAI", "OPENAI_API_KEY", "zonder wordt er niet gemeten"),
            ("Gemini", "GOOGLE_API_KEY", "zonder meet alleen ChatGPT"),
            ("Anthropic", "ANTHROPIC_API_KEY", "zonder geen teksten en geen adresvinder"),
            ("Cron", "CRON_KEY", "zonder draait er 's nachts niets")):
        if (os.environ.get(sleutel) or "").strip():
            goed.append(naam)
        else:
            fout.append(f"{sleutel} ontbreekt in Render: {waarom}.")
    mollie = (os.environ.get("MOLLIE_API_KEY") or "").strip()
    if mollie.startswith("test_"):
        fout.append("MOLLIE_API_KEY is een testsleutel: klanten betalen niet echt.")
    if (os.environ.get("SHOPIFY_BILLING_TEST") or "").strip().lower() in ("ja", "1", "true"):
        # Tijdens de beoordeling hoort dit aan; daarna uit. Geen fout, wel melden.
        goed.append("Let op: SHOPIFY_BILLING_TEST staat aan (goed tijdens de beoordeling, daarna weghalen)")

    # 3. Loopt het werk door?
    try:
        laatste_meting = _vraag("SELECT max(afgerond_op) FROM categorie_rondes")
        if _oud(laatste_meting, nu, MAX_DAGEN_ZONDER_METING):
            fout.append(f"Er is al meer dan {MAX_DAGEN_ZONDER_METING} dagen geen categorie gemeten "
                        f"(laatste: {laatste_meting or 'nooit'}). Draait de nachtronde nog?")
        else:
            goed.append("Metingen lopen")
    except Exception as e:
        fout.append(f"Metingen nakijken mislukt: {e}")
    try:
        aan = (db.get_instelling("benadering_aan") or "").lower() in ("ja", "1", "true", "aan")
        if aan and nu.weekday() < 5:
            laatste_mail = _vraag("SELECT max(gemaild_op) FROM benadering")
            # Maandag telt het weekend niet mee.
            marge = MAX_DAGEN_ZONDER_MAIL + (2 if nu.weekday() == 0 else 0)
            if _oud(laatste_mail, nu, marge):
                fout.append(f"De benadering staat aan, maar er is al meer dan {marge} dagen geen "
                            f"mail verstuurd (laatste: {laatste_mail or 'nooit'}). Rij leeg, of Brevo stuk?")
            else:
                goed.append("Koude mail loopt")
    except Exception as e:
        fout.append(f"Benadering nakijken mislukt: {e}")

    # 4. De antwoordagent (stap 126): ligt er een winkel te wachten, en komen
    # de meldingen nog bij Nino aan?
    try:
        import antwoordagent
        wacht = antwoordagent.wachtend_sinds(24)
        if wacht:
            fout.append(f"{wacht} antwoord(en) van winkels wachten al meer dan een dag op /admin/antwoorden.")
        else:
            goed.append("Geen antwoorden die blijven liggen")
    except Exception as e:
        fout.append(f"Antwoorden nakijken mislukt: {e}")
    reply = (os.environ.get("SMTP_REPLY_TO") or "").strip().lower()
    beheer = (os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL") or "").strip()
    if reply.endswith(".krilloai.com") and not beheer:
        fout.append("SMTP_REPLY_TO gaat naar de antwoordagent, maar BEHEERDER_EMAIL ontbreekt: "
                    "meldingen komen dan nergens aan.")

    return {"goed": goed, "fout": fout, "op": nu.isoformat()}


def draai(app, melden):
    """Voor de nachtronde: controleren, uitkomst bewaren, en alleen melden als er iets mis is."""
    import json
    uit = controleer(app)
    try:
        db.zet_instelling("nachtcontrole", json.dumps(uit)[:20000])
    except Exception as e:
        print(f"Nachtcontrole bewaren mislukt: {e}")
    if uit["fout"]:
        regels = "".join(f"<li>{f}</li>" for f in uit["fout"])
        melden("Nachtcontrole: er is iets mis",
               f"De controleagent vond vannacht {len(uit['fout'])} probleem/problemen:"
               f"<ul>{regels}</ul>Alles wat hij nakeek staat op /admin/controle.")
    print(f"Nachtcontrole: {len(uit['goed'])} goed, {len(uit['fout'])} fout.")
    return uit
