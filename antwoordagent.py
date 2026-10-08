"""De antwoordagent: wie ons terugmailt, krijgt snel een goed antwoord.

WAAROM DIT BESTAAT (stap 126, 28 september). Er gaan elke dag koude mails en
opvolgingen uit. Onder elke mail staat "reply to this email, a person reads
it". Tot nu toe kwam een antwoord in een gewone mailbox, tussen de rest, en
een winkelier die "hoe werkt dat dan?" terugschrijft is de warmste lead die er
is. Die mag niet een dag blijven liggen. En wie "stop" terugschrijft, moet
dezelfde dag van de lijst, ook als hij niet op de afmeldlink klikte.

HOE HET LOOPT
1. Brevo ontvangt de mail op het antwoordadres (in.krilloai.com) en stuurt hem
   als JSON naar /webhooks/inbound/<BREVO_WEBHOOK_SLEUTEL>.
2. Hier: bewaren, de winkel erbij zoeken (op mailadres, anders op domein), en
   bepalen wat voor mail het is:
   - automatisch (afwezigheidsmelding): alleen bewaren, geen ruis;
   - afmelden: METEEN afmelden, zonder AI en zonder te wachten op Nino;
   - interesse, vraag, bezwaar, anders: een concept-antwoord schrijven.
3. Nino krijgt een melding met de tekst, en keurt op /admin/antwoorden goed
   (eventueel na aanpassen) of zet hem op klaar.

REGELS DIE NOOIT LOSSEN
- Afmelden gaat op vaste woorden, niet op een AI-oordeel. Een AI die "stop met
  mailen" verkeerd leest, betekent een klacht.
- Een antwoord gaat NOOIT vanzelf weg. Dit is een gesprek met een echte
  winkelier; een AI die daar iets belooft wat niet klopt, kost meer dan een
  uur wachten.
- Het concept gebruikt alleen vaste feiten (prijzen uit payments.py, zijn
  eigen plek uit de meting). Geen beloftes over resultaat.
"""
import html as _html
import json
import os
import re
import time

import db

MODEL = os.environ.get("ANTWOORD_MODEL", "claude-haiku-4-5-20251001")
BREVO_WEBHOOKS = "https://api.brevo.com/v3/webhooks"
SLEUTEL_DOMEIN = "antwoord_domein"
STANDAARD_DOMEIN = "in.krilloai.com"
TEST_ONDERWERP = "Krillo testantwoord"

# Gratis mailadressen: daar zegt het domein niets over de winkel.
GRATIS = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.nl", "outlook.com",
          "outlook.nl", "live.nl", "live.com", "yahoo.com", "icloud.com", "me.com",
          "ziggo.nl", "kpnmail.nl", "planet.nl", "home.nl", "gmx.de", "gmx.net",
          "web.de", "proton.me", "protonmail.com", "msn.com", "telenet.be", "skynet.be"}

# Afwezig of een bounce: bewaren, niets mee doen.
AUTOMATISCH = re.compile(
    r"out of office|automatic reply|auto.?reply|autoreply|automatisch antwoord|"
    r"afwezig|abwesen|abwesenheit|niet aanwezig|vacation|on leave|"
    r"delivery status notification|undeliverable|mail delivery failed|niet afgeleverd",
    re.I)

# Een ontvangstbevestiging van een klantenservice (29 september: Nino kreeg
# alleen die binnen en moest ze allemaal zelf wegklikken). Bewust ALLEEN zinnen
# die een mens niet zo schrijft: "bedankt voor je bericht" alleen is niet
# genoeg, want zo begint ook een echt antwoord, en een echt antwoord missen is
# een gemiste klant.
ONTVANGSTBEVESTIGING = re.compile(
    r"(we|wij) hebben (je|jouw|uw) (e-?mail|bericht|vraag|aanvraag)( in goede orde| goed)? ontvangen|"
    r"(je|jouw|uw) (e-?mail|bericht|vraag|aanvraag) is (in goede orde |goed )?ontvangen|"
    r"we have received your (e-?mail|message|request|enquiry|inquiry)|"
    r"your (e-?mail|message|request) has been received|"
    r"ticket ?(nummer|number|nr|id|#)|case (number|id)|referentienummer|"
    r"this is an automated|dit is een automatisch|automatisch gegenereerd|"
    r"do not reply to this|niet (op )?(deze|dit) (e-?mail|bericht) (be)?antwoorden|"
    r"wir haben ihre (nachricht|anfrage|e-?mail) erhalten",
    re.I)
