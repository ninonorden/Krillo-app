"""De verkeersagent: meet elke dag welke bron mensen en checks oplevert, en stuurt bij (15 oktober 2026).

WAAROM. Nino: "kunnen we een traffic-agent maken die automatisch leert wat de
beste manieren zijn en dat toepast, zodat het verkeer elke dag groeit?" We doen
nu veel tegelijk (koude mail, LinkedIn-berichten, antwoorden op Reddit, gidsen,
het Top 10-plaatje, de App Store) en niemand ziet welke ervan iets oplevert.
Deze agent telt het, per bron, elke dag:
- echte mensen (bezoekers die scrolden of tikten, geen mailbeveiliging);
- gratis checks (de eerste stap naar klant);
- deze week tegen de week ervoor.

En hij LEERT erop. Dat is geen toverij: elke bron hoort bij een actie die Nino of
de agents doen (reddit hoort bij de kansenagent, linkedin_dm bij de berichten,
google bij de gidsen en de SEO-agent). De volgorde van Nino's dagtaken volgt
wat de afgelopen twee weken het meeste opleverde, en een actie die na genoeg
pogingen niets oplevert, gaat van zijn lijst (met de reden in het ochtendbericht).
Zo gaat de tijd naar wat werkt, elke dag opnieuw bepaald door de cijfers.

Alleen tellingen, geen personen: herkomst komt uit utm_source of de vorige
pagina, net als op /admin/bezoek.
"""
import json
from datetime import date, timedelta

import db

# Bron (zoals herkomst hem opslaat) -> de actie die hem voedt.
ACTIE_VAN_BRON = {
    "reddit.com": "kansen", "old.reddit.com": "kansen", "community.shopify.com": "kansen",
    "indiehackers.com": "kansen", "tweakers.net": "kansen",
    "linkedin_dm": "dm", "linkedin.com": "linkedin", "lnkd.in": "linkedin",
    "google.com": "seo", "google.nl": "seo", "google.be": "seo", "bing.com": "seo", "duckduckgo.com": "seo",
    "chatgpt.com": "ai", "perplexity.ai": "ai", "gemini.google.com": "ai",
    "koude_mail": "mail", "krillo": "shopify", "apps.shopify.com": "shopify",
}
# Een actie die na zoveel pogingen 0 mensen opleverde, gaat van de dagtaken.
STOP_NA_POGINGEN = {"dm": 40, "kansen": 20}
SLEUTEL_DAG = "verkeer_dag:"


def actie_van(bron):
    bron = (bron or "").lower()
    if bron in ACTIE_VAN_BRON:
        return ACTIE_VAN_BRON[bron]
    for sleutel, actie in ACTIE_VAN_BRON.items():
        if bron.endswith("." + sleutel):
            return actie
    return "overig" if bron else "direct"


