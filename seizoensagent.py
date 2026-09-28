"""De seizoensagent: vlak voor elk koopmoment een eerlijke mail, per land en per categorie.

WAAROM DIT BESTAAT (stap 151, 28 september). Een winkel die al een koude mail
kreeg en niets deed, is niet "nee"; het was geen goed moment. Vlak voor een
koopmoment (Sinterklaas, Kerst, Moederdag) is het wel een goed moment:
dan vragen kopers AI waar ze moeten kopen, en een winkelier denkt precies dan
na over zijn verkoop. Nino: "voor alles gelijk goed gezet, automatisch, ook
voor holidays van andere landen".

HOE HET WERKT
- KALENDER hieronder: elk moment met per land de datum (vast, "tweede zondag
  van mei", of op Pasen gebaseerd, elk jaar opnieuw uitgerekend), hoeveel
  dagen van tevoren wij mailen, en voor welke categorieen het past. Moederdag
  past bij sieraden en parfum, niet bij gereedschap.
- Elke ronde: welke momenten hebben NU hun mailvenster open (vanaf "dagen van
  tevoren", twee weken lang)? Welke winkels in dat land en die categorie
  kregen eerder een koude mail, deden niets, en hoorden al 45 dagen niets van
  ons? Die krijgen een korte mail met hun eigen plek en de vraag die ze
  verliezen.

REGELS DIE NOOIT LOSSEN
- Alleen winkels die al een koude mail kregen, minstens 14 dagen geleden.
- Hoogstens een seizoensmail per 45 dagen per winkel, en per moment maar een keer.
- Nooit naar afgemeld, bounce, klacht, klant, of wie terugmailde (die is in
  gesprek met een mens).
- Alleen binnen kantooruren en als de benadering aanstaat; een eigen dagmaximum.
- Geen verzonnen seizoenscijfers: de mail noemt de datum van het moment en de
  echte plek en vraag uit de maandmeting, niets anders.

Momenten op de maankalender (Ramadan, Suikerfeest, Chinees Nieuwjaar, Diwali)
staan er nog niet in: die verschuiven elk jaar op een manier die je niet
betrouwbaar met een formule uitrekent. Die komen erbij met een vaste tabel per
jaar zodra er een land bij komt waar ze ertoe doen.
"""
import os
from datetime import date, datetime, timedelta, timezone

import db

PER_RONDE = int(os.environ.get("SEIZOEN_PER_RONDE", "5"))
PER_DAG = int(os.environ.get("SEIZOEN_PER_DAG", "20"))
VENSTER_DAGEN = 14
RUST_DAGEN = 45
NA_KOUDE_MAIL_DAGEN = 14


# ------------------------------------------------------------- datums

def pasen(jaar):
    """Paaszondag (algoritme van Meeus/Jones/Butcher, gregoriaans)."""
    a, b, c = jaar % 19, jaar // 100, jaar % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    maand = (h + l_ - 7 * m + 114) // 31
    dag = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(jaar, maand, dag)


def nde_weekdag(jaar, maand, weekdag, n):
    """De n-de weekdag (maandag 0) van een maand; n = -1 is de laatste."""
    if n > 0:
        d = date(jaar, maand, 1)
        d += timedelta(days=(weekdag - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    volgende = date(jaar + (maand == 12), maand % 12 + 1, 1)
    d = volgende - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekdag) % 7)


ZO, DO = 6, 3


def _vast(maand, dag):
    return lambda j: date(j, maand, dag)


def _koningsdag(j):
    d = date(j, 4, 27)
    return d - timedelta(days=1) if d.weekday() == ZO else d


def _fete_des_meres(j):
    # Laatste zondag van mei; valt die op Pinksteren, dan de eerste van juni.
    d = nde_weekdag(j, 5, ZO, -1)
    return d + timedelta(weeks=1) if d == pasen(j) + timedelta(days=49) else d


# ------------------------------------------------------------- categorieen

