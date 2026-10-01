"""De groeiagent: elke paar uur kijken waar de klantenstroom vastloopt (1 oktober 2026).

WAAROM DIT BESTAAT. Nino: "ik ga niet bellen. Bedenk geautomatiseerde outreach.
Laat de agent die hiervoor verantwoordelijk is alles oppakken en constant
scannen per zoveel uur. Ik wil alleen checken en akkoord geven." En: "geef mij
dagtaken voor de volledige dag, ik wil elke dag werken aan Krillo."

WIE DOET WAT (zodat er geen twee agents hetzelfde doen)
- De MOTOREN doen de outreach zelf, elk uur: koude mail (benadering), de
  verkoopagent (opvolging van wie keek), de bureau-agent, de lijstjesagent, de
  persagent, de bewegings- en badgemails.
- De LEERAGENT onderzoekt op het web wat werkt (kanalen, concurrenten, nieuwe
  functies) en levert taken en bouwvoorstellen aan.
- DEZE AGENT is de regisseur. Elke vier uur overdag:
  1. leest hij de echte cijfers van de trechter (wat ging er uit, wie keek,
     wie klikte, wat staat er klaar);
  2. zoekt hij de rem: een motor die stilstaat omdat hij op Nino wacht, of
     een motor die meer aankan;
  3. zet hij daarvoor een voorstel klaar met een akkoordlink (voorstellen.py).
     Akkoord en de motor draait vanzelf verder.
  En elke ochtend stelt hij de dagtaken samen voor het ochtendbericht.

WAT HIJ BEWUST NIET DOET
- Zelf iets aanzetten zonder akkoord. Meer mail versturen of een agent vrij
  laten mailen is een keuze over het domein en de naam van Krillo; die is van
  Nino.
- Iets verzinnen. Elke regel hieronder volgt uit een telling in de database;
  zonder cijfers geen voorstel.
- Een AI-aanroep. Dit kost niets en kan dus zo vaak als nodig.
"""
import json
from datetime import datetime

import db

ELKE_UREN = 4
SLEUTEL_VERSLAG = "groeiagent"


def _tel(sql, waarden=None):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, waarden)
                rij = cur.fetchone()
                return rij[0] if rij else None
    except Exception as e:
        print(f"Groeiagent, telling mislukt: {e}")
        return None
    finally:
        conn.close()


def feiten():
    """De cijfers waar de regels op beslissen. Een telling die mislukt is None."""
    import benadering
    import bureauvinder
    import verkoopagent as va
    f = {
        "verkoop_concepten": _tel("SELECT count(*) FROM benadering WHERE opvolg_stand = 'concept'"),
        "verkoop_oudste_uren": _tel("SELECT extract(epoch FROM now() - min(bekeken_op)) / 3600 "
                                    "FROM benadering WHERE opvolg_stand = 'concept'"),
        "verkoop_zelf": va.zelf_versturen(),
        "bureaus_klaar": _tel("""SELECT count(*) FROM bureaus b WHERE b.stand = 'nieuw' AND b.email IS NOT NULL
                                  AND (SELECT count(*) FROM bureau_winkels w WHERE w.bureau_site = b.site) >= %s""",
                              (bureauvinder.BUREAU_MIN,)),
        "bureau_auto": bureauvinder.mag_automatisch() > 0 or
        (db.get_instelling(bureauvinder.SLEUTEL_AUTO) or "").lower() == "ja",
        "mails_7d": _tel("SELECT count(*) FROM benadering WHERE gemaild_op > now() - interval '7 days'"),
        "mensen_7d": _tel("SELECT count(*) FROM benadering WHERE mens_op > now() - interval '7 days'"),
        "geopend_7d": _tel("SELECT count(*) FROM benadering WHERE bekeken_op > now() - interval '7 days'"),
        "doorgeklikt_7d": _tel("SELECT count(*) FROM benadering WHERE doorgeklikt_op > now() - interval '7 days'"),
        "klanten": _tel("SELECT count(*) FROM klanten WHERE NOT is_test AND opgezegd_op IS NULL"),
    }
    try:
        stand = benadering.instellingen()
        f["benadering_aan"] = stand["aan"]
        f["per_dag"] = stand["per_dag"]
        f["doel"] = benadering.opbouw_doel()
        f["opbouw_max"] = benadering.OPBOUW_MAX
        f["gezond"] = benadering.verzendgezondheid()["gezond"]
    except Exception as e:
        print(f"Groeiagent, benadering lezen mislukt: {e}")
    try:
        f["klaar_voor_post"] = len(db.te_mailen_met_positie(10000))
    except Exception:
        f["klaar_voor_post"] = None
    return f


