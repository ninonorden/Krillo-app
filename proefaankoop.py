"""De proefaankoop: elke ochtend koopt een nepklant Watch, door de echte code (1 oktober 2026).

WAAROM DIT BESTAAT. Idee van 1 oktober, akkoord Nino. Die dag liepen we de
klantreis na betalen met de hand na en vonden vier dingen die niet klopten (een
bedanktpagina die twijfelde terwijl er betaald was, beloofde tijden die niet
waar waren). Zoiets mag een echte klant niet als eerste merken. Dus doet een
nepklant het elke ochtend, na de klantblik, voor het ochtendbericht.

WAT ER GEBEURT
1. Een betaling die niet bij Mollie bestaat (kenmerk tr_proefaankoop_...,
   payments.NEPBETALINGEN) gaat door de ECHTE afhandeling: _verwerk_betaling.
2. Wat daar anders is, staat daar met het vlagje proefaankoop: geen factuur
   (die nummers moeten doorlopen), geen abonnement bij Mollie, geen scan van een
   site die niet bestaat, geen melding aan Nino, geen plek in de index, geen
   AI-meting. De rest is precies wat een klant krijgt.
3. De mails gaan nergens heen: ze worden op deze draad opgevangen
   (emailing.vang_op) en nagelezen.
4. Dan wat de klant ziet: de bedanktpagina, zijn dashboard (alle pagina's) en
   inloggen met zijn mailadres.
5. Alles wordt daarna weer opgeruimd. Uitkomst in het ochtendbericht als er
   iets mis is, en op /admin/klantblik.

WAT HIJ NAKIJKT: dat er een klant is met een link en het juiste pakket, dat de
welkomstmail er is met die link en zonder verouderde zinnen, dat er GEEN
factuur uitging, dat de bedanktpagina zegt dat er betaald is, dat elk
dashboardpagina laadt en zijn pakket toont, en dat inloggen de link mailt.
"""
import json
from datetime import datetime

import db

URL = "https://proefaankoop.krilloai.com"
EMAIL = "proefaankoop@krilloai.com"
SLEUTEL = "proefaankoop"


def _opruimen(pid=None):
    conn = db._get_connection()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                for tabel in ("klanten", "rapporten", "benadering"):
                    try:
                        cur.execute("SAVEPOINT p")
                        cur.execute(f"DELETE FROM {tabel} WHERE webshop_url = %s", (URL,))
                        cur.execute("RELEASE SAVEPOINT p")
                    except Exception:
                        cur.execute("ROLLBACK TO SAVEPOINT p")
    finally:
        conn.close()
    if pid:
        try:
            db.ontclaim_payment(pid)
        except Exception:
            pass