AFZENDER_AUTOMATISCH = re.compile(r"^(no-?reply|do-?not-?reply|noreply|mailer-daemon|postmaster|"
                                  r"notifications?|autoresponder|auto)@", re.I)


# Een helpdesksysteem of AI-bot van de winkel antwoordt namens de eigenaar (8
# oktober: tuinshop.nl kreeg onze koude mail en hun helpdesk-AI schreef terug
# "Based on the text you shared..."). Dat is geen gesprek met de eigenaar en
# ook geen afwezigheidsmelding: het is een deur waar we langs moeten. Daarom een
# eigen soort met een concept dat vraagt om doorsturen, in plaats van een
# gewoon verkoopconcept aan een bot.
HELPDESK_DOMEINEN = ("trengomail.com", "trengo.com", "zendesk.com", "zendesk.net", "freshdesk.com",
                     "freshdesk.net", "freshservice.com", "gorgias.com", "gorgias.io", "helpscout.net",
                     "helpscout.com", "intercom.io", "intercom-mail.com", "intercom.com", "kustomer.com",
                     "kustomerapp.com", "helpshift.com", "front.com", "frontapp.com", "reamaze.com",
                     "hubspot.com", "hs-inbox.com", "deskpro.com", "tidio.net", "crisp.chat", "gladly.com",
                     "richpanel.com", "livechat.com", "teamwork.com", "customerly.io", "ada.cx")
# Zinnen die alleen een bot schrijft die inhoudelijk antwoordt.
HELPDESK_ZINNEN = re.compile(
    r"based on the text you shared|(i am|i'm|this is) (an? )?(ai|virtual) (assistant|agent)|"
    r"our (ai|virtual) assistant|onze (ai|virtuele)[- ]?(assistent|medewerker)|"
    r"powered by (zendesk|freshdesk|gorgias|intercom|trengo|help ?scout|kustomer)", re.I)
# Zinnen van een kale ontvangstbevestiging (ticketnummer, 'dit is een automatisch
# bericht'). Een korte bevestiging blijft 'automatisch' (stil weggeklikt, zoals
# sinds 29 september); pas als de bot er een echt antwoord omheen schrijft (een
# langer bericht) willen we dat Nino het ziet en vragen om door te sturen.
HELPDESK_BEVESTIGING = re.compile(
    r"this is an automated|dit is een automatisch|ticket ?(#|number|nr)|your ticket|case (number|id)|referentienummer",
    re.I)
HELPDESK_LANG = 200


def is_helpdesk(van, onderwerp, tekst):
    """Komt dit uit een helpdesksysteem of van een AI-bot van de winkel?
    Op het domein van de afzender (ook subdomeinen), of op zinnen die een mens
    niet zo schrijft."""
    domein = (van or "").lower().split("@")[-1]
    if any(domein == d or domein.endswith("." + d) for d in HELPDESK_DOMEINEN):
        return True
    if HELPDESK_ZINNEN.search(onderwerp or "") or HELPDESK_ZINNEN.search((tekst or "")[:800]):
        return True
    return len((tekst or "").strip()) >= HELPDESK_LANG and bool(
        HELPDESK_BEVESTIGING.search(onderwerp or "") or HELPDESK_BEVESTIGING.search((tekst or "")[:800]))


def _kop_automatisch(it):
    """De kopregels van de mail zelf zeggen het soms al (RFC 3834)."""
    koppen = it.get("Headers") or it.get("headers") or {}
    if not isinstance(koppen, dict):
        return False
    k = {str(a).lower(): str(b).lower() for a, b in koppen.items()}
    if k.get("auto-submitted", "no") not in ("", "no"):
        return True
    if "x-autoreply" in k or "x-autorespond" in k:
        return True
    return k.get("precedence", "") in ("auto_reply", "bulk", "junk")

