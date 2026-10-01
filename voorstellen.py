"""Voorstellen ter akkoord: wat de agents willen doen, en Nino zegt ja of nee (1 oktober 2026).

WAAROM DIT BESTAAT. Nino: "dat groei automatisch wordt gedaan en ik alleen hoef
te checken en akkoord hoef te geven. Dit moet allemaal in het ochtendbericht."
Tot nu toe stonden voorstellen van de leeragent als een losse zin in het
ochtendbericht, en een schakelaar omzetten betekende een instelling in Render
zoeken (BUREAUMAIL_AUTO=1) of eerst twintig concepten met de hand goedkeuren.
Nu is elk voorstel een rij met een eigen link: een tik op "akkoord" en het
gebeurt.

DRIE SOORTEN, met elk een eerlijke uitkomst van "akkoord":
- "actie": een vaste, vooraf gebouwde handeling (zie ACTIES). Akkoord voert hem
  meteen uit, bijvoorbeeld: de verkoopagent mag zijn opvolgingen zelf versturen.
  Een agent kan alleen kiezen uit deze lijst; hij kan geen nieuwe handeling
  verzinnen. Zo kan een fout in een AI-antwoord nooit iets doen wat niet
  ontworpen en getest is.
- "taak": iets wat alleen een mens kan (een aanmelding bij een gids, een post
  in een groep). Akkoord betekent "ik doe het"; daarna "gedaan".
- "bouwen": een nieuwe functie voor Krillo. Code schrijft zichzelf niet: akkoord
  zet hem op de bouwlijst, en Claude bouwt hem in de volgende sessie. Op
  /admin/voorstellen staat de tekst om aan Claude te geven.

REGELS DIE NOOIT LOSSEN
- Hetzelfde voorstel staat er nooit twee keer open (sleutel).
- Een "nee" komt 30 dagen niet terug. Nee betekent nee.
- De link in de mail doet niets bij openen: hij toont een knop. Mailprogramma's
  en virusscanners openen links vooraf; die mogen niets goedkeuren.
"""
import hashlib
import json
import secrets

import db

SOORTEN = ("actie", "taak", "bouwen")
NEE_DAGEN = 30

# Wat Claude gebouwd heeft, op sleutel. Bij de volgende start gaan deze van
# "akkoord" naar "gebouwd": ze verdwijnen van de bouwlijst en komen nooit terug.
# Zo hoeft Nino niets af te vinken; de zip met het werk doet het.
# Taken die Nino al deed en ons vertelde (zelfde werking als GEBOUWD, maar 'gedaan').
AL_GEDAAN = {
    "gids:saashub": "Nino, 1 oktober 2026: al aangemeld bij SaaSHub",
}

GEBOUWD = {
    "uitbreiding:198": "1 oktober 2026: wekelijkse snelmeting (snelmeting.py, dashboard, /admin/snelmeting)",
}


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
                return [dict(r) for r in cur.fetchall()] if alles else (
                    dict(cur.fetchone()) if cur.rowcount else None)
    finally:
        conn.close()


def maak_tabel():
    _sql("""CREATE TABLE IF NOT EXISTS voorstellen (
                id SERIAL PRIMARY KEY,
                sleutel TEXT NOT NULL,
                bron TEXT NOT NULL,
                soort TEXT NOT NULL,
                titel TEXT NOT NULL,
                waarom TEXT,
                actie TEXT,
                minuten INTEGER,
                stand TEXT NOT NULL DEFAULT 'open',
                token TEXT UNIQUE NOT NULL,
                uitkomst TEXT,
                aangemaakt_op TIMESTAMPTZ NOT NULL DEFAULT now(),
                besloten_op TIMESTAMPTZ)""")
    _sql("CREATE INDEX IF NOT EXISTS voorstellen_sleutel ON voorstellen (sleutel)")
    for sleutel, wat in AL_GEDAAN.items():
        _sql("""UPDATE voorstellen SET stand = 'gedaan', uitkomst = %s, besloten_op = coalesce(besloten_op, now())
                WHERE sleutel = %s AND stand IN ('open', 'akkoord')""", (wat, sleutel))
    for sleutel, wat in GEBOUWD.items():
        _sql("""UPDATE voorstellen SET stand = 'gebouwd', uitkomst = %s, besloten_op = coalesce(besloten_op, now())
                WHERE sleutel = %s AND stand IN ('open', 'akkoord')""", (wat, sleutel))


