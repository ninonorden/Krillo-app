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
           -- 29 september: alleen wie er als MENS was (scrollen, tikken, muis).
           -- Mailbeveiliging opent elke link om hem te controleren, en die kreeg
           -- anders een opvolgmail. Openingen van voor de menstelling
           -- aanstond tellen zoals vroeger, anders valt iedereen van toen weg.
           AND (b.mens_op IS NOT NULL
                OR b.bekeken_op < coalesce((SELECT min(gezien_op) FROM bezoek_mensen), now()))
           AND b.email IS NOT NULL
           AND NOT b.afgemeld
           AND b.bounce_op IS NULL
           -- Wie terugmailde, is in gesprek met een mens (stap 126).
           AND b.antwoord_op IS NULL
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


# ZELFVERBETERING (blok E, 28 september). Twee versies van de uitleg lopen
# naast elkaar; het scorebord telt per versie hoeveel mensen daarna
# doorklikten naar de prijzen. Na MIN_PER_VERSIE verstuurde briefjes per versie
# en een duidelijk verschil wint de beste vanzelf, en krijgt iedereen die.
# Nieuwe uitdagers schrijven gebeurt (nog) niet vanzelf: een nieuwe tekst gaat
# eerst langs Nino, want dit zijn echte mails aan echte winkeliers.
VERSIES = {
    "a": ("This is usually fixable within a few weeks. AI names stores whose pages answer "
          "the question in plain words: fuller product descriptions, image descriptions, "
          "and a questions page. With Fix we write those and put them in your store; with "
          "Watch you get them written out to do yourself."),
    "b": ("The stores AI names have one thing in common: their product pages answer the "
          "shopper's question in plain words. We can write that for your products and, with "
          "Fix, put it in your store for you. Every change keeps the old text, so nothing is "
          "lost."),
}
MIN_PER_VERSIE = 30
SLEUTEL_WINNAAR = "verkoop_winnaar"


# ZELFVERBETERING DEEL 2 (stap 96 en 153, 28 september). Zodra er een winnaar
# is, schrijft de leeragent (leeragent.py) een UITDAGER: een nieuwe versie van
# dezelfde alinea, na onderzoek, langs de controleagent. Die loopt naast de
# winnaar. Wint hij op dezelfde regels (genoeg briefjes, duidelijk verschil),
# dan wordt hij de nieuwe winnaar; verliest hij, dan schrijft de leeragent een
# nieuwe. Zo wordt de mail maand op maand beter, en gaat er nooit een versie
# live die aantoonbaar slechter is. Nino ziet elke tekst zolang "zelf
# versturen" uit staat.
SLEUTEL_UITDAGER = "verkoop_uitdager"
SLEUTEL_EXTRA = "verkoop_versies_extra"


def _extra():
    try:
        return json.loads(db.get_instelling(SLEUTEL_EXTRA) or "{}")
    except Exception:
        return {}


def uitdager():
    """{"versie": "u1", "tekst": ...} of None."""
    try:
        u = json.loads(db.get_instelling(SLEUTEL_UITDAGER) or "null")
    except Exception:
        return None
    return u if isinstance(u, dict) and u.get("versie") and u.get("tekst") else None


def versie_tekst(versie):
    if versie in VERSIES:
        return VERSIES[versie]
    u = uitdager()
    if u and u["versie"] == versie:
        return u["tekst"]
    return _extra().get(versie) or VERSIES["a"]


def kies_versie(webshop_url):
    import hashlib
    getal = int(hashlib.sha256((webshop_url or "").encode()).hexdigest(), 16)
    winnaar = db.get_instelling(SLEUTEL_WINNAAR)
    if winnaar and (winnaar in VERSIES or winnaar in _extra()):
        u = uitdager()
        if u:
            return (winnaar, u["versie"])[getal % 2]
        return winnaar
    return "ab"[getal % 2]


