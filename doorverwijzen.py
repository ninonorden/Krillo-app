"""Doorverwijzen (stap 94, 28 september).

WAAROM DIT BESTAAT. Een winkel die tevreden is kent andere winkels, en een
bureau of Shopify-partner heeft er tien tot vijftig tegelijk. Peec geeft
partners 20 procent, SE Ranking 30; HeadshotPro haalt meer dan 15 procent van
zijn omzet uit doorverwijzers. Het is bereik dat niets kost tot er betaald is.

TWEE SOORTEN
- klant: elke betalende klant heeft op zijn pagina Abonnement een eigen link.
  Wordt een winkel via die link betalend klant, dan krijgt de doorverwijzer een
  maand van zijn eigen pakket terug. Pas na WACHTDAGEN, zodat iemand niet een
  vriend laat aanmelden en na de bedenktijd laat stoppen.
- partner: een bureau, freelancer of Shopify-partner meldt zich aan op
  /partners. Nino keurt goed (geen automatische goedkeuring: een partner
  spreekt namens ons). Daarna 20 procent van wat de klant betaalt, zonder btw,
  12 maanden lang.

UITBETALEN GEBEURT MET DE HAND. Bewust: in het begin zijn het er een paar, en
een fout in een automatische terugbetaling kost echt geld. /admin/doorverwijzen
rekent uit wat er openstaat; Nino maakt het over en klikt op Betaald.

REGELS
- Eerste doorverwijzing wint (een winkel kan maar een keer worden meegeteld).
- Jezelf doorverwijzen telt niet.
- Test- en proefbetalingen tellen niet.
- GEEN COOKIE. De site belooft "geen cookie, geen cookiebanner", en een
  doorverwijscookie zou onder de Telecommunicatiewet toestemming kunnen vragen.
  Daarom gaat de code mee in de link (/?ref=code) en onthouden wij hem bij het
  winkeladres dat iemand in de gratis check of de kassa invult, 60 dagen lang.
  Dat staat in het privacybeleid.
"""
import os
import re
import secrets
from datetime import datetime, timezone

import db

PROCENT_PARTNER = 20
MAANDEN_PARTNER = 12
WACHTDAGEN = 30          # een klant-beloning pas na 30 dagen betalen (bedenktijd is 14)
ONTHOUD_DAGEN = 60
_TEKENS = "abcdefghjkmnpqrstuvwxyz23456789"   # geen 0/o, 1/l/i: wordt ook overgetypt


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
                    return cur.rowcount
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def maak_tabellen(cur):
    """Aangeroepen vanuit db.init_db, met de cursor daar."""
    cur.execute("""CREATE TABLE IF NOT EXISTS doorverwijzers (
                       code TEXT PRIMARY KEY,
                       soort TEXT NOT NULL,              -- 'klant' of 'partner'
                       naam TEXT, email TEXT,
                       webshop_url TEXT UNIQUE,          -- alleen bij soort klant
                       website TEXT, bericht TEXT,
                       stand TEXT NOT NULL DEFAULT 'actief',   -- aanvraag, actief, afgewezen
                       bezoeken INTEGER NOT NULL DEFAULT 0,
                       aangemaakt_op TIMESTAMPTZ NOT NULL DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS doorverwijzingen (
                       id SERIAL PRIMARY KEY,
                       code TEXT NOT NULL,
                       webshop_url TEXT NOT NULL UNIQUE,
                       payment_id TEXT UNIQUE,
                       pakket TEXT, periode TEXT,
                       op TIMESTAMPTZ NOT NULL DEFAULT now(),
                       uitbetaald NUMERIC(10,2) NOT NULL DEFAULT 0,
                       uitbetaald_op TIMESTAMPTZ)""")
    # Welke winkel via welke link binnenkwam, voordat er betaald is.
    cur.execute("""CREATE TABLE IF NOT EXISTS doorverwijs_kliks (
                       webshop_url TEXT PRIMARY KEY,
                       code TEXT NOT NULL,
                       op TIMESTAMPTZ NOT NULL DEFAULT now())""")


def schoon_code(code):
    """Alleen kleine letters, cijfers en streepjes. De code komt uit een link of
    cookie en is dus door iedereen te verzinnen."""
    tekst = re.sub(r"[^a-z0-9\-]", "", (code or "").strip().lower())[:40]
    return tekst or None


def _nieuwe_code(voorkeur=None):
    """Een partner krijgt een leesbare code (bureau-x); een klant een korte willekeurige."""
    basis = schoon_code(re.sub(r"[\s_.]+", "-", (voorkeur or "").lower()))
    if basis:
        basis = basis.strip("-")[:24]
        for poging in range(20):
            kandidaat = basis if poging == 0 else f"{basis}-{poging + 1}"
            if not _sql("SELECT 1 AS er FROM doorverwijzers WHERE code = %s", (kandidaat,)):
                return kandidaat
    while True:
        kandidaat = "".join(secrets.choice(_TEKENS) for _ in range(7))
        if not _sql("SELECT 1 AS er FROM doorverwijzers WHERE code = %s", (kandidaat,)):
            return kandidaat