def sleutel_van(tekst):
    """Een vaste sleutel uit een vrije tekst, zodat dezelfde zin niet twee keer komt."""
    kaal = " ".join((tekst or "").lower().split())
    return "t:" + hashlib.sha1(kaal.encode("utf-8")).hexdigest()[:16]


def stel_voor(bron, soort, titel, waarom=None, actie=None, sleutel=None, minuten=None):
    """Zet een voorstel klaar. Geeft de rij, of None als hij er al staat of kort
    geleden nee kreeg (of als de soort of actie niet bestaat)."""
    if soort not in SOORTEN or not (titel or "").strip():
        return None
    if soort == "actie" and actie not in ACTIES:
        return None
    maak_tabel()
    sleutel = sleutel or (f"actie:{actie}" if soort == "actie" else sleutel_van(titel))
    if sleutel in GEBOUWD or sleutel in AL_GEDAAN:
        return None
    bestaand = _sql(f"""SELECT id FROM voorstellen WHERE sleutel = %s
                          AND (stand IN ('open', 'akkoord')
                               OR (stand = 'nee' AND besloten_op > now() - interval '{int(NEE_DAGEN)} days')
                               OR (soort <> 'actie' AND stand IN ('gedaan', 'uitgevoerd', 'gebouwd')))
                        LIMIT 1""", (sleutel,))
    if bestaand:
        return None
    return _sql("""INSERT INTO voorstellen (sleutel, bron, soort, titel, waarom, actie, minuten, token)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (sleutel, bron[:40], soort, titel.strip()[:400], (waarom or "")[:800] or None, actie,
                 minuten, secrets.token_urlsafe(24)))


def open_voorstellen(soort=None):
    maak_tabel()
    if soort:
        return _sql("SELECT * FROM voorstellen WHERE stand = 'open' AND soort = %s ORDER BY aangemaakt_op",
                    (soort,), alles=True) or []
    return _sql("SELECT * FROM voorstellen WHERE stand = 'open' ORDER BY aangemaakt_op", alles=True) or []


def bouwlijst():
    """Goedgekeurde functies die nog gebouwd moeten worden."""
    maak_tabel()
    return _sql("SELECT * FROM voorstellen WHERE soort = 'bouwen' AND stand = 'akkoord' ORDER BY besloten_op",
                alles=True) or []


def lopende_taken():
    """Taken waar Nino ja op zei maar die nog niet gedaan zijn."""
    maak_tabel()
    return _sql("SELECT * FROM voorstellen WHERE soort = 'taak' AND stand = 'akkoord' ORDER BY besloten_op",
                alles=True) or []


def geschiedenis(limiet=40):
    maak_tabel()
    return _sql("SELECT * FROM voorstellen WHERE stand <> 'open' ORDER BY besloten_op DESC NULLS LAST LIMIT %s",
                (int(limiet),), alles=True) or []


def bij_token(token):
    maak_tabel()
    return _sql("SELECT * FROM voorstellen WHERE token = %s", (token,)) if token else None


def beslis(token, keuze):
    """keuze: 'akkoord', 'nee' of 'gedaan'. Geeft (gelukt, melding)."""
    v = bij_token(token)
    if not v:
        return False, "Dit voorstel bestaat niet (meer)."
    if sleutel_gebouwd(v):
        return False, "Dit is al gebouwd."
    if keuze == "gedaan":
        if v["stand"] not in ("open", "akkoord") or v["soort"] == "actie":
            return False, "Dit voorstel kan niet op gedaan."
        _sql("UPDATE voorstellen SET stand = 'gedaan', besloten_op = now() WHERE id = %s", (v["id"],))
        return True, "Op gedaan gezet. Dank je."
    if v["stand"] != "open":
        return False, f"Hier is al over beslist ({v['stand']})."
    if keuze == "nee":
        _sql("UPDATE voorstellen SET stand = 'nee', besloten_op = now() WHERE id = %s", (v["id"],))
        return True, f"Genoteerd: nee. Dit komt de komende {NEE_DAGEN} dagen niet terug."
    if keuze != "akkoord":
        return False, "Onbekende keuze."
    if v["soort"] == "actie":
        actie = ACTIES.get(v["actie"])
        if not actie:
            return False, "Deze handeling bestaat niet meer."
        try:
            uitkomst = actie["doe"]()
        except Exception as e:
            return False, f"Uitvoeren mislukt: {e}"
        _sql("UPDATE voorstellen SET stand = 'uitgevoerd', besloten_op = now(), uitkomst = %s WHERE id = %s",
             (str(uitkomst)[:500], v["id"]))
        return True, f"Gedaan: {uitkomst}"
    _sql("UPDATE voorstellen SET stand = 'akkoord', besloten_op = now() WHERE id = %s", (v["id"],))
    if v["soort"] == "bouwen":
        return True, "Op de bouwlijst. Claude bouwt het in de volgende sessie; de tekst staat op /admin/voorstellen."
    return True, "Akkoord. De taak staat in je dagtaken tot je hem op gedaan zet."


def sleutel_gebouwd(v):
    return (v or {}).get("sleutel") in GEBOUWD


def tekst_voor_claude(rijen=None):
    """De bouwlijst als een tekst om in een gesprek met Claude te plakken."""
    rijen = bouwlijst() if rijen is None else rijen
    if not rijen:
        return ""
    regels = ["Bouw deze goedgekeurde voorstellen voor Krillo (uit /admin/voorstellen):"]
    for i, r in enumerate(rijen, 1):
        regels.append(f"{i}. {r['titel']}" + (f" Waarom: {r['waarom']}" if r.get("waarom") else ""))
    return "\n".join(regels)


# --------------------------------------------------------------- de handelingen
# Alles wat een "actie" mag doen. Een agent kiest hieruit, verzint niets.

def _verkoop_zelf():
    import verkoopagent as va
    db.zet_instelling(va.SLEUTEL_ZELF, "ja")
    return "de verkoopagent verstuurt zijn opvolgingen nu zelf, binnen kantooruren"


def _bureau_auto():
    import bureauvinder
    db.zet_instelling(bureauvinder.SLEUTEL_AUTO, "ja")
    return f"de bureau-agent mailt nu zelf, hoogstens {bureauvinder.AUTO_PER_DAG} bureaus per dag"


def _opbouw_hoger():
    import benadering
    oud = benadering.opbouw_doel()
    nieuw = min(benadering.OPBOUW_MAX, oud + 20)
    db.zet_instelling(benadering.SLEUTEL_OPBOUW_DOEL, str(nieuw))
    return f"het doel van de koude mail gaat van {oud} naar {nieuw} per dag, stap voor stap per week"


ACTIES = {
    "verkoop_zelf": {"naam": "Verkoopagent verstuurt zelf", "doe": _verkoop_zelf},
    "bureau_auto": {"naam": "Bureau-agent mailt zelf", "doe": _bureau_auto},
    "opbouw_hoger": {"naam": "Meer koude mail per dag", "doe": _opbouw_hoger},
}


def als_json(rij):
    """Voor een pagina of test: datums als tekst."""
    return json.loads(json.dumps(rij, default=str))