def kansen(f):
    """Uit de cijfers: de voorstellen. Lijst van dicts voor voorstellen.stel_voor.
    Zuiver (geen database), zodat elke regel te testen is."""
    uit = []
    n = f.get("verkoop_concepten") or 0
    if n and not f.get("verkoop_zelf"):
        uren = f.get("verkoop_oudste_uren")
        uit.append({
            "soort": "actie", "actie": "verkoop_zelf",
            "titel": "Laat de verkoopagent zijn opvolgingen zelf versturen",
            "waarom": (f"{n} winkel(s) die hun Krillo-pagina bekeken wachten op een opvolging"
                       + (f", de oudste al {int(uren)} uur" if uren else "")
                       + ". Wie net keek is het warmst; elke dag wachten maakt dat minder. De tekst is een vast "
                         "sjabloon met zijn eigen cijfers, gaat langs de controleagent, hoogstens twee per winkel, "
                         "alleen binnen kantooruren. Terugzetten kan op /admin/verkoop."),
        })
    n = f.get("bureaus_klaar") or 0
    if n and not f.get("bureau_auto"):
        uit.append({
            "soort": "actie", "actie": "bureau_auto",
            "titel": "Laat de bureau-agent bureaus zelf mailen",
            "waarom": (f"{n} webbureau(s) hebben drie of meer klanten in de index en een algemeen adres. Een "
                       f"bureau is tientallen winkels tegelijk, en verdient 20 procent als partner. Hoogstens twee "
                       f"per dag, met afmeldlink."),
        })
    per_dag, doel = f.get("per_dag"), f.get("doel")
    klaar = f.get("klaar_voor_post")
    if (f.get("benadering_aan") and f.get("gezond") and per_dag and doel and per_dag >= doel
            and doel + 20 <= f.get("opbouw_max", 100)
            and klaar is not None and klaar >= 3 * (doel + 20) and (f.get("mails_7d") or 0) >= doel * 4):
        uit.append({
            "soort": "actie", "actie": "opbouw_hoger",
            "titel": f"Verhoog de koude mail van {doel} naar {doel + 20} per dag",
            "waarom": (f"De post landt goed (weinig teruggekaatst, geen spammeldingen), het doel van {doel} per dag "
                       f"is gehaald en er staan {klaar} winkels klaar. Meer mail is meer mensen die hun plek zien. "
                       f"De opbouw gaat per week, en de automatische rem zet hem terug als het slechter landt."),
        })
    mails, mensen = f.get("mails_7d") or 0, f.get("mensen_7d") or 0
    if mails >= 150 and mensen == 0:
        uit.append({
            "soort": "bouwen",
            "titel": "Nieuwe opening van de koude mail testen: onderwerp en eerste zin",
            "waarom": (f"{mails} koude mails in 7 dagen en geen enkele echte mens die doorklikte (alleen "
                       f"mailbeveiliging). De mail wordt wel bezorgd maar niet gelezen. Claude bouwt twee nieuwe "
                       f"openingen als uitdager naast de huidige versies."),
            "sleutel": "bouw:mailopening:" + datetime.now().strftime("%Y-%W"),
        })
    return uit


