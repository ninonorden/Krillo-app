"""Stap 181: leest AI je winkel nog? Een wekelijkse controle voor klanten (30 september 2026).

WAAROM. Peec koppelt serverlogboeken om te laten zien welke AI-robots langskomen.
Voor Shopify kan dat niet (geen logboek). Wat wel kan, en voor een webshop
bijna net zo veel zegt: elke week nakijken of de robots die winkels vinden voor
kopers (OAI-SearchBot, ChatGPT-User, PerplexityBot, ...) er nog bij mogen.

Het gaat vaker mis dan je denkt: een nieuw thema, een beveiligingsplugin of een
Cloudflare-instelling zet ze ongemerkt buiten de deur. Dan verdwijnt een
winkel een maand later uit de antwoorden, en weet niemand waarom. Deze wacht
ziet het binnen een week.

REGELS.
- Alleen lopende klanten (niet opgezegd, geen test).
- Alleen een mail bij een VERANDERING naar "geblokkeerd" (of de eerste keer
  geblokkeerd). Geen wekelijkse herhaling van hetzelfde nieuws.
- Weer open na een blokkade: een korte mail dat het weer goed is.
- Nino krijgt in beide gevallen een regel (via meld).
- Een keer per week (claim_moment), in de nacht.
"""
import json

import db

SLEUTEL = "robotwacht:"
WEEK = 7 * 24 * 3600


def klanten():
    """[(webshop_url, email, token)] van lopende klanten."""
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT webshop_url, email, klant_token FROM klanten
                                WHERE opgezegd_op IS NULL AND coalesce(is_test, FALSE) = FALSE
                                  AND email IS NOT NULL AND email <> ''""")
                return [tuple(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Robotwacht, klanten ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def _vorige(url):
    try:
        return json.loads(db.get_instelling(SLEUTEL + url) or "{}")
    except (TypeError, ValueError):
        return {}


def mailtekst(uitkomst, winkel):
    geblokt = [r for r in uitkomst.get("robots") or [] if not r["mag"]]
    alineas = [f"Our weekly check found that AI robots can no longer read {winkel}. "
               f"The robots that are now kept out:"]
    alineas += [f"{r['bot']} ({r['wie']}): {r['wat']}" for r in geblokt[:6]]
    alineas += [o for o in uitkomst.get("opmerkingen") or []][:2]
    alineas.append("This usually happens after a theme change, a new security plugin or a firewall setting. "
                   "As long as it stays like this, ChatGPT and the others cannot see your store when a shopper "
                   "asks, and you will drop out of their answers.")
    alineas.append("How to fix it: " + (uitkomst.get("herstel") or ""))
    alineas.append("Reply to this email if you want us to look at it with you.")
    return f"AI robots can no longer read {winkel}", alineas


def ronde(check=None, stuur=None, meld=None, basis_url="https://krilloai.com", forceer=False):
    """Een wekelijkse ronde. Geeft een verslag: {"bekeken", "geblokkeerd", "weer_open", "gemaild"}."""
    verslag = {"bekeken": 0, "geblokkeerd": [], "weer_open": [], "gemaild": 0}
    if not forceer and not db.claim_moment("robotwacht_week", WEEK - 3600):
        return verslag
    if check is None:
        import gratistools
        check = gratistools.crawler_check
    if stuur is None:
        import emailing
        stuur = emailing.send_klantbericht
    for url, email, token in klanten():
        try:
            u = check(url)
        except Exception as e:
            print(f"Robotwacht mislukt voor {url}: {e}")
            continue
        if not u or u.get("fout"):
            continue
        verslag["bekeken"] += 1
        nu = u.get("oordeel")
        voor = _vorige(url).get("oordeel")
        db.zet_instelling(SLEUTEL + url, json.dumps({"oordeel": nu}))
        winkel = u.get("winkel") or url
        link = f"{basis_url.rstrip('/')}/mijn/{token}" if token else basis_url
        if nu == "blocked" and voor != "blocked":
            verslag["geblokkeerd"].append(url)
            onderwerp, alineas = mailtekst(u, winkel)
            if stuur(email, onderwerp, alineas, link, knop="Open my Krillo page"):
                verslag["gemaild"] += 1
        elif voor == "blocked" and nu in ("open", "partly"):
            verslag["weer_open"].append(url)
            if stuur(email, f"AI robots can read {winkel} again",
                     [f"Good news: our weekly check shows that the AI robots that find stores for shoppers can "
                      f"read {winkel} again. Nothing else to do."], link, knop="Open my Krillo page"):
                verslag["gemaild"] += 1
    if meld and (verslag["geblokkeerd"] or verslag["weer_open"]):
        meld("Robotwacht: verandering bij een klant",
             "Geblokkeerd: " + (", ".join(verslag["geblokkeerd"]) or "geen") +
             ". Weer open: " + (", ".join(verslag["weer_open"]) or "geen") +
             ". De klant heeft een mail met de oplossing gekregen.")
    return verslag
