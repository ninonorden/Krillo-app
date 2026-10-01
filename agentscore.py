"""De vrijdagscore: wat elke agent die week opleverde (1 oktober 2026, idee goedgekeurd door Nino).

WAAROM DIT BESTAAT. Het ochtendbericht telt elke dag wat de agents DEDEN
(verstuurd, gezocht, gemeten). Dat is activiteit. Wat telt is wat het
OPLEVERDE: mensen die keken, mensen die doorklikten, klanten. Een agent die elke
dag twintig mails stuurt en nooit een mens bereikt, ziet er in de dagtelling
druk uit en levert niets op.

ELKE VRIJDAG
- per agent: hoeveel hij de afgelopen 7 dagen verstuurde, hoeveel echte mensen
  daarna keken, en hoeveel er doorklikten (alleen wat we echt kunnen tellen);
- de zwakste agent (genoeg verstuurd, niemand bereikt) krijgt een bouwvoorstel
  in het ochtendbericht: een andere aanpak, door Claude te bouwen na akkoord.

EERLIJK OVER WAT WE TELLEN. "Een mens keek" is de mens-telling van de
Krillo-pagina (scrollen, tikken, muis), niet de mailbeveiliging die elke link
opent. Voor bureaus en lijstjes tellen we wat er wel is (een bureau dat zijn
pagina opende, een schrijver die antwoordde niet: daar is geen telling voor).
Een telling die niet lukt is "onbekend", nooit nul.
"""
from datetime import datetime

import db

MIN_VERSTUURD = 15


def _tel(sql):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rij = cur.fetchone()
                return int(rij[0] or 0) if rij else 0
    except Exception as e:
        print(f"Vrijdagscore, telling mislukt: {e}")
        return None
    finally:
        conn.close()


W = "interval '7 days'"
# (sleutel, naam, verstuurd, mensen, doorgeklikt). None = niet te tellen.
AGENTS = [
    ("koud", "Koude mail",
     f"SELECT count(*) FROM benadering WHERE gemaild_op > now() - {W}",
     f"SELECT count(*) FROM benadering WHERE gemaild_op > now() - {W} AND mens_op IS NOT NULL",
     f"SELECT count(*) FROM benadering WHERE gemaild_op > now() - {W} AND doorgeklikt_op IS NOT NULL"),
    ("verkoop", "Verkoopagent (opvolging)",
     f"SELECT count(*) FROM benadering WHERE opvolg_stand = 'verstuurd' AND opvolg_op > now() - {W}",
     f"SELECT count(*) FROM benadering WHERE opvolg_stand = 'verstuurd' AND opvolg_op > now() - {W} "
     f"AND mens_op > opvolg_op",
     f"SELECT count(*) FROM benadering WHERE opvolg_stand = 'verstuurd' AND opvolg_op > now() - {W} "
     f"AND doorgeklikt_op > opvolg_op"),
    ("beweging", "Bewegingsmails",
     f"SELECT count(*) FROM benadering WHERE beweging_op > now() - {W}",
     f"SELECT count(*) FROM benadering WHERE beweging_op > now() - {W} AND mens_op > beweging_op",
     f"SELECT count(*) FROM benadering WHERE beweging_op > now() - {W} AND doorgeklikt_op > beweging_op"),
    ("badge", "Badge-agent",
     f"SELECT count(*) FROM benadering WHERE badge_op > now() - {W}",
     f"SELECT count(*) FROM benadering WHERE badge_op > now() - {W} AND badge_gezien_op IS NOT NULL",
     None),
    ("bureau", "Bureau-agent",
     f"SELECT count(*) FROM bureaus WHERE gemaild_op > now() - {W}",
     f"SELECT count(DISTINCT bureau_site) FROM bureau_winkels WHERE gekeken_op > now() - {W}",
     None),
    ("lijstjes", "Lijstjesagent",
     f"SELECT count(*) FROM lijstjes WHERE verstuurd_op > now() - {W}",
     None, None),
]


def score():
    """Lijst van {sleutel, naam, verstuurd, mensen, doorgeklikt} voor de laatste 7 dagen."""
    uit = []
    for sleutel, naam, s_v, s_m, s_d in AGENTS:
        uit.append({"sleutel": sleutel, "naam": naam, "verstuurd": _tel(s_v),
                    "mensen": _tel(s_m) if s_m else None, "doorgeklikt": _tel(s_d) if s_d else None})
    return uit


def zwakste(rijen):
    """De agent die genoeg verstuurde maar niemand bereikte. Bij meerdere: de
    grootste verstuurder (daar valt het meest te winnen). Anders None."""
    kandidaten = [r for r in rijen if (r.get("verstuurd") or 0) >= MIN_VERSTUURD
                  and r.get("mensen") == 0]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda r: r["verstuurd"])


def voorstel(rijen, nu=None):
    """Op vrijdag: een bouwvoorstel voor de zwakste agent (hoogstens een per week)."""
    import voorstellen
    nu = nu or datetime.now()
    z = zwakste(rijen)
    if not z or nu.weekday() != 4:
        return None
    return voorstellen.stel_voor(
        "vrijdagscore", "bouwen", f"{z['naam']}: andere aanpak, want deze week bereikte hij niemand",
        waarom=(f"{z['naam']} verstuurde de afgelopen 7 dagen {z['verstuurd']} keer en geen enkele echte mens "
                f"keek daarna. Claude bekijkt onderwerp, eerste zin en aan wie hij stuurt, en bouwt een "
                f"uitdager naast de huidige versie."),
        sleutel=f"vrijdag:{z['sleutel']}:{nu.strftime('%Y-%W')}")