CADEAU = {"sieraden", "horloges", "parfum", "cosmetica", "cosmetica-natuurlijk", "huidverzorging",
          "makeup", "scheren-baard", "tassen-lederwaren", "kleding", "kleding-dames", "kleding-heren",
          "kleding-kinderen", "kleding-duurzaam", "schoenen", "speelgoed", "speelgoed-educatief",
          "kraamcadeaus", "boeken", "audio", "gaming", "elektronica", "wijn-drank", "chocolade-snoep",
          "delicatessen", "koffie-thee", "kunst-posters", "woondecoratie", "hobby-knutselen",
          "breien-haken", "keuken-servies", "kookgerei", "beddengoed-textiel", "verlichting",
          "kamerplanten", "schrijfwaren-kantoor", "muziekinstrumenten", "erotiek", "sport-fitness",
          "hardlopen", "yoga", "wielrennen", "outdoor-kamperen", "gereedschap", "slim-huis",
          "telefoon-accessoires", "computers-accessoires", "reizen-bagage"}
ALLES = "alle"  # elke categorie behalve overig

MOEDER = {"sieraden", "horloges", "parfum", "cosmetica", "cosmetica-natuurlijk", "huidverzorging",
          "makeup", "kleding-dames", "tassen-lederwaren", "woondecoratie", "beddengoed-textiel",
          "koffie-thee", "delicatessen", "chocolade-snoep", "boeken", "kamerplanten", "tuin",
          "keuken-servies", "kunst-posters", "hobby-knutselen", "yoga", "wijn-drank"}
VADER = {"horloges", "gereedschap", "scheren-baard", "wijn-drank", "audio", "gaming", "elektronica",
         "sport-fitness", "hardlopen", "wielrennen", "fietsonderdelen", "outdoor-kamperen",
         "auto-accessoires", "boeken", "kleding-heren", "koffie-thee", "delicatessen", "slim-huis",
         "tassen-lederwaren", "watersport"}
KINDEREN = {"speelgoed", "speelgoed-educatief", "boeken", "gaming", "chocolade-snoep", "hobby-knutselen",
            "kleding-kinderen", "schrijfwaren-kantoor", "kraamcadeaus", "sport-fitness", "audio"}