def beslis_uitdager():
    """Winnaar tegen uitdager, met dezelfde regels als a tegen b. Geeft
    "uitdager_wint", "winnaar_blijft" of None (nog niet genoeg bewijs)."""
    winnaar, u = db.get_instelling(SLEUTEL_WINNAAR), uitdager()
    if not winnaar or not u:
        return None
    bord = {r["versie"]: r for r in scorebord()}
    w, c = bord.get(winnaar), bord.get(u["versie"])
    if not w or not c or w["verstuurd"] < MIN_PER_VERSIE or c["verstuurd"] < MIN_PER_VERSIE:
        return None
    verschil = c["score"] - w["score"]
    if verschil >= 0.05 and (c["doorgeklikt"] + c["klant"]) - (w["doorgeklikt"] + w["klant"]) >= 3:
        extra = _extra()
        extra[u["versie"]] = u["tekst"]
        db.zet_instelling(SLEUTEL_EXTRA, json.dumps(extra))
        db.zet_instelling(SLEUTEL_WINNAAR, u["versie"])
        db.zet_instelling(SLEUTEL_UITDAGER, "")
        return "uitdager_wint"
    if -verschil >= 0.05 or c["verstuurd"] >= 3 * MIN_PER_VERSIE:
        # Duidelijk slechter, of na drie keer zoveel briefjes nog geen verschil:
        # plaats maken voor een nieuwe uitdager.
        db.zet_instelling(SLEUTEL_UITDAGER, "")
        return "winnaar_blijft"
    return None


def scorebord():
    """Per versie: verstuurd, doorgeklikt na de opvolging, betaald."""
    rijen = _sql("""SELECT opvolg_variant AS versie, count(*) AS verstuurd,
                           count(*) FILTER (WHERE doorgeklikt_op > opvolg_op) AS doorgeklikt,
                           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM klanten k
                                            WHERE k.webshop_url = benadering.webshop_url)) AS klant
                      FROM benadering
                     WHERE opvolg_variant IS NOT NULL AND opvolg_stand = 'verstuurd'
                  GROUP BY opvolg_variant ORDER BY opvolg_variant""", alles=True) or []
    for r in rijen:
        r["score"] = (r["doorgeklikt"] + 3 * r["klant"]) / r["verstuurd"] if r["verstuurd"] else 0
    return rijen


def kies_winnaar():
    """Kiest vanzelf de betere versie zodra er genoeg bewijs is. Geeft de winnaar of None."""
    # Is er al een winnaar, dan beslist beslis_uitdager verder. Anders zou een
    # latere a-tegen-b-telling een uitdager die al won weer terugzetten.
    if db.get_instelling(SLEUTEL_WINNAAR):
        return None
    bord = {r["versie"]: r for r in scorebord()}
    if not all(v in bord and bord[v]["verstuurd"] >= MIN_PER_VERSIE for v in VERSIES):
        return None
    a, b = bord["a"], bord["b"]
    # Pas een winnaar als het verschil minstens 5 procentpunt is en minstens 3 mensen.
    verschil = a["score"] - b["score"]
    if abs(verschil) >= 0.05 and abs((a["doorgeklikt"] + a["klant"]) - (b["doorgeklikt"] + b["klant"])) >= 3:
        winnaar = "a" if verschil > 0 else "b"
        db.zet_instelling(SLEUTEL_WINNAAR, winnaar)
        return winnaar
    return None


