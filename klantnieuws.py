"""Klantnieuws: een keer per maand de grootste verbeteringen aan klanten (1 oktober 2026).

WAAROM. Idee van 1 oktober, akkoord Nino met een voorwaarde: "alleen de
grootste veranderingen, we zitten in een zware upgradefase, uiteindelijk een
keer per maand". Een klant die ziet dat het product beter wordt waar hij voor
betaalt, blijft langer. De tekst bestaat al: de changelog.

REGELS
- Alleen regels uit de changelog die in changelog.GROOT staan. Klein werk gaat
  niet naar klanten.
- Een keer per kalendermaand, op een werkdag binnen kantooruren, vanaf de 3e
  (dan staan de nieuwtjes van het einde van de vorige maand er ook bij).
- Hoogstens drie regels, elk een zin. Geen grote nieuwtjes: geen mail.
- Alleen naar betalende klanten die niet opzegden en geen test zijn. Niet
  nogmaals hetzelfde: wat al gemeld is, onthouden we.
- Langs de controleagent, zoals elke mail aan klanten (emailing.send_klantbericht).
"""
import json
from datetime import datetime

import db

SLEUTEL = "klantnieuws_gemeld"
MAX_REGELS = 3


def grote_nieuwtjes(al_gemeld=None):
    import changelog
    al_gemeld = set(al_gemeld or [])
    return [r for r in changelog.REGELS if r[1] in changelog.GROOT and r[1] not in al_gemeld][:MAX_REGELS]


def klanten():
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT email, webshop_url, klant_token FROM klanten
                           WHERE NOT coalesce(is_test, FALSE) AND opgezegd_op IS NULL
                             AND (mollie_klant_id IS NOT NULL OR pakket IS NOT NULL)""")
            return [{"email": r[0], "webshop_url": r[1], "klant_token": r[2]} for r in cur.fetchall()]
    except Exception as e:
        print(f"Klantnieuws, klanten ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def mag_nu(nu=None):
    nu = nu or datetime.now()
    return nu.day >= 3 and nu.weekday() < 5 and 9 <= nu.hour < 17


def ronde(basis_url="https://krilloai.com", nu=None, stuur=None):
    """Een keer per maand. Geeft een verslag {"verstuurd", "regels"}."""
    import emailing
    nu = nu or datetime.now()
    if not mag_nu(nu) or not db.claim_moment(f"klantnieuws:{nu.strftime('%Y-%m')}", 40 * 24 * 3600):
        return {"verstuurd": 0, "regels": [], "reden": "niet nu"}
    try:
        gemeld = json.loads(db.get_instelling(SLEUTEL) or "[]")
    except Exception:
        gemeld = []
    nieuw = grote_nieuwtjes(gemeld)
    if not nieuw:
        return {"verstuurd": 0, "regels": [], "reden": "geen grote nieuwtjes"}
    stuur = stuur or emailing.send_klantbericht
    alineas = ["Hi,", "Three things that got better in Krillo this month:" if len(nieuw) == 3
               else "What got better in Krillo this month:"]
    alineas += [f"<strong>{titel}.</strong> {tekst.split('. ')[0].rstrip('.')}." for _, titel, tekst, _ in nieuw]
    alineas.append("All of it is already in your dashboard. Questions? Just reply.")
    verstuurd = 0
    for k in klanten():
        link = f"{basis_url.rstrip('/')}/mijn/{k['klant_token']}"
        if stuur(k["email"], "What is new in Krillo this month", alineas, link, knop="Open my dashboard"):
            verstuurd += 1
    db.zet_instelling(SLEUTEL, json.dumps(gemeld + [r[1] for r in nieuw]))
    return {"verstuurd": verstuurd, "regels": [r[1] for r in nieuw]}