def ronde(nu=None):
    """Een keer kijken en de voorstellen klaarzetten. Geeft een verslag."""
    import voorstellen
    f = feiten()
    nieuw = []
    def _vrijdag():
        import agentscore
        return agentscore.voorstel(agentscore.score(), nu=nu)

    for stap in (volgende_gids, volgende_uitbreiding, _vrijdag):
        try:
            rij = stap()
            if rij:
                nieuw.append(rij["titel"])
        except Exception as e:
            print(f"Groeiagent, {stap.__name__} mislukt: {e}")
    for k in kansen(f):
        rij = voorstellen.stel_voor("groeiagent", k["soort"], k["titel"], waarom=k.get("waarom"),
                                    actie=k.get("actie"), sleutel=k.get("sleutel"))
        if rij:
            nieuw.append(k["titel"])
    verslag = {"op": (nu or datetime.now()).isoformat(timespec="minutes"), "feiten": f, "nieuw": nieuw}
    try:
        db.zet_instelling(SLEUTEL_VERSLAG, json.dumps(verslag, default=str)[:8000])
    except Exception as e:
        print(f"Groeiagent, verslag bewaren mislukt: {e}")
    return verslag


# ------------------------------------------------------------------ gidsen
# Uit het aanmeldpakket (project: krillo-aanmeldpakket-gidsen). Elke vermelding
# is een link naar krilloai.com die AI meetelt bij "welke tool voor AI-
# zichtbaarheid". Er staat er steeds EEN klaar als taak; staat hij er al, zeg
# dan "gedaan", dan komt de volgende. Betaalde gidsen staan er bewust niet in.
GIDSEN = [
    ("SaaSHub", "saashub.com, knop Submit Software. Zet Krillo daarna als alternatief bij Otterly.AI en Peec AI."),
    ("AlternativeTo", "alternativeto.net, menu Add application. Na goedkeuring bij Otterly en Peec AI op "
                      "Suggest alternative en kies Krillo."),
    ("FutureTools", "futuretools.io, knop Submit a tool."),
    ("The Next AI", "thenextai.com, gratis aanmelden."),
    ("Findly.tools", "findly.tools, gratis. Vragen ze een link terug, geef het stukje code aan Claude."),
    ("G2", "sell.g2.com, Get a free profile, categorie AI Search Visibility of SEO Software."),
    ("Capterra", "vendors.capterra.com, gratis profiel."),
    ("BetaList", "betalist.com, gratis (met een wachtrij van een paar weken)."),
    ("There's An AI For That", "theresanaiforthat.com, gratis beoordeling aanvragen. Niet betalen."),
]

AANMELDTEKST = {
    "Naam": "Krillo",
    "Website": "https://krilloai.com",
    "Tagline": "See if ChatGPT recommends your online store",
    "Kort": ("Krillo measures every month whether ChatGPT and Gemini recommend your online store, shows who they "
             "name instead, and fixes what keeps you out."),
    "Lang": ("More and more shoppers ask ChatGPT or Gemini where to buy. Krillo asks AI assistants the buying "
             "questions shoppers actually ask, category by category, every month, and publishes the result as a "
             "public ranking: the Krillo Index. A store owner sees their rank, the questions where AI names a "
             "competitor, and what to change. With Watch they get the fixes written out to do themselves; with "
             "Fix, Krillo makes the changes in the store. There is a free check without an account, free tools, "
             "and a partner program for agencies."),
    "Tags": "AI visibility, GEO, generative engine optimization, ChatGPT, ecommerce, Shopify, online store, AI search",
    "Prijzen": "Free check. Watch EUR 49 per month (EUR 490 per year). Fix EUR 149 per month (EUR 1,490 per year).",
    "Contact": "hello@krilloai.com",
}


def volgende_gids():
    """De eerste gids waar nog niet over beslist is, als taak klaarzetten.
    Er staat er steeds hoogstens een open of lopend."""
    import voorstellen
    voorstellen.maak_tabel()
    lopend = voorstellen._sql("""SELECT count(*) AS n FROM voorstellen WHERE bron = 'gidsen'
                                   AND stand IN ('open', 'akkoord')""") or {}
    if int(lopend.get("n") or 0):
        return None
    for naam, hoe in GIDSEN:
        rij = voorstellen.stel_voor("gidsen", "taak", f"Meld Krillo aan bij {naam}",
                                    waarom=hoe + " De teksten om te plakken staan bij deze taak.",
                                    sleutel=f"gids:{naam.lower()}", minuten=10)
        if rij:
            return rij
    return None


