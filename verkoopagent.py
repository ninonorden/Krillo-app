"""De verkoopagent: wie zijn Krillo-pagina bekeek, krijgt een persoonlijke opvolging.

WAAROM DIT BESTAAT (stap 125, 28 september). Van de 263 gemailde winkels
openden 24 hun pagina en ging er 1 naar de prijzen. Die 24 zijn de warmste
mensen die er zijn, en ze hoorden daarna niets meer. Deze agent volgt ze op.

WAT HIJ DOET
1. Zoekt winkels die hun pagina bekeken (bekeken_op), nog geen klant zijn,
   niet afgemeld en geen bounce hebben, en nog geen twee opvolgingen kregen.
   Eerste opvolging vanaf 2 uur na het bekijken (niet terwijl hij kijkt), de
   tweede 4 dagen na de eerste, en alleen als hij niet doorklikte naar de prijzen.
2. Schrijft een KORT, persoonlijk briefje: de ene vraag die hij verliest en
   die bij zijn winkel past (dezelfde keuze als de koude mail, vraagkeuze.py),
   wie daar wel genoemd werd, zijn plek, en wat eraan te doen is. Met een link
   naar zijn eigen pagina.
3. Zet het als concept klaar op /admin/verkoop. Nino keurt goed (Versturen) of
   slaat over. Na 20 goedgekeurde concepten mag hij de schakelaar "zelf
   versturen" aanzetten; dan gaat het binnen de kantooruren vanzelf.

REGELS DIE NOOIT LOSSEN: hoogstens twee opvolgingen, afmelden werkt altijd,
nooit buiten kantooruren, nooit naar een bounce of afgemelde winkel, en geen
verzonnen cijfers: alles komt uit dezelfde meting als de ranglijst.

De tekst is een vast sjabloon met zijn eigen gegevens, geen vrij geschreven
AI-tekst. Dat is met opzet: een AI die een verkoopmail schrijft kan iets
beloven dat niet klopt, en dit gaat naar echte winkeliers.
"""
import json
import os
from datetime import datetime, timezone, timedelta

import db

MAX_OPVOLGINGEN = 2
EERSTE_NA_UUR = 2
TWEEDE_NA_DAGEN = 4
PER_RONDE = int(os.environ.get("VERKOOP_PER_RONDE", "5"))
VRIJ_NA_GOEDGEKEURD = 20
SLEUTEL_ZELF = "verkoop_zelf_versturen"
SLEUTEL_TELLER = "verkoop_goedgekeurd"


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


def warme_winkels(limiet=50, nu=None):
    """Wie er nu aan de beurt is voor een (eerste of tweede) opvolging."""
    nu = nu or datetime.now(timezone.utc)
    return _sql("""
        SELECT b.webshop_url, b.naam, b.email, b.bekeken_op, b.doorgeklikt_op,
               b.opvolg_aantal, b.opvolg_op, b.opvolg_stand
          FROM benadering b
         WHERE b.bekeken_op IS NOT NULL
           AND b.email IS NOT NULL
           AND NOT b.afgemeld
           AND b.bounce_op IS NULL
           AND b.opvolg_aantal < %s
           AND (b.opvolg_stand IS NULL OR b.opvolg_stand NOT IN ('concept'))
           AND NOT EXISTS (SELECT 1 FROM klanten k WHERE k.webshop_url = b.webshop_url)
           AND (
                (b.opvolg_aantal = 0 AND b.bekeken_op < %s)
             OR (b.opvolg_aantal = 1 AND b.opvolg_op < %s AND b.doorgeklikt_op IS NULL)
           )
      ORDER BY b.bekeken_op DESC
         LIMIT %s""",
        (MAX_OPVOLGINGEN, nu - timedelta(hours=EERSTE_NA_UUR),
         nu - timedelta(days=TWEEDE_NA_DAGEN), limiet), alles=True) or []