def per_bron(van, tot):
    """{bron: {"mensen", "checks"}} tussen twee datums (tot niet meegerekend)."""
    conn = db._get_connection()
    if conn is None:
        return {}
    uit = {}
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT coalesce(b.herkomst, ''), count(DISTINCT b.bezoeker)
                                 FROM bezoeken b JOIN bezoek_mensen m ON m.bezoeker = b.bezoeker
                                WHERE b.gezien_op >= %s AND b.gezien_op < %s
                             GROUP BY 1""", (van, tot))
                for bron, n in cur.fetchall():
                    uit.setdefault(bron or "", {"mensen": 0, "checks": 0})["mensen"] += n
                cur.execute("""SELECT coalesce(herkomst, ''), count(*) FROM gratis_scans
                                WHERE gelukt AND gedaan_op >= %s AND gedaan_op < %s GROUP BY 1""", (van, tot))
                for bron, n in cur.fetchall():
                    uit.setdefault(bron or "", {"mensen": 0, "checks": 0})["checks"] += n
    except Exception as e:
        print(f"Verkeersagent, tellen mislukt: {e}")
    finally:
        conn.close()
    return uit


def per_actie(bronnen):
    uit = {}
    for bron, c in bronnen.items():
        a = uit.setdefault(actie_van(bron), {"mensen": 0, "checks": 0})
        a["mensen"] += c["mensen"]
        a["checks"] += c["checks"]
    return uit


def score(c):
    """Een check is tien keer zoveel waard als een bezoeker: dat is de stap naar klant."""
    return (c or {}).get("mensen", 0) + 10 * (c or {}).get("checks", 0)


def pogingen():
    """Hoe vaak elke actie gedaan is (voor het stoppen van wat niets oplevert)."""
    uit = {"dm": 0, "kansen": 0}
    try:
        uit["dm"] = sum(1 for _ in _instellingen_met("dm_linkedin:"))
        lijst = json.loads(db.get_instelling("kansen_lijst") or "[]")
        uit["kansen"] = sum(1 for k in lijst if k.get("stand") == "geplaatst")
    except Exception:
        pass
    return uit


def _instellingen_met(voorvoegsel):
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT sleutel FROM instellingen WHERE sleutel LIKE %s AND waarde = 'ja'",
                            (voorvoegsel + "%",))
                return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def beeld(vandaag=None, telling=None, gedaan=None):
    """Het beeld van vandaag: deze week, de week ervoor, per actie, en wat te doen."""
    vandaag = vandaag or date.today()
    telling = telling or per_bron
    nu = per_actie(telling(vandaag - timedelta(days=7), vandaag + timedelta(days=1)))
    vorig = per_actie(telling(vandaag - timedelta(days=14), vandaag - timedelta(days=7)))
    twee_weken = {k: {"mensen": nu.get(k, {}).get("mensen", 0) + vorig.get(k, {}).get("mensen", 0),
                      "checks": nu.get(k, {}).get("checks", 0) + vorig.get(k, {}).get("checks", 0)}
                  for k in set(nu) | set(vorig)}
    gedaan = gedaan if gedaan is not None else pogingen()
    gestopt = [a for a, grens in STOP_NA_POGINGEN.items()
               if gedaan.get(a, 0) >= grens and twee_weken.get(a, {}).get("mensen", 0) == 0]
    volgorde = sorted([a for a in ("kansen", "dm", "seo", "linkedin") if a not in gestopt],
                      key=lambda a: -score(twee_weken.get(a)))
    return {"deze_week": nu, "vorige_week": vorig,
            "mensen": sum(c["mensen"] for c in nu.values()),
            "mensen_vorig": sum(c["mensen"] for c in vorig.values()),
            "checks": sum(c["checks"] for c in nu.values()),
            "beste": max(twee_weken, key=lambda a: score(twee_weken[a])) if twee_weken else None,
            "volgorde": volgorde, "gestopt": gestopt}


NAAM = {"kansen": "antwoorden op Reddit en fora", "dm": "LinkedIn-berichten", "seo": "Google",
        "linkedin": "LinkedIn-posts", "mail": "koude mail", "shopify": "Shopify", "ai": "AI-assistenten",
        "direct": "direct", "overig": "overige sites"}


def ochtendregel(b):
    """Een regel voor het ochtendbericht."""
    verschil = b["mensen"] - b["mensen_vorig"]
    teken = "+" if verschil >= 0 else ""
    delen = sorted(b["deze_week"].items(), key=lambda kv: -score(kv[1]))[:4]
    bronnen = ", ".join(f"{NAAM.get(a, a)} {c['mensen']}" + (f" ({c['checks']} checks)" if c["checks"] else "")
                        for a, c in delen if c["mensen"] or c["checks"])
    regel = (f"Verkeer, 7 dagen: {b['mensen']} echte mensen ({teken}{verschil} tegen de week ervoor), "
             f"{b['checks']} checks." + (f" Per bron: {bronnen}." if bronnen else ""))
    if b["gestopt"]:
        regel += " Gestopt omdat het na genoeg pogingen niets opleverde: " + \
                 ", ".join(NAAM.get(a, a) for a in b["gestopt"]) + "."
    return regel


def bewaar_dag(b, vandaag=None):
    """Elke dag een momentopname, zodat we later zien wat werkte."""
    vandaag = vandaag or date.today()
    db.zet_instelling(SLEUTEL_DAG + vandaag.isoformat(), json.dumps(
        {"mensen": b["mensen"], "checks": b["checks"], "per_actie": b["deze_week"]}))