# ------------------------------------------------------------------ uitbreidingen
# Nino, 1 oktober: "denk aan zware uitbreidingen, meer functies, marketing en
# SEO. Peec heeft veel meer. Geef dagelijks voorstellen waar ik alleen akkoord
# op hoef te geven." Elke dag hoogstens een van deze als bouwvoorstel, op
# volgorde van wat een kleine webshop het eerst zou betalen. Akkoord zet hem op
# de bouwlijst; Claude bouwt hem. Het nummer is de stap op de roadmap. De
# leeragent voegt er elke week zijn eigen vondsten aan toe (onderwerp product).
UITBREIDINGEN = [
    (198, "Wekelijkse snelmeting voor klanten: elke week de vijf belangrijkste vragen opnieuw",
     "Nu meten we maandelijks. Wie betaalt en iets verandert, wil binnen een week zien of het werkt. Peec meet "
     "dagelijks. Kost ongeveer 10 cent per klant per week."),
    (180, "Eigen vragen: Watch vijf, Fix vijftien, alleen voor die klant gemeten",
     "Het eerste wat een klant bij Peec doet. De index blijft eerlijk (vaste vragen); de eigen vragen staan alleen "
     "in zijn dashboard."),
    (241, "Concurrent-alarm: bericht zodra een winkel je inhaalt in je top 5",
     "Een reden om elke week te kijken, en de sterkste reden om te blijven betalen. Uit de metingen die er al zijn."),
    (239, "Contentmotor: per verloren vraag een kant-en-klare pagina of blog, Fix zet hem online",
     "Dit is marketing en SEO tegelijk: dezelfde pagina helpt in Google en in AI. Profound en AthenaHQ verkopen "
     "dit los. Bij ons zit het in Fix."),
    (188, "Meer assistenten: Perplexity en Google AI Mode erbij",
     "Peec meet zeven assistenten, wij twee. Google AI Mode is waar de meeste kopers straks zitten."),
    (243, "Vermeldingenplan: op welke review- en vergelijkingssites AI kijkt, en waar jij ontbreekt",
     "AI noemt winkels die op andere sites genoemd worden. Per klant een lijst met de sites waar de top wel staat "
     "en hij niet, met de stappen om erop te komen."),
    (240, "Google en AI naast elkaar: per koopvraag ook de plek in Google",
     "Een winkeleigenaar denkt in Google. Laten zien dat hij in Google op 3 staat en in ChatGPT nergens, maakt het "
     "probleem in een oogopslag duidelijk. Ook verkoopbaar aan SEO-bureaus."),
    (191, "Welke zoekopdrachten AI zelf doet voor het antwoordt (fan-out)",
     "Zegt precies welke woorden op welke pagina moeten staan. Peec toont het; wij koppelen het aan de pagina."),
    (242, "Gestructureerde gegevens (schema) automatisch goedzetten via de Shopify-app",
     "Product, FAQ en bedrijfsgegevens als schema: AI leest het direct. Fix kan het in een klik, zonder dat de "
     "klant iets ziet veranderen."),
    (177, "Producten in ChatGPT Shopping volgen, per product",
     "ChatGPT toont productkaarten met prijs. Welke producten van de klant erin staan en welke niet."),
    (244, "Imago over tijd: hoe AI over je winkel praat, maand op maand",
     "We hebben het al per maand (wat AI zegt). Als lijn over tijd ziet de klant of zijn verhaal aankomt."),
    (245, "Producttitels en -teksten testen: twee versies, meten welke AI oppakt",
     "Fix past een titel aan, de snelmeting kijkt of AI het oppakt. Een echte proef in plaats van een gok."),
    (246, "Wit-label rapport en export voor bureaus (PDF met eigen logo, CSV)",
     "Bureaus verkopen ons door als ze het onder eigen naam kunnen laten zien. Hoort bij het pakket van 490."),
    (247, "Meldingen in Slack of WhatsApp bij een verandering in je plek",
     "Een mail wordt gemist; een melding in Slack niet. Klein om te bouwen."),
    (248, "llms.txt en de instellingen voor AI-robots per winkel goedzetten (Fix)",
     "De robotwacht kijkt al of AI een winkel mag lezen. Fix kan het ook meteen goedzetten."),
]