def _kaal(url):
    return (url or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def maak_concept(winkel, beeld, vraag=None, link_url="", nummer=1, categorienaam=None):
    """Het briefje, als onderwerp plus alinea's. Geeft None als er niets eerlijks
    te zeggen valt (geen plek in de index)."""
    if not beeld or not beeld.get("positie"):
        return None
    naam = _kaal(winkel.get("webshop_url"))
    cat = categorienaam or beeld.get("categorie") or "your category"
    positie, van = beeld["positie"], beeld.get("van") or 0
    boven = [b.get("naam") or _kaal(b.get("webshop_url")) for b in (beeld.get("boven_mij") or [])][-2:]
    alineas = []
    if nummer == 1:
        onderwerp = f"{naam}: the one question you could win"
        alineas.append("Hi,")
        alineas.append(f"You looked at your Krillo page for {naam}. One thing stood out to me.")
    else:
        onderwerp = f"Re: {naam} in the Krillo index"
        alineas.append("Hi,")
        alineas.append(f"A short follow-up on {naam}.")
    if vraag and vraag.get("concurrenten"):
        wie = " and ".join(vraag["concurrenten"][:2])
        alineas.append(f"When shoppers ask AI <strong>\"{vraag['vraag']}\"</strong>, it names {wie}, not you.")
    alineas.append(f"You are #{positie} of {van} in {cat}."
                   + (f" The stores just above you are {' and '.join(boven)}." if boven and positie > 1 else ""))
    if positie == 1:
        alineas.append("Staying #1 is the hard part: we measure again every month, and the stores "
                       "below you are working on it.")
    elif nummer == 1:
        alineas.append("This is usually fixable within a few weeks. AI names stores whose pages answer "
                       "the question in plain words: fuller product descriptions, image descriptions, "
                       "and a questions page. With Fix we write those and put them in your store; with "
                       "Watch you get them written out to do yourself.")
    else:
        alineas.append("If it helps, just reply with a question. I look at every reply myself.")
    if nummer == 1:
        alineas.append("Your page shows every question you lose, with the real answer. "
                       "Questions? Just reply to this email.")
    return {"onderwerp": onderwerp, "alineas": alineas, "link": link_url, "nummer": nummer}


def _vraag_voor(webshop_url, beeld):
    """De verloren vraag die bij deze winkel past, zoals de koude mail die kiest."""
    vragen = (beeld or {}).get("gemiste_vragen") or []
    try:
        import vraagkeuze
        passend = vraagkeuze.passende_vragen(webshop_url, vragen)
        if passend:
            return passend[0]
    except Exception as e:
        print(f"Vraagkeuze voor opvolging mislukt voor {webshop_url}: {e}")
    return None


def zelf_versturen():
    return (db.get_instelling(SLEUTEL_ZELF) or "nee").lower() == "ja"


def aantal_goedgekeurd():
    try:
        return int(db.get_instelling(SLEUTEL_TELLER) or 0)
    except Exception:
        return 0


def concepten():
    """Alle concepten die op goedkeuring wachten."""
    rijen = _sql("""SELECT webshop_url, naam, email, opvolg_aantal, opvolg_concept, bekeken_op
                      FROM benadering WHERE opvolg_stand = 'concept'
                  ORDER BY bekeken_op DESC""", alles=True) or []
    for r in rijen:
        try:
            r["concept"] = json.loads(r.get("opvolg_concept") or "{}")
        except Exception:
            r["concept"] = {}
    return rijen


def verstuur(webshop_url, basis_url):
    """Een concept versturen. Geeft True bij succes."""
    import emailing
    rij = _sql("SELECT email, opvolg_concept, opvolg_aantal, afgemeld FROM benadering "
               "WHERE webshop_url = %s", (webshop_url,))
    if not rij or rij.get("afgemeld") or not rij.get("email"):
        return False
    concept = json.loads(rij.get("opvolg_concept") or "{}")
    token = db.get_benchmark_token(webshop_url)
    afmeld = f"{basis_url}/afmelden/{token}" if token else None
    gelukt = emailing.send_opvolging(rij["email"], concept.get("onderwerp"), concept.get("alineas"),
                                     concept.get("link"), afmeld_url=afmeld)
    if gelukt:
        _sql("""UPDATE benadering SET opvolg_aantal = opvolg_aantal + 1, opvolg_op = now(),
                                      opvolg_stand = 'verstuurd' WHERE webshop_url = %s""",
             (webshop_url,))
    return gelukt


def keur_goed(webshop_url, basis_url):
    gelukt = verstuur(webshop_url, basis_url)
    if gelukt:
        db.zet_instelling(SLEUTEL_TELLER, str(aantal_goedgekeurd() + 1))
    return gelukt


def sla_over(webshop_url):
    # Overslaan telt als een opvolging, zodat hij niet elke ronde terugkomt.
    _sql("""UPDATE benadering SET opvolg_aantal = opvolg_aantal + 1, opvolg_op = now(),
                                  opvolg_stand = 'overgeslagen' WHERE webshop_url = %s""",
         (webshop_url,))


def ronde(basis_url, bouw_beeld, categorienaam=None, binnen_kantooruren=True):
    """Een ronde: concepten maken voor wie aan de beurt is, en (als dat aanstaat)
    versturen. Geeft een kort verslag."""
    verslag = {"concepten": 0, "verstuurd": 0, "overgeslagen": 0}
    for w in warme_winkels(limiet=PER_RONDE):
        url = w["webshop_url"]
        try:
            beeld = bouw_beeld(url)
        except Exception as e:
            print(f"Opvolging: beeld mislukt voor {url}: {e}")
            beeld = None
        token = db.get_benchmark_token(url)
        concept = maak_concept(w, beeld, _vraag_voor(url, beeld) if beeld else None,
                               link_url=f"{basis_url}/uitkomst/{token}" if token else basis_url,
                               nummer=(w.get("opvolg_aantal") or 0) + 1,
                               categorienaam=categorienaam(beeld) if (categorienaam and beeld) else None)
        if not concept:
            sla_over(url)
            verslag["overgeslagen"] += 1
            continue
        _sql("UPDATE benadering SET opvolg_concept = %s, opvolg_stand = 'concept' WHERE webshop_url = %s",
             (json.dumps(concept), url))
        verslag["concepten"] += 1
        if zelf_versturen() and binnen_kantooruren:
            if verstuur(url, basis_url):
                verslag["verstuurd"] += 1
    return verslag