def ronde(app, basis_url="https://krilloai.com", nu=None):
    """De proefaankoop. Geeft {"op", "goed": [...], "fout": [...]}."""
    import emailing
    import klantblik
    import payments
    nu = nu or datetime.now()
    pid = f"tr_proefaankoop_{nu.strftime('%Y%m%d%H%M%S')}"
    goed, fout = [], []
    post = []
    _opruimen()
    payments.NEPBETALINGEN[pid] = {
        "status": "paid", "is_paid": True, "interval": None, "subscription_id": None,
        "customer_id": "cst_proefaankoop", "created_at": None, "bedrag": 49.0, "mode": "test",
        "metadata": {"type": "monitoring_first_payment", "webshop_url": URL, "email": EMAIL,
                     "pakket": "watch", "customer_id": "cst_proefaankoop", "periode": "maand",
                     "proefaankoop": True}}
    emailing.vang_op(post)
    try:
        # 1. De betaling, door de echte afhandeling.
        app_module = __import__("app")
        app_module._verwerk_betaling(pid, basis_url)
        klant = db.klant_bij_url(URL) or {}
        tok = klant.get("klant_token")
        (goed if tok else fout).append("Na betalen is er een klant met een eigen link"
                                       if tok else "Na betalen is er GEEN klant aangemaakt")
        if klant and (klant.get("pakket") or "").lower() != "watch":
            fout.append(f"Het pakket staat op {klant.get('pakket')!r} in plaats van watch")
        if klant and not klant.get("is_test"):
            fout.append("De proefklant staat niet als test (hij zou meetellen als klant)")

        # 2. De mails.
        welkom = [m for m in post if "Welcome to Krillo" in m["onderwerp"]]
        if not welkom:
            fout.append("Er ging geen welkomstmail uit (onderwerpen: "
                        + ", ".join(m["onderwerp"] for m in post) + ")")
        else:
            w = welkom[0]
            voor = len(fout)
            tekst = klantblik.zichtbare_tekst(w["html"])
            if tok and f"/mijn/{tok}" not in w["html"]:
                fout.append("De welkomstmail heeft geen link naar het dashboard")
            for zin in klantblik.VEROUDERD:
                if zin.lower() in tekst.lower():
                    fout.append(f"De welkomstmail zegt nog “{zin}” (verouderd)")
            if "—" in tekst:
                fout.append("De welkomstmail heeft een lang streepje")
            if len(fout) == voor:
                goed.append("Welkomstmail met link, zonder verouderde zinnen")
        if any("invoice" in m["onderwerp"].lower() for m in post):
            fout.append("Er ging een factuur uit bij de proefaankoop (dat mag niet: nummers lopen door)")

        # 3. Wat de klant ziet.
        c = app.test_client()
        kop = {"User-Agent": klantblik.KENMERK}
        r = c.get(f"/bedankt?type=monitoring&ref={pid}", headers=kop)
        if "Payment received" in r.get_data(as_text=True):
            goed.append("De bedanktpagina zegt dat er betaald is")
        else:
            fout.append("De bedanktpagina zegt niet dat er betaald is")
        if tok:
            for pad in ("", "/ranking", "/questions", "/fixes", "/plan"):
                r = c.get(f"/mijn/{tok}{pad}", headers=kop)
                if r.status_code != 200:
                    fout.append(f"Dashboard /mijn/...{pad or '/'} geeft {r.status_code}")
                    continue
                for ernst, tekst in klantblik.keur(f"/mijn/x{pad}", r.get_data(as_text=True), r.mimetype or "text/html"):
                    if ernst == "fout":
                        fout.append(f"Dashboard {pad or '/'}: {tekst}")
            plan = c.get(f"/mijn/{tok}/plan", headers=kop).get_data(as_text=True)
            if "Watch" not in klantblik.zichtbare_tekst(plan):
                fout.append("De pagina Plan noemt zijn pakket (Watch) niet")
            else:
                goed.append("Dashboard laadt op alle pagina's en noemt zijn pakket")

        # 4. Inloggen: de link opnieuw per mail.
        post.clear()
        c.post("/login", data={"email": EMAIL}, headers=kop)
        if tok and any(f"/mijn/{tok}" in m["html"] for m in post):
            goed.append("Inloggen mailt de link naar het dashboard")
        else:
            fout.append("Inloggen met het mailadres stuurde geen link")
    except Exception as e:
        fout.append(f"De proefaankoop liep vast: {type(e).__name__}: {e}"[:200])
    finally:
        emailing.vang_op(None)
        payments.NEPBETALINGEN.pop(pid, None)
        _opruimen(pid)
    uit = {"op": nu.isoformat(timespec="minutes"), "goed": goed, "fout": fout}
    try:
        db.zet_instelling(SLEUTEL, json.dumps(uit))
    except Exception as e:
        print(f"Proefaankoop bewaren mislukt: {e}")
    print(f"Proefaankoop: {len(goed)} goed, {len(fout)} fout.")
    return uit


def laatste():
    try:
        return json.loads(db.get_instelling(SLEUTEL) or "{}")
    except Exception:
        return {}