# Afmelden. Liever een keer te vaak afmelden dan een keer te weinig: wie "not
# interested" schrijft, wil ook geen tweede opvolging.
AFMELDEN = re.compile(
    r"unsubscri|uitschrijv|afmeld|meld (me|mij) af|remove (me|us|my)|take (me|us) off|"
    r"niet meer (mailen|e-?mailen|benaderen)|geen (mail|e-?mail|berichten) meer|"
    r"geen interesse|niet ge[iï]nteresseerd|not interested|no interest|kein interesse|"
    r"stop (e-?mailing|mailing|sending|contacting)|stop met mailen|"
    r"do(n'?t| not) (e-?mail|mail|contact)|niet (meer )?contacteren|van (jullie|de) lijst",
    re.I)

SOORTEN = ("interesse", "vraag", "bezwaar", "anders")


# ---------------------------------------------------------------- binnenkomst

def _eerste(waarde):
    if isinstance(waarde, list):
        return waarde[0] if waarde else ""
    return waarde or ""


def _zonder_citaat(tekst):
    """Alleen wat hij zelf schreef, niet onze mail eronder."""
    regels = []
    for regel in (tekst or "").splitlines():
        s = regel.strip()
        # De onzichtbare meetlink van Brevo (r.hello.krilloai.com/tr/op/...)
        # komt als tekstregel mee; die hoort niet bij wat hij schreef.
        if re.fullmatch(r"\[?[^\s]*/tr/(op|cl)/[^\s]*(\([^)]*\))?", s):
            continue
        if s.startswith(">"):
            break
        if re.match(r"^(on .+ wrote:|op .+ schreef.*:|am .+ schrieb.*:|-----\s*original message|"
                    r"van: |from: |-----oorspronkelijk bericht)", s, re.I):
            break
        regels.append(regel)
    return "\n".join(regels).strip()


def lees_brevo(data):
    """Maakt van wat Brevo stuurt een lijst gewone berichten. Faalt nooit."""
    if isinstance(data, dict):
        items = data.get("items") or [data]
    elif isinstance(data, list):
        items = data
    else:
        items = []
    uit = []
    for it in items:
        if not isinstance(it, dict):
            continue
        van = it.get("From") or it.get("from") or {}
        if isinstance(van, str):
            adres, naam = van, ""
        else:
            adres, naam = van.get("Address") or van.get("address") or "", van.get("Name") or ""
        tekst = (it.get("ExtractedMarkdownMessage") or it.get("RawTextBody") or "")
        if not tekst and it.get("RawHtmlBody"):
            tekst = re.sub(r"<br\s*/?>|</p>", "\n", it["RawHtmlBody"], flags=re.I)
            tekst = _html.unescape(re.sub(r"<[^>]+>", "", tekst))
        bericht_id = (_eerste(it.get("MessageId")) or _eerste(it.get("Uuid"))
                      or f"{adres}|{it.get('Subject')}|{it.get('SentAtDate')}")
        uit.append({"bericht_id": str(bericht_id)[:300], "van": adres.strip().lower(),
                    "naam": (naam or "").strip()[:200], "onderwerp": (it.get("Subject") or "").strip()[:300],
                    "tekst": _zonder_citaat(tekst)[:6000], "automatisch_kop": _kop_automatisch(it)})
    return uit


def _sql(opdracht, waarden=None, een=False, alles=False):
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
                if alles:
                    return [dict(r) for r in cur.fetchall()]
                rij = cur.fetchone()
                return dict(rij) if rij else None
    finally:
        conn.close()


def zoek_winkel(adres):
    """Welke winkel dit is: eerst op het adres waar wij heen mailden, dan op
    klant, dan op het domein (info@ schreef, jan@ antwoordt)."""
    adres = (adres or "").strip().lower()
    if not adres:
        return None
    rij = _sql("SELECT webshop_url FROM benadering WHERE lower(email) = %s LIMIT 1", (adres,))
    if rij:
        return rij["webshop_url"]
    rij = _sql("SELECT webshop_url FROM klanten WHERE lower(email) = %s LIMIT 1", (adres,))
    if rij:
        return rij["webshop_url"]
    domein = adres.split("@")[-1]
    if not domein or domein in GRATIS:
        return None
    for r in _sql("SELECT webshop_url FROM benadering WHERE lower(webshop_url) LIKE %s LIMIT 20",
                  ("%" + domein + "%",), alles=True) or []:
        host = re.sub(r"^https?://(www\.)?", "", r["webshop_url"].lower()).split("/")[0]
        if host == domein:
            return r["webshop_url"]
    return None