def code_voor_klant(webshop_url, email=None):
    """De vaste code van een klant. Maakt hem aan bij de eerste keer."""
    if not webshop_url:
        return None
    rij = _sql("SELECT code FROM doorverwijzers WHERE webshop_url = %s", (webshop_url,))
    if rij:
        return rij["code"]
    code = _nieuwe_code()
    _sql("""INSERT INTO doorverwijzers (code, soort, email, webshop_url, stand)
            VALUES (%s, 'klant', %s, %s, 'actief') ON CONFLICT (webshop_url) DO NOTHING""",
         (code, email, webshop_url))
    rij = _sql("SELECT code FROM doorverwijzers WHERE webshop_url = %s", (webshop_url,))
    return rij["code"] if rij else None


def partner_aanvragen(naam, email, website, bericht=None):
    """Een aanvraag van een bureau of partner. Nog niet actief."""
    code = _nieuwe_code(naam)
    _sql("""INSERT INTO doorverwijzers (code, soort, naam, email, website, bericht, stand)
            VALUES (%s, 'partner', %s, %s, %s, %s, 'aanvraag')""",
         (code, (naam or "")[:120], (email or "")[:200], (website or "")[:200], (bericht or "")[:2000]))
    return code


def zet_stand(code, stand):
    if stand not in ("actief", "afgewezen", "aanvraag"):
        return None
    _sql("UPDATE doorverwijzers SET stand = %s WHERE code = %s", (stand, code))
    return bij_code(code, ook_niet_actief=True)


def bij_code(code, ook_niet_actief=False):
    code = schoon_code(code)
    if not code:
        return None
    rij = _sql("SELECT * FROM doorverwijzers WHERE code = %s", (code,))
    if not rij or (not ook_niet_actief and rij.get("stand") != "actief"):
        return None
    return rij


def onthoud(webshop_url, code):
    """Iemand checkte deze winkel via een doorverwijslink. De eerste link wint;
    een link na de 60 dagen mag de oude vervangen."""
    wie = bij_code(code)
    if not wie or not webshop_url or wie.get("webshop_url") == webshop_url:
        return None
    _sql("""INSERT INTO doorverwijs_kliks (webshop_url, code) VALUES (%s, %s)
            ON CONFLICT (webshop_url) DO UPDATE SET code = EXCLUDED.code, op = now()
            WHERE doorverwijs_kliks.op < now() - make_interval(days => %s)""",
         (webshop_url, wie["code"], ONTHOUD_DAGEN))
    return wie["code"]


def onthouden(webshop_url):
    """De code die bij deze winkel hoort, als dat minder dan 60 dagen geleden is."""
    if not webshop_url:
        return None
    rij = _sql("""SELECT code FROM doorverwijs_kliks WHERE webshop_url = %s
                  AND op >= now() - make_interval(days => %s)""", (webshop_url, ONTHOUD_DAGEN))
    return rij["code"] if rij and bij_code(rij["code"]) else None


def code_bij_kassa(webshop_url, ref=None):
    """De code die mee moet naar Mollie: uit de link zelf, anders onthouden bij de winkel."""
    if ref:
        onthoud(webshop_url, ref)
    wie = bij_code(ref) if ref else None
    if wie and wie.get("webshop_url") != webshop_url:
        return wie["code"]
    return onthouden(webshop_url)


def tel_bezoek(code):
    _sql("UPDATE doorverwijzers SET bezoeken = bezoeken + 1 WHERE code = %s", (code,))