# ------------------------------------------------------------- de kalender
# sleutel: (naam in het Engels, {land: datumfunctie}, dagen van tevoren, categorieen)
KALENDER = {
    "nieuwjaar": ("New Year", {l: _vast(1, 1) for l in ("nl", "be", "de", "fr", "gb", "us")}, 28,
                  {"sport-fitness", "hardlopen", "yoga", "supplementen", "boeken", "zerowaste"}),
    "valentijn": ("Valentine's Day", {l: _vast(2, 14) for l in ("nl", "be", "de", "fr", "gb", "us")}, 28,
                  {"sieraden", "horloges", "parfum", "cosmetica", "cosmetica-natuurlijk", "huidverzorging",
                   "makeup", "chocolade-snoep", "wijn-drank", "erotiek", "kleding-dames", "kleding-heren",
                   "tassen-lederwaren", "kunst-posters", "delicatessen"}),
    "pasen": ("Easter", {l: pasen for l in ("nl", "be", "de", "fr", "gb", "us")}, 28,
              {"chocolade-snoep", "delicatessen", "woondecoratie", "speelgoed", "speelgoed-educatief",
               "feestartikelen", "kamerplanten", "tuin", "hobby-knutselen", "kleding-kinderen",
               "keuken-servies"}),
    "tuinseizoen": ("the start of the garden season", {l: _vast(4, 1) for l in ("nl", "be", "de", "fr", "gb")},
                    35, {"tuin", "zaden-bloembollen", "kamerplanten", "outdoor-kamperen", "gereedschap"}),
    "koningsdag": ("King's Day", {"nl": _koningsdag}, 21, {"feestartikelen", "kleding", "wijn-drank"}),
    "moederdag": ("Mother's Day", {
        "nl": lambda j: nde_weekdag(j, 5, ZO, 2), "be": lambda j: nde_weekdag(j, 5, ZO, 2),
        "de": lambda j: nde_weekdag(j, 5, ZO, 2), "us": lambda j: nde_weekdag(j, 5, ZO, 2),
        "gb": lambda j: pasen(j) - timedelta(days=21), "fr": _fete_des_meres}, 28, MOEDER),
    "vaderdag": ("Father's Day", {
        "nl": lambda j: nde_weekdag(j, 6, ZO, 3), "be": lambda j: nde_weekdag(j, 6, ZO, 2),
        "gb": lambda j: nde_weekdag(j, 6, ZO, 3), "us": lambda j: nde_weekdag(j, 6, ZO, 3),
        "fr": lambda j: nde_weekdag(j, 6, ZO, 3), "de": lambda j: pasen(j) + timedelta(days=39)}, 28, VADER),
    "zomervakantie": ("the summer holidays", {
        "nl": _vast(7, 12), "be": _vast(7, 1), "de": _vast(7, 15), "fr": _vast(7, 5),
        "gb": _vast(7, 22), "us": _vast(6, 20)}, 42,
        {"reizen-bagage", "outdoor-kamperen", "watersport", "schoenen", "kleding", "cosmetica",
         "huidverzorging", "fietsonderdelen", "wielrennen"}),
    "terugnaarschool": ("back to school", {
        "nl": _vast(8, 24), "be": _vast(9, 1), "fr": _vast(9, 1), "de": _vast(8, 20),
        "gb": _vast(9, 3), "us": _vast(8, 20)}, 35,
        {"schrijfwaren-kantoor", "tassen-lederwaren", "kleding-kinderen", "schoenen",
         "computers-accessoires", "telefoon-accessoires", "elektronica", "boeken", "speelgoed-educatief"}),
    "halloween": ("Halloween", {l: _vast(10, 31) for l in ("nl", "be", "de", "fr", "gb", "us")}, 28,
                  {"feestartikelen", "chocolade-snoep", "kleding-kinderen", "woondecoratie", "hobby-knutselen"}),
    "singlesday": ("Singles' Day", {l: _vast(11, 11) for l in ("nl", "be", "de", "fr", "gb", "us")}, 28,
                   {"elektronica", "audio", "gaming", "computers-accessoires", "telefoon-accessoires",
                    "kleding", "kleding-dames", "kleding-heren", "schoenen", "cosmetica", "makeup"}),
    # Black Friday bewust NIET (Nino, 28 september): in Nederland en Belgie
    # klein en vooral Amerikaans, en daar zitten wij (nog) niet.
    "sinterklaas": ("Sinterklaas", {"nl": _vast(12, 5), "be": _vast(12, 6)}, 42, KINDEREN),
    "kerst": ("Christmas", {l: _vast(12, 25) for l in ("nl", "be", "de", "fr", "gb", "us")}, 42,
              CADEAU | {"feestartikelen", "woondecoratie", "verlichting"}),
}


def past(categorie, cats):
    """Past dit moment bij deze categorie (of de bovenliggende)?"""
    if not categorie or categorie == "overig":
        return False
    if cats == ALLES:
        return True
    try:
        import categorieen
        ouder = categorieen.OUDER.get(categorie)
    except Exception:
        ouder = None
    return categorie in cats or (ouder in cats if ouder else False)


def momenten_rond(vandaag, dagen_vooruit=400):
    """Alle momenten per land van vandaag tot dagen_vooruit, met hun mailvenster."""
    uit = []
    for sleutel, (naam, per_land, vooraf, cats) in KALENDER.items():
        for land, functie in per_land.items():
            for jaar in (vandaag.year, vandaag.year + 1):
                d = functie(jaar)
                if vandaag - timedelta(days=VENSTER_DAGEN + vooraf) <= d <= vandaag + timedelta(days=dagen_vooruit):
                    open_op = d - timedelta(days=vooraf)
                    uit.append({"sleutel": f"{sleutel}-{land}-{jaar}", "moment": sleutel, "naam": naam,
                                "land": land, "datum": d, "open_op": open_op,
                                "dicht_op": open_op + timedelta(days=VENSTER_DAGEN), "cats": cats})
    return sorted(uit, key=lambda m: (m["datum"], m["land"]))