def winkel_uit_tekst(onderwerp, tekst):
    """Bij een helpdeskantwoord zegt het afzenderdomein (trengomail.com) niets
    over de winkel. De bot noemt de winkel wel bij naam ("tuinshop.nl is not one
    of..."), dus zoeken we een adres uit onze benaderlijst in zijn tekst. Zonder
    dit blijft de winkel 'niet beantwoord' en gaan de opvolgmails gewoon door."""
    ruimte = f"{onderwerp or ''} {tekst or ''}".lower()
    for naam in set(re.findall(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.[a-z]{2,}", ruimte)):
        for r in _sql("SELECT webshop_url FROM benadering WHERE lower(webshop_url) LIKE %s LIMIT 20",
                      ("%" + naam + "%",), alles=True) or []:
            host = re.sub(r"^https?://(www\.)?", "", r["webshop_url"].lower()).split("/")[0]
            if host == naam.removeprefix("www."):
                return r["webshop_url"]
    return None


def soort_van(onderwerp, tekst, model=None, van=None, kop_automatisch=False):
    """Wat voor mail het is. Automatisch en afmelden op vaste woorden; de rest
    mag een model inschatten, en zonder model is het een vraag."""
    if onderwerp and TEST_ONDERWERP.lower() in onderwerp.lower():
        return "test"
    # Helpdesk vooraan (eerder dan 'automatisch', want hun ontvangstbevestiging
    # en bot-antwoorden hebben woorden als 'ticket #' en 'automated'). Wie
    # daarin toch duidelijk afmeldt, valt door naar afmelden: dat moet altijd werken.
    if is_helpdesk(van, onderwerp, tekst) and not AFMELDEN.search(tekst or "") \
            and not AFMELDEN.search(onderwerp or ""):
        return "helpdesk"
    if AUTOMATISCH.search(onderwerp or "") or AUTOMATISCH.search((tekst or "")[:300]):
        return "automatisch"
    kaal = re.sub(r"[^a-z]", "", (tekst or "").lower())
    if kaal in ("stop", "nee", "no", "nein", "remove", "unsubscribe") or AFMELDEN.search(tekst or "") \
            or AFMELDEN.search(onderwerp or ""):
        return "afmelden"
    # Na afmelden: wie in een bevestiging toch "geen interesse" schrijft, is
    # een mens, en afmelden moet altijd werken.
    if kop_automatisch or AFZENDER_AUTOMATISCH.search(van or "") \
            or ONTVANGSTBEVESTIGING.search(onderwerp or "") or ONTVANGSTBEVESTIGING.search((tekst or "")[:600]):
        return "automatisch"
    if model is not None:
        try:
            s = model(onderwerp, tekst)
            if s in SOORTEN:
                return s
        except Exception as e:
            print(f"Antwoord indelen via het model mislukt: {e}")
    return "vraag"


# ---------------------------------------------------------------- het concept

def feiten(webshop_url, basis_url):
    """Alles wat het concept mag zeggen. Niets anders."""
    import payments
    f = {
        "watch_prijs": payments.PAKKETTEN["watch"]["prijs"]["value"].split(".")[0],
        "fix_prijs": payments.PAKKETTEN["fix"]["prijs"]["value"].split(".")[0],
        "pagina": None, "plek": None, "categorie": None, "winkel": None,
    }
    if webshop_url:
        f["winkel"] = re.sub(r"^https?://(www\.)?", "", webshop_url).rstrip("/")
        try:
            token = db.get_benchmark_token(webshop_url)
            if token:
                f["pagina"] = f"{basis_url}/uitkomst/{token}"
        except Exception:
            pass
        try:
            rij = _sql("""SELECT u.positie, u.categorie FROM categorie_uitkomsten u
                            JOIN categorie_rondes r ON r.id = u.ronde
                           WHERE u.webshop_url = %s AND r.afgerond_op IS NOT NULL
                        ORDER BY u.ronde DESC LIMIT 1""", (webshop_url,))
            if rij:
                f["plek"], f["categorie"] = rij.get("positie"), rij.get("categorie")
        except Exception:
            pass
    return f


def _schoon(tekst):
    # Geen lange streepjes (huisregel), en niets wat op HTML lijkt.
    tekst = (tekst or "").replace("—", ",").replace("–", "-")
    return re.sub(r"<[^>]+>", "", tekst).strip()


def vast_concept(soort, naam, f):
    """Zonder model: kort en eerlijk, en Nino vult aan."""
    aanhef = f"Hi {naam.split()[0]}," if naam else "Hi,"
    pagina = f"\n\nYour own page is here: {f['pagina']}" if f.get("pagina") else ""
    return (f"{aanhef}\n\nThanks for your reply. [Nino: answer the question here]\n\n"
            f"In short: Watch is EUR {f['watch_prijs']} a month and shows each month where "
            f"AI assistants place your store and what to fix. Fix is EUR {f['fix_prijs']} a "
            f"month and we carry out those fixes in your store. You can cancel every month."
            f"{pagina}")


def _nederlandse_winkel(webshop_url, van, tekst):
    """Antwoorden in het Nederlands als de winkel Nederlands is: .nl of .be, of
    de bot zelf schreef Nederlands."""
    host = re.sub(r"^https?://(www\.)?", "", (webshop_url or "").lower()).split("/")[0]
    if host.endswith((".nl", ".be")):
        return True
    if re.search(r"\b(een|het|niet|wij|jullie|bedankt|geen|webwinkel|onze)\b", (tekst or "").lower()):
        return True
    return False


def helpdesk_concept(naam, f, nederlands=False):
    """Kort verzoek aan de bot of medewerker: stuur dit door naar de eigenaar of
    marketing. Alleen vaste feiten, geen verkooppraatje richting een bot."""
    winkel = f.get("winkel") or ("your store" if not nederlands else "jullie winkel")
    pagina = f.get("pagina")
    if nederlands:
        plek = (f" Op dit moment staat {winkel} op plek {f['plek']} in onze index voor {f.get('categorie') or 'jullie categorie'}."
                if f.get("plek") else "")
        link = f"\n\nDe uitslag voor jullie winkel staat hier: {pagina}" if pagina else ""
        return (f"Hallo,\n\nDit antwoord kwam van een automatisch helpdesksysteem, dus ik weet niet of er "
                f"een mens meeleest. Zou u deze mail willen doorsturen naar de eigenaar of naar degene die "
                f"de marketing doet?\n\nKort waar het om gaat: wij meten of AI-assistenten zoals ChatGPT "
                f"en Gemini {winkel} aanbevelen bij vragen van kopers.{plek}{link}\n\n"
                f"Alvast bedankt voor het doorsturen.")
    plek = (f" Right now {winkel} is number {f['plek']} in our index for {f.get('categorie') or 'its category'}."
            if f.get("plek") else "")
    link = f"\n\nThe result for your store is here: {pagina}" if pagina else ""
    return (f"Hi,\n\nThis reply came from an automatic helpdesk system, so I am not sure a person reads it. "
            f"Could you please forward this email to the owner or to whoever handles marketing?\n\n"
            f"In short: we measure whether AI assistants such as ChatGPT and Gemini recommend {winkel} "
            f"when shoppers ask buying questions.{plek}{link}\n\nThank you for passing it on.")


def schrijf_concept(bericht, f, soort, client=None):
    """Een concept in de taal van zijn mail. Met model als dat er is."""
    naam = bericht.get("naam") or ""
    if client is None:
        return vast_concept(soort, naam, f)
    afzender = (os.environ.get("AFZENDER_NAAM") or "Nino").strip()
    regels = [
        f"Watch: EUR {f['watch_prijs']} per month. Every month we ask ChatGPT and Gemini the buying "
        "questions in the store's category and show its rank, which questions it loses and to whom, "
        "and a list of fixes (texts ready to copy) to do yourself.",
        f"Fix: EUR {f['fix_prijs']} per month. Everything in Watch, and we carry out the fixes in the "
        "store. On Shopify the Krillo app does it; on other platforms we need access.",
        "Both are monthly, cancel any time. Within 14 days you can withdraw.",
        "Nobody can promise a place in AI answers. We measure honestly and improve what the store "
        "controls: clear product texts, facts, and pages AI assistants can read.",
    ]
    if f.get("winkel"):
        regels.append(f"Their store: {f['winkel']}.")
    if f.get("plek"):
        regels.append(f"Their latest rank in our index for {f.get('categorie') or 'their category'}: "
                      f"number {f['plek']}.")
    if f.get("pagina"):
        regels.append(f"Their own Krillo page (link to share): {f['pagina']}")
    prompt = (
        "You write a reply for Krillo, a small company that measures how often AI assistants "
        "recommend a webshop. A store owner answered our email. Write the reply that "
        f"{afzender} (founder) will send after reading it.\n\n"
        "FACTS (use only these; do not invent numbers, features, clients or guarantees):\n- "
        + "\n- ".join(regels) + "\n\n"
        "RULES: Write in the same language as their message. Plain, friendly, short (max 110 "
        "words). Answer what they actually asked. If the facts do not answer it, say you will "
        "check and come back to them, and do not guess. No long dashes. No sales pressure. "
        "If they say they are not a webshop, or that we put them in the wrong category: say plainly "
        "that this was OUR mistake (our system placed them there), not an AI assistant's; apologise "
        "once; say we have taken them out of that ranking and will not email them about it again. "
        "No sales pitch in that case. "
        "Do NOT end with a greeting or a name: the signature is added automatically. "
        "No subject line, only the body.\n\n"
        f"Their subject: {bericht.get('onderwerp')}\n"
        f"Their message:\n{(bericht.get('tekst') or '')[:3000]}")
    gestart = time.monotonic()
    antwoord = client.messages.create(model=MODEL, max_tokens=500,
                                      messages=[{"role": "user", "content": prompt}])
    try:
        import kosten
        kosten.registreer_aanroep(provider="anthropic", model=MODEL,
                                  invoer_tokens=antwoord.usage.input_tokens,
                                  uitvoer_tokens=antwoord.usage.output_tokens,
                                  soort="antwoordagent",
                                  duur_ms=int((time.monotonic() - gestart) * 1000))
    except Exception:
        pass
    tekst = _haal_groet_weg(_schoon(antwoord.content[0].text), afzender)
    return tekst or vast_concept(soort, naam, f)


def _haal_groet_weg(tekst, afzender):
    """De handtekening komt er bij het versturen onder; een groet of naam aan
    het eind zou er dan dubbel staan. Het model krijgt dat te horen, maar we
    vertrouwen er niet op."""
    regels = (tekst or "").rstrip().split("\n")
    groeten = ("kind regards", "best regards", "regards", "best", "cheers", "thanks", "thank you",
               "met vriendelijke groet", "vriendelijke groet", "groeten", "groet", "hartelijke groet",
               "mit freundlichen grüßen", "viele grüße", "cordialement", "bien à vous")
    while regels and (regels[-1].strip().strip(",.!").lower() in groeten
                      or regels[-1].strip().strip(",.!").lower() == afzender.lower()
                      or not regels[-1].strip()):
        regels.pop()
    return "\n".join(regels).strip()


def _model_indeler(client):
    def indelen(onderwerp, tekst):
        antwoord = client.messages.create(
            model=MODEL, max_tokens=20,
            messages=[{"role": "user", "content": (
                "A store owner replied to our email about AI visibility. Classify the reply as "
                "exactly one word: interesse (wants to buy, try or talk), vraag (asks something), "
                "bezwaar (objection, doubt, too expensive, already has someone), anders (anything "
                f"else).\n\nSubject: {onderwerp}\nMessage: {(tekst or '')[:1500]}\n\nOne word:")}])
        return re.sub(r"[^a-z]", "", antwoord.content[0].text.lower())
    return indelen


# ---------------------------------------------------------------- verwerken

def _eigen_adres(adres, onderwerp=""):
    """Mail die we NIET verwerken: van ons eigen domein, of Nino die op een
    melding van Krillo antwoordt (dan komt er "Re: Krillo:" voor). Een gewone
    mail van Nino zelf verwerken we wel: zo kan hij de agent testen (28
    september: zijn testmail verdween stil, omdat al zijn mail genegeerd werd)."""
    beheer = (os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL") or "").strip().lower()
    if adres.endswith("@krilloai.com") or adres.endswith(".krilloai.com"):
        return True
    return bool(beheer and adres == beheer and (onderwerp or "").lower().lstrip().startswith(("re: krillo:", "fwd: krillo:")))


def verwerk(data, basis_url, melden, client=None):
    """Alles wat Brevo stuurde verwerken. Geeft per bericht wat ermee gebeurde."""
    if client is None:
        try:
            import categoriemeting
            client = categoriemeting._client()
        except Exception:
            client = None
    verslag = []
    for b in lees_brevo(data):
        if not b["van"]:
            continue
        soort = soort_van(b["onderwerp"], b["tekst"], _model_indeler(client) if client else None,
                          van=b.get("van"), kop_automatisch=b.get("automatisch_kop", False))
        if soort != "test" and _eigen_adres(b["van"], b["onderwerp"]):
            # Nino die op een melding antwoordt, of een lus: niet verwerken.
            verslag.append({"van": b["van"], "soort": "eigen"})
            continue
        url = zoek_winkel(b["van"])
        if not url and soort == "helpdesk":
            url = winkel_uit_tekst(b["onderwerp"], b["tekst"])
        rij = _sql("""INSERT INTO antwoorden (bericht_id, van, naam, onderwerp, tekst, webshop_url, soort)
                      VALUES (%s, %s, %s, %s, %s, %s, %s)
                      ON CONFLICT (bericht_id) DO NOTHING RETURNING id""",
                   (b["bericht_id"], b["van"], b["naam"], b["onderwerp"], b["tekst"], url, soort), een=True)
        if not rij:
            verslag.append({"van": b["van"], "soort": "dubbel"})
            continue
        nr = rij["id"]
        if url:
            _sql("UPDATE benadering SET antwoord_op = coalesce(antwoord_op, now()) WHERE webshop_url = %s",
                 (url,))
        if soort in ("test", "automatisch"):
            _sql("UPDATE antwoorden SET stand = 'klaar', afgehandeld_op = now() WHERE id = %s", (nr,))
        elif soort == "afmelden":
            gelukt = db.meld_benadering_af(url) if url else False
            if not gelukt:
                # Winkel niet gevonden: dan in elk geval het adres zelf van de lijst.
                _sql("UPDATE benadering SET afgemeld = TRUE, stand = 'afgevallen' WHERE lower(email) = %s",
                     (b["van"],))
            _sql("UPDATE antwoorden SET stand = 'afgemeld', afgehandeld_op = now() WHERE id = %s", (nr,))
            melden("Afgemeld via een antwoord",
                   f"{_html.escape(b['van'])} ({_html.escape(url or 'winkel niet gevonden')}) schreef terug "
                   f"en is afgemeld. Hun tekst:<br><em>{_html.escape(b['tekst'][:600])}</em>")
        elif soort == "helpdesk":
            # Geen model en geen verkooptekst: een kort verzoek om door te sturen.
            # Nino moet het nog steeds goedkeuren (een antwoord gaat nooit vanzelf weg).
            f = feiten(url, basis_url)
            concept = helpdesk_concept(b["naam"], f, _nederlandse_winkel(url, b["van"], b["tekst"]))
            _sql("UPDATE antwoorden SET concept = %s, stand = 'concept' WHERE id = %s", (concept, nr))
            melden("Automatisch helpdeskantwoord (geen mens)",
                   f"<strong>{_html.escape(b['van'])}</strong> ({_html.escape(url or b['van'])}) antwoordde met een "
                   f"AUTOMATISCH HELPDESKANTWOORD, waarschijnlijk een AI-bot en geen eigenaar. Hun tekst:<br>"
                   f"<em>{_html.escape(b['tekst'][:800])}</em><br><br>Er staat een kort concept klaar op "
                   f"{basis_url}/admin/antwoorden dat vraagt om door te sturen naar de eigenaar of marketing. "
                   f"Opvolgmails naar dit adres zijn gestopt. Het is geen warme lead, geen haast.")
        else:
            try:
                concept = schrijf_concept(b, feiten(url, basis_url), soort, client=client)
            except Exception as e:
                print(f"Concept-antwoord schrijven mislukt: {e}")
                concept = vast_concept(soort, b["naam"], feiten(url, basis_url))
            _sql("UPDATE antwoorden SET concept = %s, stand = 'concept' WHERE id = %s", (concept, nr))
            kop = {"interesse": "Een winkel wil verder", "bezwaar": "Een winkel twijfelt"}.get(
                soort, "Een winkel mailde terug")
            melden(kop,
                   f"<strong>{_html.escape(b['naam'] or b['van'])}</strong> ({_html.escape(url or b['van'])}) "
                   f"schreef:<br><em>{_html.escape(b['tekst'][:1500])}</em><br><br>Er staat een "
                   f"concept-antwoord klaar op {basis_url}/admin/antwoorden. Antwoord liefst binnen het uur.")
        verslag.append({"van": b["van"], "soort": soort, "winkel": url, "id": nr})
    return verslag


# ---------------------------------------------------------------- het scherm

def lijst(limiet=60):
    return _sql("SELECT * FROM antwoorden ORDER BY (stand = 'concept') DESC, ontvangen_op DESC LIMIT %s",
                (limiet,), alles=True) or []


def wachtend_sinds(uren=24):
    rij = _sql("SELECT count(*) AS n FROM antwoorden WHERE stand = 'concept' "
               "AND ontvangen_op < now() - make_interval(hours => %s)", (uren,), een=True)
    return int((rij or {}).get("n") or 0)


def verstuur(nr, tekst):
    """Het (aangepaste) antwoord versturen, als gewone mail, met Re: ervoor."""
    import emailing
    rij = _sql("SELECT * FROM antwoorden WHERE id = %s", (nr,), een=True)
    if not rij or rij["stand"] != "concept" or not (tekst or "").strip():
        return False
    onderwerp = rij.get("onderwerp") or "Krillo"
    if not onderwerp.lower().startswith("re:"):
        onderwerp = "Re: " + onderwerp
    gelukt = emailing.send_antwoord(rij["van"], onderwerp, _schoon(tekst))
    if gelukt:
        _sql("UPDATE antwoorden SET stand = 'verstuurd', concept = %s, afgehandeld_op = now() WHERE id = %s",
             (_schoon(tekst), nr))
    return gelukt


def klaar(nr):
    _sql("UPDATE antwoorden SET stand = 'klaar', afgehandeld_op = now() WHERE id = %s AND stand = 'concept'",
         (nr,))


def domein():
    return (db.get_instelling(SLEUTEL_DOMEIN) or STANDAARD_DOMEIN).strip().lower()


def koppel_brevo(basis_url, sleutel, domein_naam=None, post=None):
    """Zet bij Brevo de doorsturing aan, met de Brevo-sleutel die al in Render
    staat. Zo hoeft er geen sleutel door iemands handen. Geeft (gelukt, tekst)."""
    import requests
    api = (os.environ.get("BREVO_API_KEY") or "").strip()
    if not api:
        return False, "BREVO_API_KEY staat niet in Render."
    if not sleutel:
        return False, "BREVO_WEBHOOK_SLEUTEL staat niet in Render."
    domein_naam = (domein_naam or domein()).strip().lower()
    post = post or requests.post
    try:
        r = post(BREVO_WEBHOOKS, headers={"api-key": api, "accept": "application/json",
                                          "content-type": "application/json"},
                 json={"type": "inbound", "events": ["inboundEmailProcessed"],
                       "url": f"{basis_url}/webhooks/inbound/{sleutel}", "domain": domein_naam,
                       "description": "Krillo antwoordagent"}, timeout=15)
    except Exception as e:
        return False, f"Brevo niet bereikt: {e}"
    if r.status_code >= 300:
        return False, f"Brevo zei {r.status_code}: {r.text[:300]}"
    db.zet_instelling(SLEUTEL_DOMEIN, domein_naam)
    db.zet_instelling("antwoord_gekoppeld", json.dumps({"domein": domein_naam, "op": time.time()}))
    return True, f"Gekoppeld: mail aan elk adres op {domein_naam} komt nu bij de antwoordagent."


def ruim_automatische_op():
    """Concepten die achteraf een ontvangstbevestiging blijken (de herkenning
    werd 29 september beter), alsnog afhandelen. Zo hoeft Nino ze niet weg te
    klikken. Geeft het aantal."""
    rijen = _sql("SELECT id, van, onderwerp, tekst FROM antwoorden WHERE stand = 'concept'", alles=True) or []
    n = 0
    for r in rijen:
        if soort_van(r.get("onderwerp"), r.get("tekst"), van=r.get("van")) == "automatisch":
            _sql("UPDATE antwoorden SET soort = 'automatisch', stand = 'klaar', afgehandeld_op = now() "
                 "WHERE id = %s", (r["id"],))
            n += 1
    return n
