"""De agentwereld (stap 148, idee Nino 28 september): een dorp dat een stad wordt.

WAAROM DIT BESTAAT. Nino wil in een oogopslag zien welke agent werkt, en het
dorp moet meegroeien met Krillo. Elke agent heeft een huisje. Werkte hij het
laatste uur, dan staat zijn poppetje te bouwen; anders zit het op het bankje.
Hoe hoog zijn huis is hangt aan zijn echte werk (elke tien keer zoveel werk is
een verdieping erbij), en het stadhuis in het midden krijgt een verdieping per
betalende klant.

HOE HET GEKOPPELD IS: nergens nieuwe logboeken voor nodig. Elke agent zet al
een tijdstip bij wat hij doet (gemaild_op, opvolg_op, gekeken_op, ...). De
wereld telt die: hoeveel in totaal, hoeveel het laatste uur. Een telling die
niet lukt (een tabel die er nog niet is) geeft een leeg huisje, nooit een fout.
"""
import math

import db

# (sleutel, naam, wat hij doet, SQL totaal, SQL laatste uur). "{uur}" wordt het tijdvenster.
AGENTS = [
    ("mailer", "De mailer", "stuurt de koude mail",
     "SELECT count(*) FROM benadering WHERE gemaild_op IS NOT NULL",
     "SELECT count(*) FROM benadering WHERE gemaild_op > now() - interval '{uur}'"),
    ("adres", "De adresvinder", "zoekt het adres van winkels",
     "SELECT count(*) FROM benadering WHERE email IS NOT NULL",
     None),
    ("meter", "De meter", "stelt de koopvragen aan AI",
     "SELECT count(*) FROM categorie_uitkomsten",
     "SELECT count(*) FROM categorie_uitkomsten WHERE gemeten_op > now() - interval '{uur}'"),
    ("verkoop", "De verkoopagent", "volgt warme winkels op",
     "SELECT count(*) FROM benadering WHERE opvolg_op IS NOT NULL",
     "SELECT count(*) FROM benadering WHERE opvolg_op > now() - interval '{uur}'"),
    ("antwoord", "De antwoordagent", "beantwoordt wie terugmailt",
     "SELECT count(*) FROM antwoorden",
     "SELECT count(*) FROM antwoorden WHERE ontvangen_op > now() - interval '{uur}'"),
    ("beweging", "De bewegingsagent", "meldt wie steeg of daalde",
     "SELECT count(*) FROM benadering WHERE beweging_op IS NOT NULL",
     "SELECT count(*) FROM benadering WHERE beweging_op > now() - interval '{uur}'"),
    ("badge", "De badge-agent", "feliciteert de top",
     "SELECT count(*) FROM benadering WHERE badge_op IS NOT NULL",
     "SELECT count(*) FROM benadering WHERE badge_op > now() - interval '{uur}'"),
    ("bureau", "De bureauvinder", "zoekt bureaus onderaan winkels",
     "SELECT count(*) FROM bureau_winkels",
     "SELECT count(*) FROM bureau_winkels WHERE gekeken_op > now() - interval '{uur}'"),
    ("klant", "De klantagenten", "houden klanten en winnen ze terug",
     "SELECT count(*) FROM klanten WHERE behoud_op IS NOT NULL OR overstap_op IS NOT NULL OR terugwin_op IS NOT NULL",
     "SELECT count(*) FROM klanten WHERE agent_gekeken_op > now() - interval '{uur}'"),
    ("tools", "De gereedschapsmid", "draait de gratis tools",
     "SELECT count(*) FROM tool_gebruik",
     "SELECT count(*) FROM tool_gebruik WHERE op > now() - interval '{uur}'"),
    ("leer", "De leeragent", "onderzoekt en leert",
     "SELECT count(*) FROM agent_inzichten",
     "SELECT count(*) FROM agent_inzichten WHERE op > now() - interval '{uur}'"),
    ("wacht", "De wachtpost", "houdt de wachtlijst per land bij",
     "SELECT count(*) FROM wachtlijst_land",
     "SELECT count(*) FROM wachtlijst_land WHERE op > now() - interval '{uur}'"),
    ("pers", "De persagent", "stuurt het persbericht naar de vakmedia",
     "SELECT count(*) FROM pers_verstuurd",
     "SELECT count(*) FROM pers_verstuurd WHERE op > now() - interval '{uur}'"),
    ("lijstjes", "De lijstjesagent", "vraagt schrijvers van GEO-lijstjes om Krillo",
     "SELECT count(*) FROM lijstjes WHERE stand = 'gemaild'",
     "SELECT count(*) FROM lijstjes WHERE verstuurd_op > now() - interval '{uur}'"),
]

KLEUREN = ["#E8836B", "#6B9BD1", "#E6B655", "#8BB37A", "#C98BB9", "#7FB8B0",
           "#D9A07A", "#9A8FD1", "#E0927F", "#86A8C9", "#B7C77A", "#D19A9A",
           "#A3B8E0", "#E0B3A3"]


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
    except Exception:
        return None
    finally:
        conn.close()


def verdiepingen(totaal):
    """Elke tien keer zoveel werk een verdieping: 0 is 1, 10 is 2, 100 is 3, tot 5."""
    if not totaal:
        return 1
    return max(1, min(5, int(math.log10(totaal)) + 1))


_BEWAARD = {"op": 0.0, "waarde": None}
BEWAAR_SECONDEN = 300


def stand(uur="1 hour", tel=None):
    """Alles voor het plaatje: per agent zijn huis, en het stadhuis.

    Vijf minuten bewaard (29 september): 24 tellingen op grote tabellen elke
    minuut, zolang de pagina open stond, maakte de rest van de site trager."""
    import time
    if tel is None:
        if _BEWAARD["waarde"] and time.time() - _BEWAARD["op"] < BEWAAR_SECONDEN:
            return _BEWAARD["waarde"]
        uit = _stand(uur, _tel)
        _BEWAARD.update(op=time.time(), waarde=uit)
        return uit
    return _stand(uur, tel)


def _stand(uur, tel):
    agents = []
    for i, (sleutel, naam, wat, sql_totaal, sql_uur) in enumerate(AGENTS):
        totaal = tel(sql_totaal)
        recent = tel(sql_uur.replace("{uur}", uur)) if sql_uur else None
        agents.append({"sleutel": sleutel, "naam": naam, "wat": wat, "totaal": totaal,
                       "recent": recent, "werkt": bool(recent), "hoog": verdiepingen(totaal),
                       "kleur": KLEUREN[i % len(KLEUREN)]})
    klanten = tel("SELECT count(*) FROM klanten WHERE NOT is_test AND opgezegd_op IS NULL") or 0
    return {"agents": agents, "klanten": klanten, "stadhuis": 1 + min(klanten, 20),
            "werkend": sum(1 for a in agents if a["werkt"])}