def leg_vast(code, webshop_url, payment_id, pakket=None, periode=None):
    """Een nieuwe betalende klant via een doorverwijzer. Geeft de doorverwijzer
    terug als het telt, anders None (onbekende code, eigen winkel, al eerder
    doorverwezen)."""
    wie = bij_code(code)
    if not wie or not webshop_url:
        return None
    if wie.get("webshop_url") and wie["webshop_url"] == webshop_url:
        return None
    aantal = _sql("""INSERT INTO doorverwijzingen (code, webshop_url, payment_id, pakket, periode)
                     VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                  (wie["code"], webshop_url, payment_id, pakket, periode))
    return wie if aantal else None


def _maanden_tussen(begin, eind):
    maanden = (eind.year - begin.year) * 12 + (eind.month - begin.month)
    if eind.day < begin.day:
        maanden -= 1
    return max(0, maanden)


def _excl_btw(bedrag):
    """Betaalt Krillo btw af (BTW_REGELING=btw), dan zit er btw in het bedrag
    en rekenen we de 20 procent over het deel zonder btw."""
    if os.environ.get("BTW_REGELING", "kor").lower() == "btw":
        return round(bedrag / 1.21, 2)
    return bedrag


def verdiend(rij, soort, nu=None, prijzen=None, eigen_prijs=None):
    """Wat er bij deze doorverwijzing verdiend is tot nu.

    rij: een doorverwijzing met op, pakket, periode, opgezegd_op, is_test.
    prijzen: {pakket: (maandprijs, jaarprijs)}; standaard uit payments.
    eigen_prijs: bij een klant-doorverwijzer de maandprijs van zijn eigen pakket.
    Geeft {"bedrag", "betalingen", "klaar_op", "uitleg"}."""
    nu = nu or datetime.now(timezone.utc)
    if rij.get("is_test"):
        return {"bedrag": 0.0, "betalingen": 0, "uitleg": "testklant, telt niet"}
    begin = rij["op"]
    eind = min(nu, rij["opgezegd_op"]) if rij.get("opgezegd_op") else nu
    if soort == "klant":
        dagen = (eind - begin).days
        if dagen < WACHTDAGEN:
            if rij.get("opgezegd_op"):
                return {"bedrag": 0.0, "betalingen": 0, "uitleg": "gestopt binnen 30 dagen, vervalt"}
            return {"bedrag": 0.0, "betalingen": 0,
                    "uitleg": f"wacht nog {WACHTDAGEN - dagen} dagen (tegen stoppen in de bedenktijd)"}
        return {"bedrag": float(eigen_prijs or 0), "betalingen": 1,
                "uitleg": "een maand van zijn eigen pakket terug"}
    if prijzen is None:
        import payments
        prijzen = {p: (float(v["prijs"]["value"]), float(v.get("jaarprijs", v["prijs"])["value"]))
                   for p, v in payments.PAKKETTEN.items()}
    maand, jaar = prijzen.get((rij.get("pakket") or "fix").lower(), prijzen.get("fix"))
    if rij.get("periode") == "jaar":
        # Een jaar vooruit betaald: een betaling binnen de 12 maanden.
        return {"bedrag": round(_excl_btw(jaar) * PROCENT_PARTNER / 100, 2), "betalingen": 1,
                "uitleg": f"{PROCENT_PARTNER}% van de jaarbetaling"}
    betalingen = min(MAANDEN_PARTNER, _maanden_tussen(begin, eind) + 1)
    return {"bedrag": round(_excl_btw(maand) * PROCENT_PARTNER / 100 * betalingen, 2),
            "betalingen": betalingen,
            "uitleg": f"{PROCENT_PARTNER}% van {betalingen} maandbetaling(en)"
                      + (" (klant gestopt)" if rij.get("opgezegd_op") else "")}


def overzicht(nu=None):
    """Alles voor /admin/doorverwijzen: aanvragen, doorverwijzers en wat openstaat."""
    import payments
    aanvragen = _sql("SELECT * FROM doorverwijzers WHERE stand = 'aanvraag' ORDER BY aangemaakt_op",
                     alles=True) or []
    wie = _sql("""SELECT d.*, (SELECT count(*) FROM doorverwijzingen v WHERE v.code = d.code) AS klanten
                  FROM doorverwijzers d WHERE d.stand = 'actief'
                  ORDER BY d.soort DESC, d.bezoeken DESC LIMIT 300""", alles=True) or []
    rijen = _sql("""SELECT v.*, d.soort, d.naam, d.email AS door_email, d.webshop_url AS door_winkel,
                           k.opgezegd_op, coalesce(k.is_test, false) AS is_test,
                           e.pakket AS eigen_pakket
                    FROM doorverwijzingen v
                    JOIN doorverwijzers d ON d.code = v.code
                    LEFT JOIN klanten k ON k.webshop_url = v.webshop_url
                    LEFT JOIN klanten e ON e.webshop_url = d.webshop_url
                    ORDER BY v.op DESC""", alles=True) or []
    open_totaal = 0.0
    for r in rijen:
        eigen = None
        if r["soort"] == "klant":
            try:
                eigen = float(payments.pakket_van(r.get("eigen_pakket"))["prijs"]["value"])
            except Exception:
                eigen = None
        r["verdiend"] = verdiend(r, r["soort"], nu=nu, eigen_prijs=eigen)
        r["open"] = round(max(0.0, r["verdiend"]["bedrag"] - float(r.get("uitbetaald") or 0)), 2)
        open_totaal += r["open"]
    return {"aanvragen": aanvragen, "doorverwijzers": wie, "doorverwijzingen": rijen,
            "open_totaal": round(open_totaal, 2)}


def zet_uitbetaald(id_, bedrag):
    """Nino heeft overgemaakt: het totaal dat nu uitbetaald is bij deze doorverwijzing."""
    return _sql("UPDATE doorverwijzingen SET uitbetaald = %s, uitbetaald_op = now() WHERE id = %s",
                (round(float(bedrag), 2), int(id_)))


def voor_klant(webshop_url):
    """Voor het dashboard: hoeveel winkels via zijn link klant werden."""
    code = code_voor_klant(webshop_url)
    if not code:
        return None
    tel = _sql("SELECT count(*) AS n FROM doorverwijzingen WHERE code = %s", (code,)) or {}
    rij = _sql("SELECT bezoeken FROM doorverwijzers WHERE code = %s", (code,)) or {}
    return {"code": code, "klanten": int(tel.get("n") or 0), "bezoeken": int(rij.get("bezoeken") or 0)}