def open_nu(vandaag):
    """De momenten waarvan het mailvenster vandaag open is."""
    return [m for m in momenten_rond(vandaag) if m["open_op"] <= vandaag < m["dicht_op"]]


# ------------------------------------------------------------- wie

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
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def _passende_categorieen(momenten):
    """Alle categorieen die bij minstens een van deze momenten passen, of None voor alles."""
    if any(m["cats"] == ALLES for m in momenten):
        return None
    import categorieen
    return sorted({slug for slug in categorieen.GELDIG if any(past(slug, m["cats"]) for m in momenten)})


def kandidaten(land, momenten=None, limiet=500):
    """Winkels in dit land die een seizoensmail mogen krijgen. Met momenten:
    alleen winkels in een passende categorie, die dit moment nog niet kregen."""
    momenten = momenten or []
    cats = _passende_categorieen(momenten) if momenten else None
    sleutels = [m["sleutel"] for m in momenten] or ["-"]
    extra = "AND b.categorie = ANY(%s)" if cats is not None else ""
    waarden = [land, sleutels] + ([cats] if cats is not None else []) + [limiet]
    return _sql(f"""
        SELECT b.webshop_url, b.email, b.categorie, b.seizoen_op, b.seizoen_sleutel
          FROM benadering b
         WHERE lower(coalesce(b.land, 'nl')) = %s
           AND b.email IS NOT NULL AND b.email <> ''
           AND b.gemaild_op IS NOT NULL AND b.gemaild_op < now() - interval '{NA_KOUDE_MAIL_DAGEN} days'
           AND NOT b.afgemeld AND b.bounce_op IS NULL AND b.klacht_op IS NULL AND b.antwoord_op IS NULL
           AND coalesce(b.soort, 'winkel') = 'winkel'
           AND (b.seizoen_op IS NULL OR b.seizoen_op < now() - interval '{RUST_DAGEN} days')
           AND NOT EXISTS (SELECT 1 FROM klanten k WHERE k.webshop_url = b.webshop_url)
           AND coalesce(b.seizoen_sleutel, '') <> ALL(%s)
           {extra}
      ORDER BY b.seizoen_op NULLS FIRST, b.gemaild_op
         LIMIT %s""", tuple(waarden), alles=True) or []


def vandaag_verstuurd():
    rij = _sql("SELECT count(*) AS n FROM benadering WHERE seizoen_op >= date_trunc('day', now())")
    return int((rij or {}).get("n") or 0)


# ------------------------------------------------------------- de mail