def volgende_uitbreiding(nu=None):
    """Hoogstens een bouwvoorstel per dag uit UITBREIDINGEN, en niet als er
    nog een open staat."""
    import voorstellen
    voorstellen.maak_tabel()
    rij = voorstellen._sql("""SELECT count(*) FILTER (WHERE stand = 'open') AS open,
                                     count(*) FILTER (WHERE aangemaakt_op > now() - interval '20 hours') AS vandaag
                              FROM voorstellen WHERE bron = 'uitbreidingen'""") or {}
    if int(rij.get("open") or 0) or int(rij.get("vandaag") or 0):
        return None
    for nr, titel, waarom in UITBREIDINGEN:
        if f"uitbreiding:{nr}" in voorstellen.GEBOUWD:
            continue
        v = voorstellen.stel_voor("uitbreidingen", "bouwen", titel, waarom=f"{waarom} (roadmap stap {nr})",
                                  sleutel=f"uitbreiding:{nr}")
        if v:
            return v
    return None


# ------------------------------------------------------------------ dagtaken
# Wat alleen een mens kan, per weekdag. Elke taak is kort en gaat over klanten.
# Komt er een taak van de leeragent bij (een concreet kanaal dat hij vond), dan
# gaat die voor. In het weekend niets: alles loopt vanzelf.
DAGRITME = {
    0: ("Bekijk op /admin/bezoekers waar bezoekers vandaan kwamen deze week, en of er een gids of lijstje "
        "bij zit. Werkt een bron, zeg het tegen Claude: dan zoeken we er meer van.", 10, "/admin/bezoekers"),
    1: ("Keur het artikel van de week goed en deel het op de Krillo-pagina op LinkedIn.", 15, "/admin/artikelen"),
    2: ("Schrijf een behulpzame reactie in een e-commerce groep (Facebook, Reddit r/shopify of een "
        "LinkedIn-groep) op een vraag over vindbaarheid. Link naar de gratis tool, niet naar de prijzen.", 20,
        "/tools"),
    3: ("Kijk in het Shopify Partner Dashboard of de review van de app vragen heeft, en beantwoord ze.", 10,
        "https://partners.shopify.com"),
    4: ("Lees de week: hoeveel mails, hoeveel mensen keken, wie klikte door. Kies het ene ding dat Claude "
        "volgende week moet verbeteren.", 15, "/admin/agents"),
}


def dagtaken(basis_url, te_doen=None, nu=None):
    """De dagtaken voor het ochtendbericht: lijst van dicts {tekst, minuten, link, gedaan_link}.

    Volgorde: eerst beslissen (voorstellen), dan wat moet (antwoorden, Fix),
    dan de taken waar je ja op zei, dan de taak van vandaag."""
    import voorstellen
    nu = nu or datetime.now()
    taken = []
    open_v = voorstellen.open_voorstellen()
    if open_v:
        taken.append({"tekst": f"Zeg ja of nee op {len(open_v)} voorstel(len) hieronder", "minuten": 2 * len(open_v),
                      "link": f"{basis_url}/admin/voorstellen"})
    for tekst, link in (te_doen or []):
        taken.append({"tekst": tekst, "minuten": 10, "link": link})
    for t in voorstellen.lopende_taken()[:3]:
        taken.append({"tekst": t["titel"], "minuten": t.get("minuten") or 20,
                      "link": f"{basis_url}/v/{t['token']}", "gedaan": True})
    ritme = DAGRITME.get(nu.weekday())
    if ritme and not any(t.get("gedaan") for t in taken):
        tekst, minuten, link = ritme
        taken.append({"tekst": tekst, "minuten": minuten,
                      "link": link if link.startswith("http") else f"{basis_url}{link}"})
    return taken


def laatste_verslag():
    try:
        return json.loads(db.get_instelling(SLEUTEL_VERSLAG) or "{}")
    except Exception:
        return {}