def maak_concept(winkel, beeld, vraag=None, link_url="", nummer=1, categorienaam=None, versie="a",
                 aanleiding="pagina"):
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
        # Het onderwerp belooft alleen wat erin staat (28 september: een
        # nummer 1 kreeg "the one question you could win" zonder vraag).
        if positie == 1:
            onderwerp = f"{naam}: #1 in {cat}, and how to keep it"
        elif vraag and vraag.get("concurrenten"):
            onderwerp = f"{naam}: the one question you could win"
        else:
            onderwerp = f"{naam}: #{positie} of {van} in {cat}"
        alineas.append("Hi,")
        # Stap 118: dezelfde brief voor wie de gratis check deed. Die bekeek
        # geen pagina, dus dat zeggen we dan ook niet.
        if aanleiding == "check":
            alineas.append(f"A few days ago you checked {naam} with Krillo. One thing stood out to me.")
        else:
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
        alineas.append(versie_tekst(versie))
    else:
        alineas.append("If it helps, just reply with a question. I look at every reply myself.")
    if nummer == 1:
        # Stap 167: de gratis proef is de kleinste stap die er is; zeg het.
        alineas.append("Your page shows every question you lose, with the real answer. "
                       "You can try Watch free for 14 days. Questions? Just reply to this email.")
    return {"onderwerp": onderwerp, "alineas": alineas, "link": link_url, "nummer": nummer,
            "versie": versie}


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
                                      opvolg_stand = 'verstuurd', opvolg_variant = %s
                 WHERE webshop_url = %s""", (concept.get("versie"), webshop_url))
    return gelukt


def schrijf_opnieuw(webshop_url):
    """Het concept weggooien; de volgende ronde schrijft een nieuw (met de nieuwste tekst)."""
    _sql("UPDATE benadering SET opvolg_stand = NULL, opvolg_concept = NULL WHERE webshop_url = %s",
         (webshop_url,))


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
    try:
        verslag["winnaar"] = kies_winnaar()
        verslag["uitdager"] = beslis_uitdager()
    except Exception as e:
        print(f"Winnaar kiezen mislukt: {e}")
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
                               categorienaam=categorienaam(beeld) if (categorienaam and beeld) else None,
                               versie=kies_versie(url))
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


def maak_maandbericht(beeld, link_url="", categorienaam=None):
    """Stap 118, de derde mail na de gratis check: zijn nieuwe plek na de
    maandmeting. Alleen echte beweging of een eerlijk "gelijk gebleven"; geen
    reclametekst erbij, want dit is nieuws, en nieuws wordt gelezen."""
    if not beeld or not beeld.get("positie"):
        return None
    naam = _kaal(beeld.get("webshop_url"))
    cat = categorienaam or beeld.get("categorie") or "your category"
    nu, van, vorige = beeld["positie"], beeld.get("van") or 0, beeld.get("vorige_positie")
    if vorige and vorige > nu:
        onderwerp = f"{naam} moved up: #{nu} in {cat}"
        zin = f"In this month's measurement {naam} went from #{vorige} to <strong>#{nu}</strong> of {van} in {cat}."
    elif vorige and vorige < nu:
        onderwerp = f"{naam} dropped to #{nu} in {cat}"
        zin = f"In this month's measurement {naam} went from #{vorige} to <strong>#{nu}</strong> of {van} in {cat}."
    else:
        onderwerp = f"{naam}: #{nu} in {cat} this month"
        zin = f"In this month's measurement {naam} is <strong>#{nu}</strong> of {van} in {cat}."
    alineas = ["Hi,", zin]
    boven = [b.get("naam") or _kaal(b.get("webshop_url")) for b in (beeld.get("boven_mij") or [])][-2:]
    if nu == 1:
        alineas.append("You are the store AI names first. We measure again next month.")
    elif boven:
        alineas.append(f"Just above you: {' and '.join(boven)}.")
    alineas.append("Your page has every question and the real answers. Questions? Just reply.")
    return {"onderwerp": onderwerp, "alineas": alineas, "link": link_url, "nummer": 3, "versie": None}


def formulier_bericht(beeld, vraag=None, link_url="", categorienaam=None):
    """Stap 156: het bericht dat Nino in een contactformulier plakt, bij een
    winkel zonder info@. Platte tekst (een formulier kent geen opmaak), kort,
    en met dezelfde eerlijke feiten als de koude mail. Geeft None zonder plek."""
    if not beeld or not beeld.get("positie"):
        return None
    naam = _kaal(beeld.get("webshop_url"))
    cat = categorienaam or beeld.get("categorie") or "your category"
    regels = ["Hi,", ""]
    regels.append(f"I run Krillo. Every month we ask ChatGPT and Gemini the questions shoppers ask "
                  f"in {cat}, and see which stores they name.")
    if vraag and vraag.get("concurrenten"):
        wie = " and ".join(vraag["concurrenten"][:2])
        regels.append(f"When someone asks \"{vraag['vraag']}\", AI names {wie}, not {naam}.")
    regels.append(f"{naam} is #{beeld['positie']} of {beeld.get('van') or '?'} in {cat} right now.")
    regels += ["", f"Your own page, with every question and the real answers (free): {link_url}", "",
               "No need to reply if it is not for you. We will not contact you again.", "", "Nino, Krillo"]
    return "\n".join(regels)