def _kaal(url):
    return (url or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def maak_mail(moment, beeld, vraag=None, link_url="", categorienaam=None, vandaag=None):
    """Onderwerp en alinea's. None als er niets eerlijks te zeggen is (geen plek)."""
    if not beeld or not beeld.get("positie"):
        return None
    vandaag = vandaag or date.today()
    naam = _kaal(beeld.get("webshop_url"))
    cat = categorienaam or beeld.get("categorie") or "your category"
    weken = max(1, round((moment["datum"] - vandaag).days / 7))
    dag = f"{moment['datum'].day} {moment['datum'].strftime('%B')}"
    onderwerp = f"{naam}: {moment['naam']} is in {weken} weeks"
    alineas = ["Hi,",
               f"{moment['naam'][0].upper() + moment['naam'][1:]} is on {dag}, in {weken} weeks. "
               f"Around now shoppers start asking ChatGPT and Gemini where to buy."]
    if vraag and vraag.get("concurrenten"):
        wie = " and ".join(vraag["concurrenten"][:2])
        alineas.append(f"Right now, for <strong>\"{vraag['vraag']}\"</strong> AI names {wie}, not you.")
    alineas.append(f"You are #{beeld['positie']} of {beeld.get('van') or '?'} in {cat}.")
    alineas.append("Changes on a site take a while to show up in AI answers, so the weeks before "
                   f"{moment['naam']} are when it counts. With Fix we write and place the product "
                   "texts for you; with Watch you get them written out to do yourself.")
    alineas.append("Your page shows every question you lose, with the real answer.")
    return {"onderwerp": onderwerp, "alineas": alineas, "link": link_url}


# ------------------------------------------------------------- de ronde

def ronde(basis_url, bouw_beeld, vraag_voor, categorienaam=None, verstuur=None, vandaag=None,
          binnen_kantooruren=True, aan=True):
    """Een ronde. Geeft een verslag {verstuurd, overgeslagen, momenten}."""
    verslag = {"verstuurd": 0, "overgeslagen": 0, "momenten": []}
    if not aan or not binnen_kantooruren:
        return verslag
    vandaag = vandaag or datetime.now(timezone.utc).date()
    ruimte = min(PER_RONDE, max(0, PER_DAG - vandaag_verstuurd()))
    if not ruimte:
        return verslag
    if verstuur is None:
        import emailing
        verstuur = emailing.send_opvolging
    open_ = open_nu(vandaag)
    verslag["momenten"] = [m["sleutel"] for m in open_]
    # Alle momenten van de komende tijd, om te zien of er voor een winkel een
    # moment aankomt dat beter bij hem past dan een algemeen moment.
    komend = momenten_rond(vandaag, dagen_vooruit=120)

    def beter_moment_komt(w, moment):
        """Een speelgoedwinkel wacht op Sinterklaas in plaats van een algemeen moment te
        krijgen en daarna 45 dagen rust. Geldt alleen voor algemene momenten."""
        if moment["cats"] != ALLES:
            return False
        return any(m["land"] == moment["land"] and m["cats"] != ALLES and past(w.get("categorie"), m["cats"])
                   and abs((m["datum"] - moment["datum"]).days) <= 21 and m["datum"] >= vandaag
                   for m in komend)

    for land in sorted({m["land"] for m in open_}):
        momenten = [m for m in open_ if m["land"] == land]
        for w in kandidaten(land, momenten):
            if verslag["verstuurd"] >= ruimte:
                return verslag
            # Het eerstvolgende moment dat bij zijn categorie past, en dat hij nog niet kreeg.
            # Eerst een moment dat specifiek bij hem past, dan pas een algemeen moment.
            passend = [m for m in momenten if past(w.get("categorie"), m["cats"])
                       and w.get("seizoen_sleutel") != m["sleutel"]]
            passend.sort(key=lambda m: (m["cats"] == ALLES, m["datum"]))
            moment = next((m for m in passend if not beter_moment_komt(w, m)), None)
            if not moment:
                continue
            url = w["webshop_url"]
            try:
                beeld = bouw_beeld(url)
            except Exception:
                beeld = None
            token = db.get_benchmark_token(url)
            mail = maak_mail(moment, beeld, vraag_voor(url, beeld) if beeld else None,
                             link_url=f"{basis_url}/uitkomst/{token}" if token else basis_url,
                             categorienaam=categorienaam(beeld) if (categorienaam and beeld) else None,
                             vandaag=vandaag)
            if not mail:
                # Alleen dit moment afvinken (geen plek, dus niets eerlijks te
                # zeggen), zonder de rust van 45 dagen: er ging niets uit.
                _sql("UPDATE benadering SET seizoen_sleutel = %s WHERE webshop_url = %s",
                     (moment["sleutel"], url))
                verslag["overgeslagen"] += 1
                continue
            afmeld = f"{basis_url}/afmelden/{token}" if token else None
            # Voor het versturen vastleggen: gaat er daarna iets mis, dan liever
            # een mail te weinig dan twee keer dezelfde.
            _sql("UPDATE benadering SET seizoen_op = now(), seizoen_sleutel = %s WHERE webshop_url = %s",
                 (moment["sleutel"], url))
            if verstuur(w["email"], mail["onderwerp"], mail["alineas"], mail["link"], afmeld_url=afmeld):
                verslag["verstuurd"] += 1
    return verslag
