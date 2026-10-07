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
# 30 september: "/demo/plan" zocht nog "Start Watch", maar de knop heet sinds
# de proef "Try Watch free for 14 days". De pagina was goed, de controle oud.
# Daarom zoekt hij nu naar de knoppen zoals ze echt heten, en bewaakt
# test_nachtcontrole_teksten dat elke tekst op de echte pagina staat.
PAGINAS = [
    ("/", "Check my store free"),
    ("/#pricing", "Start Watch free for 14 days"),
    ("/demo", "Overview"),
    ("/demo/ranking", "Ranking"),
    ("/demo/questions", "All buying questions"),
    ("/demo/fixes", "Start Fix"),
    ("/demo/plan", "Try Watch free for 14 days"),
    ("/index", "Krillo"),
    ("/privacy", "Privacy"),
    ("/faq", "?"),
    ("/terms", "Krillo"),
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


def controleer(app, nu=None, proef=True):
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

    # 5. De knop "Get my free rank" zoals een bezoeker hem gebruikt (30
    # september, idee van 29 september dat Nino goedkeurde). Een pagina kan
    # prima laden terwijl de knop zelf niets teruggeeft; dat zag je hierboven niet.
    try:
        g, f = gratis_plek(app)
        goed += g
        fout += f
    except Exception as e:
        fout.append(f"Gratis plek nakijken mislukt: {type(e).__name__}: {e}")

    # 6. De kassa zelf, met de testsleutel van Mollie (stap 134 deel 2).
    if proef:
        try:
            g, f = proefbetaling(app)
            goed += g
            fout += f
        except Exception as e:
            fout.append(f"Proefbetaling mislukt: {e}")

    return {"goed": goed, "fout": fout, "op": nu.isoformat()}


# Duurt de gratis check langer dan dit, dan is hij voor een bezoeker kapot:
# die klikt weg voordat er iets staat.
GRATIS_PLEK_MAX_SECONDEN = 25
GRATIS_PLEK_HERKOMST = "nachtcontrole"


def gratis_plek(app, winkel=None):
    """De knop "Get my free rank" met een winkel die in de index staat.

    Wat hij nakijkt: /api/scan geeft antwoord, binnen GRATIS_PLEK_MAX_SECONDEN,
    en noemt de PLEK van de winkel in zijn categorie. Dat is de belofte van de
    knop; een antwoord met alleen de dertien technische punten is voor deze
    winkel fout. Kon zijn site niet gelezen worden, dan telt dat niet als fout:
    de plek hangt daar niet van af, en de pagina zegt dat eerlijk.

    Een keer per nacht een gewone paginaopvraag bij een winkel, niet meer. De
    regel die dit in gratis_scans achterlaat halen we weer weg, zodat de
    cijfers in het ochtendbericht alleen echte bezoekers tellen.

    Geeft (goed, fout). Zonder gemeten winkel slaat hij over."""
    import time
    if winkel is None:
        try:
            voorbeeld = db.voorbeeldwinkel()
            winkel = (voorbeeld or {}).get("webshop_url")
        except Exception:
            winkel = None
    if not winkel:
        return ["Gratis plek overgeslagen (nog geen gemeten winkel om mee te proberen)"], []
    klant = app.test_client()
    begin = time.time()
    try:
        r = klant.post("/api/scan", json={"url": winkel, "herkomst": GRATIS_PLEK_HERKOMST})
        data = r.get_json(silent=True) or {}
    except Exception as e:
        return [], [f"'Get my free rank' gaf een fout voor {winkel}: {type(e).__name__}: {e}"]
    finally:
        _ruim_gratis_scan_op()
    duur = time.time() - begin
    fout = []
    if r.status_code != 200:
        fout.append(f"'Get my free rank' geeft {r.status_code} voor {winkel}: {str(data)[:200]}")
    elif not (data.get("rang") or {}).get("positie"):
        fout.append(f"'Get my free rank' noemt geen plek voor {winkel}, terwijl die in de index "
                    f"staat. De bezoeker ziet dan alleen de technische punten.")
    if duur > GRATIS_PLEK_MAX_SECONDEN:
        fout.append(f"'Get my free rank' deed er {duur:.0f} seconden over voor {winkel}. "
                    f"Een bezoeker klikt dan weg. Kijk op /admin/traag.")
    if fout:
        return [], fout
    return [f"'Get my free rank' werkt ({winkel}: plek {data['rang']['positie']} van "
            f"{data['rang'].get('van')}, {duur:.0f} s)"], []


def _ruim_gratis_scan_op():
    try:
        conn = db._get_connection()
        if conn is not None:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM gratis_scans WHERE herkomst = %s", (GRATIS_PLEK_HERKOMST,))
            conn.close()
    except Exception:
        pass


PROEFWINKEL = "https://nachtcontrole.krilloai.com"
PROEFADRES = "nachtcontrole@krilloai.com"


def proefbetaling(app, sleutel=None):
    """Stap 134 deel 2: de kassa zoals een klant hem gebruikt, met de
    TESTsleutel van Mollie. Er gaat geen geld om en er ontstaat geen klant.

    Wat hij nakijkt: de kassa geeft een betaallink; Mollie kent de betaling,
    met het juiste bedrag, de juiste terugkeerlink en onze webhook; en onze
    webhook verwerkt een open (niet betaalde) betaling zonder fout en zonder
    klant te maken. Wat hij NIET kan: echt betalen. Dat kan in testmodus
    alleen met de hand op de pagina van Mollie.

    Geeft (goed, fout): twee lijsten. Zonder MOLLIE_TEST_KEY slaat hij over."""
    import payments
    sleutel = (sleutel if sleutel is not None else os.environ.get("MOLLIE_TEST_KEY") or "").strip()
    goed, fout = [], []
    if not sleutel:
        return ["Proefbetaling overgeslagen (zet MOLLIE_TEST_KEY in Render om de kassa elke nacht na te lopen)"], []
    if not sleutel.startswith("test_"):
        return [], ["MOLLIE_TEST_KEY begint niet met test_: dat is geen testsleutel. Proefbetaling niet gedaan."]
    klant = app.test_client()
    with payments.met_sleutel(sleutel):
        try:
            r = klant.post("/api/checkout/monitoring", json={
                "email": PROEFADRES, "url": PROEFWINKEL, "pakket": "fix",
                "voorwaarden_akkoord": True})
            data = r.get_json(silent=True) or {}
        except Exception as e:
            return goed, [f"De kassa gaf een fout: {type(e).__name__}: {e}"]
        if r.status_code != 200 or not data.get("checkout_url") or not data.get("payment_id"):
            return goed, [f"De kassa geeft geen betaallink ({r.status_code}): {str(data)[:200]}"]
        goed.append("Kassa geeft een betaallink")
        p = payments.betaling_nakijken(data["payment_id"]) or {}
        if p.get("mode") != "test":
            fout.append("De proefbetaling staat NIET in testmodus. Kijk direct in Mollie.")
        verwacht = payments.PAKKETTEN["fix"]["prijs"]["value"]
        if p.get("bedrag") != verwacht:
            fout.append(f"Bedrag bij Mollie is {p.get('bedrag')}, verwacht {verwacht}.")
        if not str(p.get("webhook_url") or "").endswith("/webhooks/mollie"):
            fout.append(f"De webhook bij Mollie klopt niet: {p.get('webhook_url')}.")
        if "/bedankt" not in str(p.get("redirect_url") or ""):
            fout.append(f"De terugkeerlink bij Mollie klopt niet: {p.get('redirect_url')}.")
        if p and not fout:
            goed.append("Mollie kent de proefbetaling met het goede bedrag en de goede links")
        # Niet via de route zelf: die verwerkt op de achtergrond in een eigen
        # draad, en die kent de testsleutel niet (en zou jou dan melden dat de
        # betaling niet op te halen is). Hier dezelfde verwerking, direct.
        try:
            import sys
            appmod = sys.modules.get("app")
            regels = {r.rule for r in app.url_map.iter_rules()}
            if "/webhooks/mollie" not in regels:
                fout.append("De webhook /webhooks/mollie bestaat niet meer.")
            elif appmod is not None and hasattr(appmod, "_verwerk_betaling"):
                appmod._verwerk_betaling(data["payment_id"], "https://krilloai.com")
                if _vraag("SELECT count(*) FROM klanten WHERE webshop_url = %s", (PROEFWINKEL,)):
                    fout.append("De verwerking maakte een klant van een NIET betaalde betaling.")
                else:
                    goed.append("Verwerking van een open betaling maakt geen klant")
        except Exception as e:
            fout.append(f"Verwerken van de proefbetaling gaf een fout: {type(e).__name__}: {e}")
    # De toestemmingsregel van de proef hoort niet tussen die van klanten.
    try:
        conn = db._get_connection()
        if conn is not None:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM toestemmingen WHERE email = %s", (PROEFADRES,))
            conn.close()
    except Exception:
        pass
    return goed, fout


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
