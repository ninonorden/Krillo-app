"""Stap 88: het opleveroverzicht gaat vanzelf naar de klant (30 september 2026).

WAAROM. Tot nu toe stuurde Nino het overzicht met de hand via /admin/oplevering.
Bij een gekoppelde winkel (Shopify of WordPress) zet Krillo de wijzigingen er
zelf in, met de oude tekst bewaard. Dan is er niets meer om eerst te lezen: de
klant keurde elk voorstel zelf goed. Hij hoort dan vanzelf, dezelfde dag, een
overzicht te krijgen met oud en nieuw. Dat is:
- de belofte "je kunt alles terugzetten" waarmaken (de oude tekst staat erin);
- het bewijs van werk, en dus de reden om te blijven betalen;
- het vaste moment voor de nameting (de opdracht staat op opgeleverd).

WAT BEWUST NIET. Wijzigingen die Nino met de hand vastlegt (werkbriefje, voor
Lightspeed en de rest) gaan NIET vanzelf. Die leest hij eerst zelf, zoals de
beschrijving van /admin/oplevering altijd zei.

HOE.
- Alleen wijzigingen van de motoren (taak_id begint met shopify: of wp:).
- Pas als het RUSTIG is: de nieuwste wijziging is minstens RUST_UREN oud. Wie
  tien voorstellen achter elkaar goedkeurt, krijgt een mail, geen tien.
- Alleen wat nieuw is sinds de vorige keer. Geen herhaling.
- Tussen 9 en 19 uur (wachtklok), nooit midden in de nacht.
- Een klant die opzegde krijgt niets.
"""
import db

RUST_UREN = 2
# Nooit oude wijzigingen als nieuws sturen (1 oktober: de eerste ronde stuurde
# wijzigingen van weken terug). Ouder dan dit gaat niet meer vanzelf.
TERUG_DAGEN = 7


def _recent(moment):
    from datetime import datetime, timedelta, timezone
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment > datetime.now(timezone.utc) - timedelta(days=TERUG_DAGEN)
MOTOREN = ("shopify:", "wp:")


def _sql(q, w=None, alles=True):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return [] if alles else None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(q, w)
                if cur.description is None:
                    return None
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def maak_tabel():
    _sql("""CREATE TABLE IF NOT EXISTS opleveringen_verstuurd (
                webshop_url TEXT PRIMARY KEY,
                verstuurd_op TIMESTAMPTZ NOT NULL,
                aantal INTEGER NOT NULL DEFAULT 0)""")


def te_versturen():
    """[{webshop_url, email, wijzigingen}] voor wie er nu een overzicht krijgt."""
    maak_tabel()
    rijen = _sql(f"""
        SELECT w.webshop_url, max(w.gedaan_op) AS laatst, o.verstuurd_op
          FROM wijzigingen w
          LEFT JOIN opleveringen_verstuurd o ON o.webshop_url = w.webshop_url
         WHERE (w.taak_id LIKE 'shopify:%%' OR w.taak_id LIKE 'wp:%%')
      GROUP BY w.webshop_url, o.verstuurd_op
        HAVING max(w.gedaan_op) < now() - interval '{int(RUST_UREN)} hours'
           AND max(w.gedaan_op) > now() - interval '{int(TERUG_DAGEN)} days'
           AND (o.verstuurd_op IS NULL OR max(w.gedaan_op) > o.verstuurd_op)""")
    uit = []
    for r in rijen:
        url = r["webshop_url"]
        klant = db.klant_bij_url(url) or {}
        # 1 oktober: de eerste ronde stuurde ook naar Nino's eigen proefwinkels op
        # Shopify (krill-test, krillo-demo), met wijzigingen van weken geleden.
        # Alleen echte, lopende klanten; testklanten niet.
        if klant.get("opgezegd_op") or klant.get("is_test"):
            continue
        email = klant.get("email")
        if not email:
            for u in db.get_uitvoeringen(url) or []:
                if u.get("stand") != "afgebroken" and u.get("email"):
                    email = u["email"]
                    break
        if not email:
            continue
        grens = r["verstuurd_op"]
        nieuw = [dict(w) for w in db.get_wijzigingen(url)
                 if (w.get("taak_id") or "").startswith(MOTOREN)
                 and (grens is None or w["gedaan_op"] > grens)
                 and _recent(w["gedaan_op"])]
        if nieuw:
            uit.append({"webshop_url": url, "email": email, "wijzigingen": nieuw,
                        "token": klant.get("klant_token")})
    return uit


def ronde(basis_url="https://krilloai.com", stuur=None):
    """Verstuurt de overzichten. Geeft een verslag: {"verstuurd": [...], "mislukt": [...]}."""
    import emailing
    stuur = stuur or emailing.send_oplevering
    verslag = {"verstuurd": [], "mislukt": []}
    for k in te_versturen():
        link = f"{basis_url.rstrip('/')}/mijn/{k['token']}" if k.get("token") else None
        if not stuur(k["email"], k["webshop_url"], k["wijzigingen"], link):
            # Niets vastleggen: de volgende keer opnieuw proberen.
            verslag["mislukt"].append(k["webshop_url"])
            continue
        _sql("""INSERT INTO opleveringen_verstuurd (webshop_url, verstuurd_op, aantal)
                VALUES (%s, now(), %s)
                ON CONFLICT (webshop_url) DO UPDATE SET verstuurd_op = now(),
                       aantal = opleveringen_verstuurd.aantal + EXCLUDED.aantal""",
             (k["webshop_url"], len(k["wijzigingen"])))
        # Telt als oplevering voor de nameting (stap 79).
        for u in db.get_uitvoeringen(k["webshop_url"]) or []:
            if u.get("stand") == "bezig":
                db.zet_uitvoering_stand(u["id"], "opgeleverd")
                break
        verslag["verstuurd"].append(f"{k['webshop_url']} ({len(k['wijzigingen'])})")
    return verslag
