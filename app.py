"""
Krillo - lokale ontwikkelserver / webserver.

Dit koppelt de landingspagina aan de echte scan-logica, zodat de
"Scan gratis"-knop een werkelijk resultaat teruggeeft, en aan de
Mollie-betaalkoppeling voor de audit en het abonnement.

Starten:
    pip install -r requirements.txt
    python3 app.py

Ga daarna naar http://127.0.0.1:5000 in je browser.
"""

import hmac
import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from flask import (Flask, request, jsonify, render_template, redirect, Response,
                   has_request_context, session, url_for)
import scan_engine
from scan_engine import run_scan
import payments
import emailing
import ai_content
import db
import artikelen
import koopvragen
import kosten
import paginataal
import winkelvinder
import metingen
import actieplan
import beoordeling
import bronnen
import controle
import verklaring
import waarschuwing
import zichtbaarheid
import benchmark
import markt
import shopify_app
import shopify_werk
import toepasmodule
import shopify_billing
import benadering

app = Flask(__name__)
db.init_db()


def get_base_url():
    """Geeft de basis-URL van de site, werkt zowel lokaal als op Render."""
    configured = os.environ.get("BASE_URL")
    if configured:
        return configured.rstrip("/")
    # Buiten een bezoek aan de site is er geen verzoek om het adres uit te
    # halen. Dat is niet zeldzaam: de ronde van de benadering, de wekelijkse
    # klantketen en de cron-taken draaien allemaal op een eigen draad. Zonder
    # deze terugval gooit Flask daar "Working outside of request context", en
    # dan mislukt elke mail die een link nodig heeft. Stil, want de fout wordt
    # verderop opgevangen en de winkel blijft gewoon op zijn oude stand staan.
    if has_request_context():
        return request.url_root.rstrip("/")
    return "https://krillo.nl"


# Vanaf hoeveel gescande webshops wij dat aantal op de site zetten.
MINIMUM_VOOR_TELLER = int(os.environ.get("MINIMUM_VOOR_TELLER", "50"))


@app.route("/")
def home():
    # Het aantal gescande webshops als sociaal bewijs. Onder een ondergrens
    # laten wij het weg: "wij scanden al 3 webshops" is slechter dan niets, want
    # het zegt precies hoe klein je bent op de plek waar je vertrouwen wilt
    # wekken. Mislukt het tellen, dan komt er 0 uit en valt het vanzelf weg.
    try:
        gescand = db.tel_gescande_webshops()
    except Exception as e:
        print(f"Teller ophalen mislukt: {e}")
        gescand = 0
    return render_template("index.html",
                           gescand=gescand if gescand >= MINIMUM_VOOR_TELLER else None,
                           eigen_cijfer=_eigen_benchmarkcijfer())


def _eigen_benchmarkcijfer():
    """Het eigen cijfer over Nederlandse webshops, of None.

    De probleemsectie op de homepage leunt op een Amerikaans onderzoek naar
    21.000 vermeldingen. Dat is een goed cijfer maar het is niet van ons, het
    gaat over merken en niet over Nederlandse webshops, en het is precies het
    soort verwijzing waar de doelgroep overheen leest.

    Zodra wij genoeg winkels zelf gemeten hebben is er een beter cijfer: hoeveel
    Nederlandse webshops bij koopvragen NOOIT genoemd worden. Dat is van ons, het
    is controleerbaar, en het is de enige reden om over Krillo te schrijven die
    geen verkooppraatje is.

    Onder de ondergrens geven wij None terug en blijft het Amerikaanse cijfer
    staan. Een eigen cijfer over negen winkels is geen onderzoek, en het zo
    noemen is precies de overpromising waar Krillo van weg wil blijven. Dit gaat
    dus vanzelf aan zodra het klopt, zonder dat er iemand aan te pas komt."""
    try:
        cijfers = benchmark.tel_op(db.benchmark_regels())
    except Exception as e:
        print(f"Eigen benchmarkcijfer ophalen mislukt: {e}")
        return None
    gemeten = cijfers.get("gemeten") or 0
    if gemeten < MINIMUM_WINKELS_VOOR_VERGELIJKING:
        return None
    nooit = cijfers.get("nooit_genoemd") or 0
    if not nooit:
        return None
    return {"gemeten": gemeten, "nooit": nooit,
            "deel": round(nooit * 100 / gemeten)}


@app.route("/privacybeleid")
def privacybeleid():
    return render_template("privacybeleid.html")


@app.route("/voorwaarden")
def voorwaarden():
    return render_template("voorwaarden.html")


@app.route("/veelgestelde-vragen")
def veelgestelde_vragen():
    return render_template("faq.html")


@app.route("/zo-meten-we")
def zo_meten_we():
    return render_template("zo-meten-we.html")


@app.route("/over-ons")
def over_ons():
    return render_template("over-ons.html")


@app.route("/herroepen")
def herroepen_pagina():
    return render_template("herroepen.html")


@app.route("/api/herroepen", methods=["POST"])
def api_herroepen():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    toelichting = (data.get("toelichting") or "").strip()
    if not email:
        return jsonify({"error": "Vul het e-mailadres in waarmee je hebt besteld."}), 400

    nummer = db.leg_herroeping_vast(email, webshop_url, toelichting)
    if nummer is None:
        # Niets vastgelegd. Dan NIET bevestigen dat we het ontvangen hebben:
        # dit is een wettelijk verzoek met een termijn van veertien dagen, en
        # een bevestiging op iets dat nergens staat is het ergste antwoord.
        print(f"HERROEPING NIET VASTGELEGD voor {email} ({webshop_url}). "
              f"Toelichting: {toelichting}")
        return jsonify({
            "error": "Het opslaan is niet gelukt. Mail je herroeping naar "
                     "hallo@krillo.nl, dan verwerken we hem handmatig. "
                     "Je herroepingsrecht blijft gewoon geldig."
        }), 500
    emailing.send_herroeping_bevestiging(email, nummer, webshop_url)
    beheerder = os.environ.get("BEHEERDER_EMAIL")
    if beheerder:
        emailing.send_herroeping_melding(beheerder, email, webshop_url, toelichting, nummer)
    return jsonify({"ok": True})


@app.route("/api/opzeggen/<klant_token>", methods=["POST"])
def api_opzeggen(klant_token):
    klant = db.get_klant(klant_token)
    if klant is None:
        return jsonify({"error": "Deze pagina is niet meer geldig."}), 404

    abonnement = payments.zoek_abonnement(klant["webshop_url"])
    if abonnement is None:
        return jsonify({"error": "We konden geen lopend abonnement vinden. Mail hallo@krillo.nl, dan zoeken we het uit."}), 400

    resultaat = payments.zeg_abonnement_op(abonnement["customer_id"], abonnement["subscription_id"])
    if "error" in resultaat:
        return jsonify(resultaat), 400

    emailing.send_opzegging_bevestiging(klant["email"], klant["webshop_url"])
    beheerder = os.environ.get("BEHEERDER_EMAIL")
    if beheerder:
        emailing.send_email(beheerder, "Opzegging bij Krillo",
                             f"<p>{klant['email']} heeft de monitoring voor {klant['webshop_url']} opgezegd.</p>")
    return jsonify({"ok": True})


@app.route("/artikelen")
def artikelen_overzicht():
    return render_template("artikelen.html", artikelen=artikelen.ARTIKELEN)


@app.route("/artikelen/<slug>")
def artikel_pagina(slug):
    artikel = artikelen.get_artikel(slug)
    if artikel is None:
        return render_template("fout.html"), 404
    andere = [a for a in artikelen.ARTIKELEN if a["slug"] != slug][:3]
    return render_template("artikel.html", artikel=artikel, andere=andere)


@app.errorhandler(404)
def pagina_niet_gevonden(e):
    return render_template("fout.html"), 404


@app.route("/robots.txt")
def robots_txt():
    # LET OP: één groep per User-agent. Twee keer "User-agent: *" in hetzelfde
    # bestand is precies de fout waar Krillo bij klanten op controleert: de
    # meeste robots pakken dan alleen de eerste groep en negeren de tweede, en
    # dan staan de privépagina's alsnog open. Nieuwe verboden horen dus hier
    # bij de eerste groep en niet onderaan in een tweede.
    inhoud = """User-agent: *
Allow: /
Disallow: /uitkomst/
Disallow: /monitoring/
Disallow: /rapport/
Disallow: /admin/

User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: OAI-SearchBot
Allow: /

Sitemap: https://www.krillo.nl/sitemap.xml
"""
    return Response(inhoud, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    # Een sitemap zonder lastmod dwingt een zoekmachine om elke pagina steeds
    # opnieuw op te halen om te zien of er iets veranderd is. Met een datum
    # erbij weet hij meteen wat nieuw is, en dat is precies wat je wil op het
    # moment dat je artikelen toevoegt.
    nieuwste = max([a["datum"] for a in artikelen.ARTIKELEN] or ["2026-08-01"])
    # /uitkomst/<token> staat hier BEWUST niet in. Die pagina's gaan over één
    # winkel met naam en toenaam en horen niet in Google.
    vast = ["/", "/artikelen", "/zo-meten-we", "/veelgestelde-vragen",
            "/onderzoek", "/over-ons", "/voorwaarden", "/privacybeleid", "/herroepen"]
    regels = [(p, nieuwste) for p in vast]
    regels += [(f"/artikelen/{a['slug']}", a["datum"]) for a in artikelen.ARTIKELEN]
    urls = "".join(
        f"<url><loc>https://www.krillo.nl{p}</loc>"
        f"<lastmod>{datum}</lastmod><changefreq>weekly</changefreq></url>"
        for p, datum in regels
    )
    inhoud = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(inhoud, mimetype="application/xml")


@app.route("/llms.txt")
def llms_txt():
    inhoud = """# Krillo

> Krillo laat eigenaren van Nederlandse en Belgische webshops zien of AI-assistenten
> zoals ChatGPT, Gemini en Perplexity hun webshop vinden en aanbevelen, en lost de
> gevonden verbeterpunten op.

## Wat Krillo doet
Krillo scant een webshop op dertien punten, verdeeld over toegang, leesbaarheid,
structuur en inhoud. De gratis scan toont de score en alle bevindingen. Daarnaast is
er een gratis zichtbaarheidstest: die stelt vijf koopvragen aan ChatGPT en Gemini,
zoals een koper ze zou stellen, en laat zien bij hoeveel vragen de webshop genoemd
wordt en welke andere winkels er in het antwoord staan. De betaalde
audit schrijft voor elk verbeterpunt een oplossing uit: herschreven teksten voor de
producten van die specifieke webshop, en technische code die de eigenaar kan plakken.
Wil de eigenaar het niet zelf doen, dan voert Krillo de verbeteringen zelf uit in zijn
webshop, met achteraf een overzicht van elke wijziging en de oude tekst erbij zodat
alles terug te draaien is. Het monitoring-abonnement meet elke week opnieuw.

## Voor wie
Eigenaren van webshops in Nederland en Belgie, zonder marketingbureau en zonder
technische kennis. Ze kunnen het zelf doen met de uitgeschreven oplossingen, of het
door Krillo laten uitvoeren.

## Prijzen
- Gratis scan: 0 euro, geen account nodig
- Volledige audit: 79 euro eenmalig, alle oplossingen uitgeschreven om zelf te doen
- Wij doen het: 149 euro eenmalig, Krillo voert de verbeteringen uit in de webshop
- Monitoring: 39 euro per maand, maandelijks opzegbaar

## Belangrijke pagina's
- Homepage, gratis scan en gratis zichtbaarheidstest: https://www.krillo.nl/
- Artikelen over AI-zichtbaarheid: https://www.krillo.nl/artikelen
- Hoe we meten: https://www.krillo.nl/zo-meten-we
- Veelgestelde vragen: https://www.krillo.nl/veelgestelde-vragen
- Over Krillo en contact: https://www.krillo.nl/over-ons
- Onderzoek naar AI-antwoorden over Nederlandse webshops: https://www.krillo.nl/onderzoek

## Artikelen
""" + "\n".join(
        f"- {a['titel']}: https://www.krillo.nl/artikelen/{a['slug']}"
        for a in artikelen.ARTIKELEN
    ) + """

## Contact
hallo@krillo.nl
"""
    return Response(inhoud, mimetype="text/plain")


def _herkomst():
    """Waar de bezoeker vandaan komt, zonder iets over de persoon vast te leggen.

    We kijken naar een campagnelabel in de link (utm_source) en anders naar het
    domein van de vorige pagina. Geen IP-adres en geen cookie: we willen weten
    of LinkedIn of een forum bezoekers oplevert, niet wie die bezoekers zijn."""
    bron = (request.args.get("utm_source") or "").strip()[:60]
    if bron:
        return bron.lower()

    verwijzer = request.referrer or ""
    if not verwijzer:
        return None
    try:
        from urllib.parse import urlparse
        domein = (urlparse(verwijzer).netloc or "").lower().replace("www.", "")
    except Exception:
        return None
    # Onszelf niet meetellen. Niet alleen krillo.nl hardcoderen: op een
    # testomgeving, een preview-adres of met www ervoor zou de site zichzelf
    # anders als bron opschrijven, en dan staat "krillo.nl" bovenaan de lijst
    # met plekken die bezoekers opleveren.
    eigen = (request.host or "").lower().replace("www.", "").split(":")[0]
    if not domein or "krillo.nl" in domein or (eigen and domein == eigen):
        return None
    return domein[:60]


def _mailtaal(webshop_url):
    """"nl" of "en" voor deze winkel.

    Een winkel in Texas hoort geen Nederlandse weekmail te krijgen. De taal
    staat in het winkelprofiel; is die onbekend, dan wordt het Nederlands, want
    daar zit bijna elke klant."""
    if not webshop_url:
        return "nl"
    try:
        return "nl" if _markt_van(webshop_url)["is_nederlands"] else "en"
    except Exception as e:
        print(f"Taal bepalen mislukt voor {webshop_url}: {e}")
        return "nl"


# De sleutel waarmee Flask het inlogkoekje ondertekent. Zonder deze regel kan
# Flask geen sessie bewaren en werkt het inlogscherm niet.
#
# Terugval op ADMIN_KEY als SESSIE_SLEUTEL niet gezet is: dan werkt het inloggen
# meteen, zonder dat er eerst iets in Render bij moet. Een eigen SESSIE_SLEUTEL
# is netter, want dan hoeft de beheersleutel niet ook nog koekjes te tekenen.
app.secret_key = (os.environ.get("SESSIE_SLEUTEL")
                  or os.environ.get("ADMIN_KEY") or "krillo-zonder-sleutel")

# Hoe lang je ingelogd blijft op de beheerpagina's.
INLOG_DAGEN = int(os.environ.get("INLOG_DAGEN", "14"))
app.permanent_session_lifetime = timedelta(days=INLOG_DAGEN)


def _mag_bij_beheer():
    """Of deze bezoeker bij de beheerpagina's mag.

    Twee manieren, en dat is met opzet:

    1. Ingelogd via /admin/inloggen. Dan staat er niets in het webadres.
    2. Met ?key= in het adres, zoals het altijd werkte. Die manier blijft
       bestaan, want de cron-taken gebruiken hem en jouw bladwijzers ook.

    Wat er wel verandert: komt iemand binnen met ?key=, dan onthouden wij dat in
    een koekje en sturen wij hem door naar hetzelfde adres ZONDER de sleutel.
    Daarna staat de sleutel niet meer in de adresbalk, niet in je geschiedenis,
    niet in een schermafdruk en niet in de logboeken van Render. Dat is het hele
    punt: de sleutel bestaat nog, hij ligt alleen niet meer overal rond.

    Geeft (mag, doorsturen_naar) terug."""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key:
        return False, None
    if session.get("beheer") is True:
        return True, None
    if _sleutel_klopt(request.args.get("key"), admin_key):
        session.permanent = True
        session["beheer"] = True
        # Alleen doorsturen bij een gewoon bezoek. Een POST doorsturen zou het
        # formulier weggooien, en een cron-taak heeft geen adresbalk.
        if request.method == "GET":
            zonder = {k: v for k, v in request.args.items() if k != "key"}
            return True, url_for(request.endpoint, **{**(request.view_args or {}),
                                                      **zonder})
        return True, None
    return False, None


def _sleutel_klopt(gegeven, verwacht):
    """Vergelijkt een sleutel zonder dat de duur iets verraadt.

    Met == stopt de vergelijking bij het eerste verschillende teken, en dan
    kan iemand aan de reactietijd zien hoeveel tekens hij goed had. Dat is
    theoretisch over het internet, maar het kost een regel om het goed te doen
    en shopify_app.py doet het elders al zo."""
    if not gegeven or not verwacht:
        return False
    return hmac.compare_digest(str(gegeven), str(verwacht))


def _schoon_bron(waarde):
    """Maakt een bronlabel schoon voordat het de database of Mollie in gaat.

    Het label komt uit de browser van de bezoeker en is dus door iedereen te
    verzinnen. Het wordt nergens uitgevoerd of als HTML getoond, maar een label
    van tienduizend tekens of met regeleinden erin maakt de beheerpagina en de
    metadata van Mollie onleesbaar. Daarom kort, kleine letters, en alleen
    tekens die in een campagnenaam thuishoren."""
    tekst = (waarde or "")
    if not isinstance(tekst, str):
        return None
    tekst = re.sub(r"[^a-z0-9._\-]", "", tekst.strip().lower())[:60]
    return tekst or None


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Vul een website-URL in."}), 400

    herkomst = data.get("herkomst") or _herkomst()
    result = run_scan(url)
    if "error" in result:
        db.bewaar_gratis_scan(url, gelukt=False, foutsoort=result["error"][:200], herkomst=herkomst)
        return jsonify(result), 400

    db.bewaar_gratis_scan(result["url"], score=result.get("score"), herkomst=herkomst)

    previous = db.get_previous_score(result["url"])
    if previous:
        result["vorige_score"] = previous["score"]
        result["verschil"] = result["score"] - previous["score"]

    return jsonify(result)


_EMAIL_VORM = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def _draai_zichtbaarheidstest(test_id, webshop_url, email, base_url):
    """Draait de gratis test en mailt de uitslag. Op de achtergrond, want vijf
    vragen aan de modellen duurt een minuut of twee."""
    try:
        resultaat = zichtbaarheid.draai(test_id, webshop_url)
        if not resultaat:
            return
        try:
            emailing.send_zichtbaarheidstest(
                email, webshop_url, resultaat,
                zichtbaarheid.samenvattingszin(resultaat, webshop_url),
                base_url,
            )
        except Exception as e:
            # De uitslag staat al in de database en op de pagina. Een mail die
            # niet aankomt mag de test niet als mislukt laten gelden.
            print(f"Uitslag mailen mislukt voor {webshop_url}: {e}")
    except Exception as e:
        print(f"Zichtbaarheidstest mislukt voor {webshop_url}: {e}")


def _draai_voorproef(test_id, webshop_url):
    """De korte meting die meteen na de gratis scan draait, zonder e-mailadres."""
    try:
        # Zonder bronanalyse. De voorproef draait bij ELKE gratis scan, ook bij
        # iemand die alleen even kwam kijken. Daar een zoekmachine en een reeks
        # paginabezoeken achteraan sturen maakt de goedkoopste stap van de
        # trechter ineens de duurste. De bronanalyse zit in de volledige gratis
        # test, waar iemand een e-mailadres voor achterlaat.
        zichtbaarheid.draai(test_id, webshop_url,
                            aantal_vragen=zichtbaarheid.VOORPROEF_VRAGEN,
                            max_aanbieders=1, bronnen_erbij=False)
    except Exception as e:
        print(f"Voorproef mislukt voor {webshop_url}: {e}")


@app.route("/api/voorproef", methods=["POST"])
def api_voorproef():
    """Drie koopvragen, meteen na de gratis scan, zonder dat er iets gevraagd wordt.

    Dit bestaat omdat de gratis scan zonder dit een SEO-tool lijkt. Het cijfer
    over dertien technische punten is het minst bijzondere wat Krillo doet, en
    dat stond bovenaan terwijl het enige onderscheidende eronder achter een
    formulier zat. Wie niet doorklikte, en dat is bijna iedereen, oordeelde over
    het verkeerde product.

    Geen e-mailadres, dus ook geen mail. De rem is dezelfde als bij de volledige
    test, en dezelfde winkel krijgt binnen dertig dagen de bewaarde uitslag."""
    if not zichtbaarheid.VOORPROEF_AAN:
        return jsonify({"status": "uit"}), 200

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Geen webshop opgegeven."}), 400
    url = scan_engine.normalize_url(url)

    eerder = db.laatste_geslaagde_test(url, zichtbaarheid.HERGEBRUIK_DAGEN)
    if eerder and eerder.get("resultaat"):
        return jsonify({"status": "klaar", "resultaat": eerder["resultaat"],
                        "zin": zichtbaarheid.samenvattingszin(eerder["resultaat"], url)})

    # Loopt er al een meting voor deze winkel, dan geen tweede starten.
    # Dit is een publieke pagina zonder wachtwoord: twee keer klikken, of een
    # dubbelklik, startte anders twee volledige metingen bij de modellen. Dat
    # kost twee keer geld voor precies dezelfde uitslag.
    if db.loopt_er_al_een_test(url):
        return jsonify({"status": "uit"}), 200

    mag, _ = zichtbaarheid.mag_starten()
    if not mag:
        # Bewust geen foutmelding aan de bezoeker. Hij vroeg hier niet om, hij
        # deed gewoon een scan. Dan hoort hij geen melding te krijgen dat er
        # iets niet kon.
        return jsonify({"status": "uit"}), 200

    # Zonder e-mailadres, dus met een vaste plaatsaanduiding. Dat is geen
    # persoonsgegeven en er gaat nooit mail heen.
    aanvraag = db.start_zichtbaarheidstest(url, "voorproef@krillo.nl", False, _herkomst(),
                                           soort="voorproef")
    if not aanvraag:
        return jsonify({"status": "uit"}), 200

    threading.Thread(target=_draai_voorproef, args=(aanvraag["id"], url), daemon=True).start()
    return jsonify({"kenmerk": aanvraag["kenmerk"], "status": "bezig"})


@app.route("/api/zichtbaarheidstest", methods=["POST"])
def api_zichtbaarheidstest():
    """Fase 5 punt 12. Start de gratis zichtbaarheidstest voor een webshop.

    Vraagt om een e-mailadres, en dat is met opzet. Het kost echt geld per test,
    dus we doen hem alleen voor iemand die er om vraagt. En het levert een lijst
    op van mensen die zelf om contact gevraagd hebben, wat het enige nette
    fundament is onder alles wat we ze daarna sturen."""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    email = (data.get("email") or "").strip().lower()
    nieuwsbrief = bool(data.get("nieuwsbrief"))

    if not url:
        return jsonify({"error": "Vul eerst je webshop in."}), 400
    if not email or not _EMAIL_VORM.match(email) or len(email) > 190:
        return jsonify({"error": "Vul een geldig e-mailadres in."}), 400
    if not data.get("voorwaarden_akkoord"):
        return jsonify({"error": "Ga akkoord met het privacybeleid."}), 400

    url = scan_engine.normalize_url(url)
    herkomst = data.get("herkomst") or _herkomst()

    # Is deze winkel kortgeleden al gemeten, dan hergebruiken we die uitslag.
    # Scheelt geld, maar belangrijker: wie zijn uitslag doorstuurt hoort niet
    # drie verschillende cijfers te zien door de ruis in AI-antwoorden.
    # Met soort="volledig": een voorproef van drie vragen mag nooit doorgaan
    # voor de volledige test van vijf. Wie zijn adres achterlaat hoort de test
    # te krijgen waarvoor hij tekende, niet de korte versie die hij al zag.
    eerder = db.laatste_geslaagde_test(url, zichtbaarheid.HERGEBRUIK_DAGEN, soort="volledig")
    if eerder and eerder.get("resultaat"):
        # Als hergebruik wegschrijven, want deze test kost niets. Telden we hem
        # mee in de dagteller, dan zou een uitslag die tien keer gedeeld wordt
        # de gratis test voor iedereen dichtzetten zonder dat er een cent
        # uitgegeven is.
        aanvraag = db.start_zichtbaarheidstest(url, email, nieuwsbrief, herkomst,
                                               hergebruikt=True)
        if aanvraag:
            db.zet_zichtbaarheidstest(aanvraag["id"], "klaar", resultaat=eerder["resultaat"])
        # base_url en de zin hier bepalen en niet in de thread. In de thread is
        # er geen verzoek meer, en get_base_url() leest het verzoek. Deed je
        # dat daar, dan liep de mail elke keer stuk zonder dat iemand het merkt:
        # de uitslag staat immers gewoon op de pagina.
        basis = get_base_url()
        zin = zichtbaarheid.samenvattingszin(eerder["resultaat"], url)
        resultaat = eerder["resultaat"]
        threading.Thread(
            target=lambda: emailing.send_zichtbaarheidstest(email, url, resultaat, zin, basis),
            daemon=True).start()
        return jsonify({"kenmerk": (aanvraag or {}).get("kenmerk"), "status": "klaar",
                        "resultaat": resultaat, "zin": zin})

    # Loopt er al een meting voor deze winkel, dan geen tweede starten. Anders
    # betaal je twee keer voor dezelfde uitslag. Deze bezoeker vroeg er zelf om
    # en wacht op een antwoord, dus die krijgt wel te horen wat er aan de hand
    # is, in plaats van een stille afwijzing zoals bij de voorproef.
    if db.loopt_er_al_een_test(url):
        return jsonify({"error": "Er loopt al een meting voor deze webshop. "
                                 "Die is over een paar minuten klaar."}), 409

    mag, reden = zichtbaarheid.mag_starten()
    if not mag:
        return jsonify({"error": reden}), 429

    aanvraag = db.start_zichtbaarheidstest(url, email, nieuwsbrief, herkomst)
    if not aanvraag:
        return jsonify({"error": "Het lukte even niet. Probeer het zo nog eens."}), 500

    threading.Thread(target=_draai_zichtbaarheidstest,
                     args=(aanvraag["id"], url, email, get_base_url()), daemon=True).start()
    return jsonify({"kenmerk": aanvraag["kenmerk"], "status": "wachtrij"})


@app.route("/api/zichtbaarheidstest/<kenmerk>")
def api_zichtbaarheidstest_status(kenmerk):
    """De pagina vraagt hier om de tien seconden of de uitslag er al is.

    Op kenmerk en niet op rijnummer. Met een rijnummer kon iemand die zelf een
    test deed simpelweg naar beneden tellen en van elke andere bezoeker de
    winkel en de volledige uitslag opvragen.

    Geeft ook geen e-mailadres terug, ook niet met het juiste kenmerk."""
    test = db.get_zichtbaarheidstest_op_kenmerk(kenmerk)
    if not test:
        return jsonify({"error": "Onbekende test."}), 404

    antwoord = {"status": test.get("status") or "wachtrij",
                "webshop_url": test.get("webshop_url")}
    if test.get("status") == "klaar" and test.get("resultaat"):
        antwoord["resultaat"] = test["resultaat"]
        antwoord["zin"] = zichtbaarheid.samenvattingszin(test["resultaat"],
                                                         test.get("webshop_url"))
    elif test.get("status") == "mislukt":
        antwoord["fout"] = ("De test kon niet afgemaakt worden. Dat ligt meestal aan de site "
                            "die ons niet binnenliet, of aan een AI-model dat even dichtzat.")
    return jsonify(antwoord)


@app.route("/api/checkout/audit", methods=["POST"])
def checkout_audit():
    data = request.get_json(silent=True) or {}
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    email = (data.get("email") or "").strip()
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    direct = bool(data.get("directe_uitvoering_akkoord"))
    if not webshop_url or not email:
        return jsonify({"error": "Vul een webshop-URL en e-mailadres in."}), 400
    # De vorm van het adres controleren. Stond hier niet, alleen bij de gratis
    # test. Wie zich vertypt betaalde dus 79 euro, Brevo weigerde stilletjes, en
    # niemand merkte iets: niet de klant, niet wij.
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "Dat e-mailadres klopt niet. Controleer het even, "
                                 "want hier sturen wij alles naartoe."}), 400
    if not voorwaarden:
        return jsonify({"error": "Ga akkoord met de voorwaarden en het privacybeleid."}), 400
    if not direct:
        return jsonify({"error": "Geef aan dat we direct mogen beginnen."}), 400

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    result = payments.create_audit_payment(get_base_url(), webshop_url, email,
                                           bedrijfsnaam, bron=bron)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "audit", voorwaarden, direct)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/checkout/uitvoering", methods=["POST"])
def checkout_uitvoering():
    """Wij voeren het uit in de webshop van de klant.

    Zelfde toestemmingen als bij de audit, want het is net zo goed een dienst
    die meteen begint: zodra wij toegang hebben en aan het werk gaan, kan de
    klant zijn herroepingsrecht niet meer inroepen voor het deel dat af is.

    Het platform komt uit een eerdere scan als we die hebben. Weten we het niet,
    dan gaat er algemene uitleg mee in plaats van een gok."""
    data = request.get_json(silent=True) or {}
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    email = (data.get("email") or "").strip()
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    direct = bool(data.get("directe_uitvoering_akkoord"))
    if not webshop_url or not email:
        return jsonify({"error": "Vul een webshop-URL en e-mailadres in."}), 400
    # De vorm van het adres controleren. Stond hier niet, alleen bij de gratis
    # test. Wie zich vertypt betaalde dus 79 euro, Brevo weigerde stilletjes, en
    # niemand merkte iets: niet de klant, niet wij.
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "Dat e-mailadres klopt niet. Controleer het even, "
                                 "want hier sturen wij alles naartoe."}), 400
    if not voorwaarden:
        return jsonify({"error": "Ga akkoord met de voorwaarden en het privacybeleid."}), 400
    if not direct:
        return jsonify({"error": "Geef aan dat we direct mogen beginnen."}), 400

    platform = None
    try:
        platform = (db.get_winkelprofiel(webshop_url) or {}).get("platform")
    except Exception as e:
        print(f"Platform ophalen mislukt bij de kassa voor {webshop_url}: {e}")

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    result = payments.create_uitvoering_payment(get_base_url(), webshop_url, email,
                                                bedrijfsnaam, bron=bron, platform=platform)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "uitvoering",
                                voorwaarden, direct)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/checkout/monitoring", methods=["POST"])
def checkout_monitoring():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    if not email or not webshop_url:
        return jsonify({"error": "Vul een e-mailadres en webshop-URL in."}), 400
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "Dat e-mailadres klopt niet. Controleer het even, "
                                 "want hier sturen wij alles naartoe."}), 400
    if not voorwaarden:
        return jsonify({"error": "Ga akkoord met de voorwaarden en het privacybeleid."}), 400

    # Loopt er al een abonnement op deze winkel, dan houden wij het hier tegen.
    # Zonder deze controle maakt elke nieuwe aanmelding een tweede abonnement
    # bij Mollie met dezelfde winkel erin, en dan wordt er elke maand twee keer
    # geïncasseerd. Erger nog: het opzeggen zegt maar een van de twee op, dus
    # hij krijgt een bevestiging terwijl er gewoon geld af blijft gaan.
    try:
        if payments.zoek_abonnement(webshop_url):
            return jsonify({
                "error": "Op deze webshop loopt al een abonnement. Kijk in je mail naar "
                         "je eigen pagina, of mail hallo@krillo.nl als je die kwijt bent."
            }), 400
    except Exception as e:
        # Kunnen wij het niet nakijken, dan gaan wij door. Iemand tegenhouden
        # die wil betalen omdat onze controle hapert is erger dan het risico.
        print(f"Bestaand abonnement nakijken mislukt voor {webshop_url}: {e}")

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    result = payments.create_monitoring_signup(get_base_url(), email, webshop_url,
                                               bedrijfsnaam, bron=bron)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "monitoring", voorwaarden, False)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


def _meld_aan_beheer(kop, bericht):
    """Stuurt een waarschuwing naar het eigen adres.

    Alleen voor dingen die stil misgaan en die je moet weten voordat een klant
    het merkt. Zet BEHEERDER_EMAIL in Render; staat hij er niet, dan blijft het
    bij de logs."""
    print(f"BEHEERMELDING: {kop} | {bericht}")
    # BEHEERDER_EMAIL eerst, want dat is de naam die de rest van de code en de
    # README gebruiken. Stond hier alleen BEHEER_EMAIL, en dan kwam geen enkele
    # noodmelding aan bij iemand die netjes BEHEERDER_EMAIL had ingevuld. Precies
    # de drie meldingen die ertoe doen ("betaald maar niet geleverd",
    # "abonnement niet aangemaakt") verdwenen daardoor in de logs.
    adres = (os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL")
             or os.environ.get("SMTP_REPLY_TO") or "").strip()
    if not adres:
        return False
    try:
        return emailing.send_email(
            adres, f"Krillo: {kop}",
            f"<p style='font-family:Arial,sans-serif;font-size:15px;'>{bericht}</p>")
    except Exception as e:
        print(f"Beheermelding versturen mislukt: {e}")
        return False


def _meld_nieuwe_klant(soort, webshop_url, email, bedrag, extra=None):
    """Een bericht naar je eigen adres zodra er iemand betaald heeft.

    Dit ontbrak, en dat is raar als je erover nadenkt: er ging wel een mail uit
    als er iets MISGING, maar niet als het goed ging. De belangrijkste
    gebeurtenis van het hele bedrijf, de eerste betalende klant, kwam dus nergens
    binnen behalve in de mail van Mollie en op een beheerpagina die je zelf moet
    openen.

    Bij "wij doen het" is dat niet alleen jammer maar ook riskant: daar moet jij
    binnen een paar dagen echt aan de slag, en de klant zit te wachten. Daarom
    staat in dit bericht meteen waar je heen moet klikken."""
    basis = get_base_url()
    sleutel = (os.environ.get("ADMIN_KEY") or "").strip()
    achter = f"?key={quote(sleutel)}&url={quote(webshop_url)}" if sleutel else ""
    regels = [
        f"<strong>{soort}</strong> voor {webshop_url}",
        f"Bedrag: {bedrag}",
        f"E-mailadres: {email}",
    ]
    if extra:
        regels.append(extra)
    if basis:
        regels.append(f'<a href="{basis}/admin/werkbriefje{achter}">Naar het werkbriefje</a>')
        regels.append(f'<a href="{basis}/admin/bestellingen{("?key=" + quote(sleutel)) if sleutel else ""}">Naar de bestellingen</a>')
    return _meld_aan_beheer(f"Nieuwe klant: {soort}", "<br>".join(regels))


def _scan_met_herkansing(webshop_url, pogingen=3):
    """Scant, en probeert het nog twee keer als het misgaat.

    De meeste mislukkingen zijn tijdelijk: een trage server, een robotcheck die
    even aanslaat. Meteen opgeven betekent dat iemand die net betaald heeft
    niets krijgt vanwege een hapering van vijf seconden."""
    laatste = {"error": "onbekend"}
    for poging in range(max(1, pogingen)):
        if poging:
            time.sleep(4 * poging)
        try:
            laatste = run_scan(webshop_url)
        except Exception as e:
            laatste = {"error": f"{type(e).__name__}: {e}"[:200]}
        if "error" not in laatste:
            if poging:
                print(f"Scan van {webshop_url} lukte bij poging {poging + 1}.")
            return laatste
        print(f"Scan van {webshop_url} mislukt (poging {poging + 1}): {laatste['error']}")
    return laatste


def _uitvoering_voorbereiden(payment_id, webshop_url, email, klant_token, base_url):
    """Zet het werk klaar voor een klant die "wij doen het" gekocht heeft.

    Wat de prijskaart belooft is "alles uit de volledige audit zit erbij". Dat
    werd niet gedaan: de uitvoering-tak zette de opdracht op de werklijst en
    vroeg om toegang, en verder gebeurde er niets. Geen scan, geen rapport, geen
    meting. Daardoor was de klantpagina van iemand die 149 euro betaald had leeg,
    en stond er op het werkbriefje geen enkele taak.

    Draait op de achtergrond en mag rustig een paar minuten duren: de klant moet
    eerst toch zelf toegang regelen voordat er iets kan gebeuren."""
    try:
        scan_result = _scan_met_herkansing(webshop_url)
        if "error" in scan_result:
            _meld_aan_beheer(
                "Uitvoering: scan mislukt",
                f"{email} betaalde 149 euro voor {webshop_url}, maar de site is niet te "
                f"scannen: {scan_result.get('error')}. De opdracht staat wel op de "
                f"werklijst. Er is dus GEEN werkbriefje. Kijk er met de hand naar.")
            return

        db.zet_platform(webshop_url, scan_result.get("platform"))
        db.save_report("monitoring", webshop_url, email, scan_result.get("score", 0),
                       scan_result.get("checks", []), None, None, klant_token)

        # Dezelfde keten als bij een abonnee, want het werkbriefje leunt op de
        # meting: zonder vermeldingen is er geen actieplan, en zonder actieplan
        # weet jij niet wat je in die winkel moet doen.
        _meet_en_beoordeel(webshop_url, None, klant_token, base_url)
    except Exception as e:
        print(f"Uitvoering voorbereiden mislukt voor {webshop_url}: {e}")
        _meld_aan_beheer(
            "Uitvoering: voorbereiding mislukt",
            f"Het klaarzetten van het werk voor {webshop_url} ({email}, 149 euro) ging "
            f"mis: {type(e).__name__}: {e}. De opdracht staat op de werklijst maar er "
            f"is geen werkbriefje.")


def _levering_mislukt(payment_id, webshop_url, email, soort, reden):
    """Er is betaald maar wij konden niet leveren.

    Twee dingen gebeuren hier, en allebei zijn ze nodig. De claim gaat terug,
    zodat een volgende melding van Mollie het opnieuw probeert. En er gaat een
    bericht naar het eigen adres, want anders staat het alleen in de logs van
    Render en kijkt niemand daar."""
    db.ontclaim_payment(payment_id)
    _meld_aan_beheer(
        "Betaald maar niet geleverd",
        f"Betaling {payment_id} voor {webshop_url} ({soort}, {email}) is binnen, maar "
        f"de scan lukte niet: {reden}. De betaling staat weer open, dus een volgende "
        f"melding van Mollie probeert het opnieuw. Lukt dat ook niet, doe het dan met "
        f"de hand of geef het geld terug.")


def _verwerk_betaling(payment_id, base_url):
    """Doet het echte werk na een geslaagde betaling: scannen, AI-tekst maken,
    rapport opslaan en e-mail versturen. Draait op de achtergrond zodat Mollie
    niet hoeft te wachten en de melding niet opnieuw stuurt."""
    try:
        # Eerst kijken of er echt betaald is. Zolang dat niet zo is doen we
        # niets en claimen we niets, zodat de melding die later WEL "paid"
        # zegt gewoon verwerkt wordt.
        status = payments.get_payment_status(payment_id)
        if not (status and status["is_paid"]):
            return

        # Pas nu vastleggen dat wij deze betaling oppakken. Komt Mollie later
        # nog een keer met dezelfde betaling, dan stopt het hier.
        geclaimd = db.claim_payment(payment_id)
        if geclaimd is None:
            # Wij KONDEN niet claimen. Dat is iets anders dan "al verwerkt" en
            # het hoort een belletje te geven, want dit is het pad waarin iemand
            # wel betaalt en geen klantrecord krijgt.
            _meld_aan_beheer(
                "Betaling niet geclaimd",
                f"Betaling {payment_id} is binnen, maar wij konden niet vastleggen dat "
                f"wij hem oppakken (database niet bereikbaar). Er is NIETS geleverd. "
                f"Controleer deze betaling met de hand in Mollie.")
            return
        if not geclaimd:
            print(f"Betaling {payment_id} was al verwerkt, overgeslagen.")
            return

        # Tweede blokkade: is er voor deze betaling al een rapport gemaakt?
        if db.report_bestaat_al(payment_id):
            print(f"Er bestaat al een rapport voor betaling {payment_id}, niets verstuurd.")
            return

        # LET OP: hier stond een controle die betalingen ouder dan drie uur
        # negeerde, gemeten vanaf het AANMAKEN van de betaling. Dat brak elke
        # overboeking: die is per definitie een dag of langer onderweg, en bij
        # aankomst werd hij als "late herhaling" weggegooid. Geld ontvangen,
        # niets geleverd. Dubbele verwerking wordt al voorkomen door de claim
        # hierboven en door report_bestaat_al, dus een leeftijdsgrens voegde
        # niets toe.

        metadata = status.get("metadata") or {}
        payment_type = metadata.get("type")
        webshop_url = metadata.get("webshop_url")
        email = metadata.get("email")
        bedrijfsnaam = metadata.get("bedrijfsnaam")
        # Waar deze klant vandaan kwam. Komt ongewijzigd terug uit de metadata
        # van Mollie, ook bij een overboeking die een dag onderweg was. Bij
        # betalingen van voor deze wijziging staat er niets, en dan blijft het
        # veld leeg in plaats van dat we iets gaan raden.
        bron = _schoon_bron(metadata.get("bron"))

        # Eerst de betaalbevestiging met factuur, die hoort er meteen te zijn.
        # De audit zelf duurt langer omdat er gescand en geschreven moet worden.
        if email:
            if payment_type == "audit":
                omschrijving = f"Krillo volledige audit voor {webshop_url}"
            elif payment_type == "uitvoering":
                omschrijving = f"Krillo voert de verbeteringen uit voor {webshop_url}"
            else:
                omschrijving = f"Krillo monitoring, eerste maand, voor {webshop_url}"
            bedrag = status.get("bedrag")
            if bedrag is not None:
                factuurnummer = db.maak_factuur(payment_id, email, bedrijfsnaam,
                                                omschrijving, bedrag, bron=bron)
                if factuurnummer and factuurnummer.get("nieuw"):
                    # ALLEEN bij een nieuwe factuur mailen. Bij een herhaling van
                    # Mollie na een mislukte levering kwam dezelfde factuur er
                    # anders nog een keer uit, voor iets wat de klant nog steeds
                    # niet gekregen had.
                    if not emailing.send_factuur_email(
                            email, factuurnummer["factuurnummer"], omschrijving,
                            bedrag, bedrijfsnaam):
                        _meld_aan_beheer(
                            "Factuur niet verstuurd",
                            f"De factuur voor betaling {payment_id} ({email}) kon niet "
                            f"verstuurd worden. De factuur staat wel in de database.")

        if payment_type == "uitvoering" and webshop_url and email:
            # Deze opdracht wordt door een mens uitgevoerd, dus het enige wat
            # hier gebeurt is: op de werklijst zetten en om toegang vragen.
            # Eerst de werklijst en dan pas de mail: gaat de mail mis, dan staat
            # de opdracht er tenminste, en zie je op de beheerpagina dat er
            # iemand wacht. Andersom zou een klant gevraagd worden om toegang
            # voor een opdracht die nergens staat.
            platform = metadata.get("platform")
            if not db.start_uitvoering(payment_id, webshop_url, email, platform):
                print(f"LET OP: uitvoering voor {webshop_url} staat NIET op de werklijst.")
            # Meteen een bericht naar het eigen adres. Hier moet een mens aan de
            # slag, dus dit is het enige product waarbij stilte betekent dat er
            # niets gebeurt.
            _meld_nieuwe_klant("Wij doen het", webshop_url, email, "149 euro eenmalig",
                               extra=(f"Platform: {platform}" if platform else
                                      "Platform onbekend, kijk zelf even waar hij op draait."))
            klant_token = db.get_or_create_klant(webshop_url, email)
            if not klant_token:
                # Deze webshop hoort al bij een ander e-mailadres. Wij geven die
                # pagina niet aan iemand anders, ook niet als hij net betaald
                # heeft. Dat kan een tikfout zijn of iemand die de URL van een
                # bekende winkel invulde; beide moeten met de hand bekeken.
                _meld_aan_beheer(
                    "Bestelling op een webshop van een andere klant",
                    f"{email} bestelde een uitvoering voor {webshop_url}, maar die "
                    f"webshop hoort al bij een ander adres. De klantpagina is NIET "
                    f"gedeeld. Kijk of dit klopt en handel het met de hand af.")
            monitoring_url = f"{base_url}/monitoring/{klant_token}" if klant_token else None
            if not emailing.send_uitvoering_welkom(email, webshop_url, platform,
                                                   monitoring_url):
                _meld_aan_beheer(
                    "Toegangsmail niet verstuurd",
                    f"{email} betaalde 149 euro voor {webshop_url}, maar de mail met de "
                    f"vraag om toegang is NIET verstuurd. Zonder die mail kan hij niets "
                    f"doen en gebeurt er niets. Neem contact op.")

            # En dan het werk waar hij voor betaald heeft klaarzetten.
            #
            # Dit ontbrak volledig, en het is precies wat de prijskaart belooft:
            # "Alles uit de volledige audit zit erbij". Er werd niet gescand,
            # geen rapport bewaard en niet gemeten. Gevolg: de klantpagina van
            # iemand die 149 euro betaalde was leeg, en JIJ had geen werkbriefje,
            # dus je wist niet wat je in zijn winkel moest doen.
            #
            # Op de achtergrond, want dit duurt minuten en de klant hoeft er niet
            # op te wachten: hij moet eerst toch toegang regelen. Mislukt het,
            # dan krijg jij bericht en staat de opdracht nog steeds op je
            # werklijst.
            threading.Thread(
                target=_uitvoering_voorbereiden,
                args=(payment_id, webshop_url, email, klant_token, base_url),
                daemon=True,
            ).start()

        elif payment_type == "audit" and webshop_url and email:
            scan_result = _scan_met_herkansing(webshop_url)
            if "error" in scan_result:
                # Betaald, maar wij kunnen niet leveren. De claim gaat terug, zodat
                # een volgende melding van Mollie het opnieuw probeert. Zou de claim
                # blijven staan, dan is het geld binnen, komt er nooit een rapport,
                # en merkt niemand het.
                _levering_mislukt(payment_id, webshop_url, email, "audit",
                                  scan_result.get("error"))
            else:
                # Op welk winkelplatform deze shop draait. Werd tot nu toe
                # alleen bij demo's opgeslagen, waardoor we het van betalende
                # klanten juist niet wisten. Zonder dit schrijft de tekst bij
                # "waar zet je dit neer" een route in Shopify voor iemand met
                # WooCommerce.
                db.zet_platform(webshop_url, scan_result.get("platform"))
                ai_fixes = ai_content.generate_ai_fixes(
                    webshop_url, scan_result.get("checks", []), scan_result.get("gevonden_paginas")
                )
                # NIET stil terugvallen op de gratis sjabloonteksten. Dat deed
                # hij wel, en dan betaalde iemand 79 euro voor precies de drie
                # voorbeelden die hij een minuut eerder gratis op de homepage
                # zag. Lukt het schrijven niet, dan is dat een fout die jij moet
                # weten, en dan gaat de mail niet uit: de betaling blijft open
                # staan zodat een volgende melding van Mollie het opnieuw
                # probeert.
                if ai_fixes is None:
                    _levering_mislukt(
                        payment_id, webshop_url, email, "audit",
                        "De uitgeschreven oplossingen konden niet gemaakt worden "
                        "(AI-sleutel ontbreekt of de kostenrem staat dicht). Er is "
                        "GEEN mail verstuurd, want dan had de klant de gratis "
                        "voorbeeldteksten gekregen voor 79 euro.")
                    return
                fixes = ai_fixes
                token = db.save_report("audit", webshop_url, email, scan_result.get("score", 0),
                                        scan_result.get("checks", []), fixes, payment_id)
                report_url = f"{base_url}/rapport/{token}" if token else None
                emailing.send_audit_email(email, webshop_url, scan_result, fixes, report_url,
                                          taal=_mailtaal(webshop_url))

        elif payment_type == "monitoring_first_payment":
            customer_id = metadata.get("customer_id")
            if customer_id:
                # Het antwoord WEL nakijken. Ging dit mis, dan heeft de klant de
                # eerste maand betaald maar wordt er daarna nooit meer
                # geincasseerd, en valt hij stilletjes uit de dienst.
                # EERST kijken of er al een abonnement loopt bij deze klant.
                # Zonder deze controle gebeurde dit: de levering mislukt, de
                # claim gaat terug, Mollie komt opnieuw langs, en er wordt een
                # TWEEDE doorlopend abonnement aangemaakt. Dan gaat er elke maand
                # twee keer 39 euro af, en opzeggen haalt er maar een van de
                # twee weg. De klant krijgt een bevestiging terwijl er geld af
                # blijft gaan.
                bestaand = None
                try:
                    bestaand = payments.zoek_abonnement(webshop_url)
                except Exception as e:
                    print(f"Nakijken op een bestaand abonnement mislukt: {e}")
                if bestaand:
                    print(f"Er loopt al een abonnement voor {webshop_url}, "
                          f"geen tweede aangemaakt.")
                    uitkomst = {"id": bestaand.get("subscription_id")}
                else:
                    uitkomst = payments.create_subscription(customer_id) or {}
                if uitkomst.get("error"):
                    print(f"LET OP: doorlopend abonnement NIET aangemaakt voor "
                          f"{webshop_url} ({customer_id}): {uitkomst['error']}")
                    _meld_aan_beheer(
                        "Abonnement niet aangemaakt",
                        f"{webshop_url} heeft de eerste maand betaald, maar het "
                        f"doorlopende abonnement is niet aangemaakt bij Mollie. "
                        f"Reden: {uitkomst['error']}. Maak het met de hand aan, "
                        f"anders wordt er nooit meer geincasseerd.")
            if webshop_url and email:
                scan_result = _scan_met_herkansing(webshop_url)
                if "error" in scan_result:
                    _levering_mislukt(payment_id, webshop_url, email, "monitoring",
                                      scan_result.get("error"))
                else:
                    db.zet_platform(webshop_url, scan_result.get("platform"))
                    klant_token = db.get_or_create_klant(webshop_url, email)
                    if not klant_token:
                        _meld_aan_beheer(
                            "Aanmelding op een webshop van een andere klant",
                            f"{email} meldde zich aan voor monitoring op {webshop_url}, "
                            f"maar die webshop hoort al bij een ander adres. De "
                            f"klantpagina is NIET gedeeld. Handel dit met de hand af.")
                    db.save_report("monitoring", webshop_url, email, scan_result.get("score", 0),
                                    scan_result.get("checks", []), None, payment_id, klant_token)
                    monitoring_url = f"{base_url}/monitoring/{klant_token}" if klant_token else None
                    emailing.send_monitoring_welcome_email(
                        email, webshop_url, scan_result, monitoring_url,
                        taal=_mailtaal(webshop_url))
                    _meld_nieuwe_klant(
                        "Monitoring", webshop_url, email, "39 euro per maand",
                        extra=(f'Zijn pagina: <a href="{monitoring_url}">{monitoring_url}</a>'
                               if monitoring_url else None))

                    # Meteen de eerste meting bij de AI-modellen, niet pas over
                    # een week. Een nieuwe klant die zeven dagen naar een lege
                    # pagina kijkt, zegt op voordat hij iets gezien heeft.
                    threading.Thread(
                        target=_meet_en_beoordeel,
                        args=(webshop_url, email, klant_token, base_url),
                        daemon=True,
                    ).start()
    except Exception as e:
        # Dit was het gevaarlijkste stukje van het hele bedrijf. De claim staat
        # op dat moment al vast, dus zonder wat hieronder gebeurt stopt elke
        # volgende melding van Mollie bij "was al verwerkt" en is de betaling
        # voorgoed onverwerkbaar. De klant heeft betaald, krijgt niets, en er
        # gaat nergens een belletje. Nu gaat de claim terug EN krijg jij bericht.
        print(f"Verwerken van betaling {payment_id} mislukt: {e}")
        try:
            db.ontclaim_payment(payment_id)
        except Exception as e2:
            print(f"Claim terugdraaien mislukt na fout: {e2}")
        _meld_aan_beheer(
            "Betaling niet verwerkt",
            f"Bij betaling {payment_id} ging er iets mis na de betaling: "
            f"{type(e).__name__}: {e}. De betaling staat weer open, dus een volgende "
            f"melding van Mollie probeert het opnieuw. Blijft het misgaan, doe het dan "
            f"met de hand of geef het geld terug.")


@app.route("/admin/inloggen", methods=["GET", "POST"])
def admin_inloggen():
    """Het inlogscherm voor de beheerpagina's.

    Waarom dit bestaat: de sleutel stond in het webadres van elke beheerpagina.
    Dat staat dus ook in je browsergeschiedenis, in de logboeken van Render, en
    op elke schermafdruk die je maakt. Er is er in augustus al een keer een in
    een schermafdruk in een chat beland. Met nul klanten is dat te overzien, met
    klanten niet meer.

    De sleutel blijft bestaan en ?key= blijft werken, want de cron-taken
    gebruiken hem. Wat er verandert: na een keer inloggen hoeft hij nergens meer
    in het adres, en kom je binnen met ?key=, dan onthouden wij het en halen wij
    hem meteen uit de adresbalk."""
    admin_key = os.environ.get("ADMIN_KEY")
    fout = None
    if request.method == "POST":
        if admin_key and _sleutel_klopt((request.form.get("sleutel") or "").strip(),
                                        admin_key):
            session.permanent = True
            session["beheer"] = True
            return redirect(request.args.get("verder") or "/admin/benadering")
        # Bewust geen verschil tussen "geen sleutel ingesteld" en "verkeerde
        # sleutel". Dat verschil vertelt een vreemde iets wat hij niet hoeft te
        # weten.
        fout = "Die sleutel klopt niet."
    return render_template("admin_inloggen.html", fout=fout)


@app.route("/admin/uitloggen")
def admin_uitloggen():
    session.pop("beheer", None)
    return redirect("/admin/inloggen")


@app.route("/webhooks/mollie", methods=["POST"])
def mollie_webhook():
    """Mollie roept dit aan zodra de status van een betaling verandert.
    We antwoorden meteen en doen het werk op de achtergrond, anders denkt
    Mollie dat het mislukt is en stuurt het bericht steeds opnieuw."""
    payment_id = request.form.get("id")
    if not payment_id:
        return "", 400

    # BEWUST GEEN CLAIM HIER. Die zit in _verwerk_betaling, en pas nadat
    # vaststaat dat er echt betaald is.
    #
    # Dit stond hier wel, en dat kostte klanten. Mollie meldt bij elke
    # statuswissel: open, pending, canceled, failed en paid. De melding bij
    # "pending" verbruikte de claim, en de melding bij "paid" werd daarna
    # weggegooid als "was al verwerkt". Wie met iDEAL of een overboeking
    # betaalde kreeg dus niets: geen factuur, geen rapport, geen mail, en geen
    # foutmelding waaruit je het had kunnen afleiden.
    base_url = get_base_url()
    threading.Thread(target=_verwerk_betaling, args=(payment_id, base_url), daemon=True).start()
    return "", 200


def meetdag(webshop_url):
    """Op welke dag van de week deze klant aan de beurt is. Maandag is 0.

    Elke klant krijgt een vaste dag, afgeleid van zijn eigen webadres. Dezelfde
    winkel komt dus altijd op dezelfde dag uit, ook na een herstart, en zonder
    dat we er iets voor hoeven op te slaan.

    Waarom dit nodig is: alle abonnees op een dag meten kost bij vijftig klanten
    meer dan de dagelijkse kostenrem toelaat. Die rem zou dan halverwege de dag
    ingrijpen en de rest van de klanten die week overslaan, zonder dat iemand
    dat merkt. Spreiden is beter dan de rem verhogen, want de rem moet blijven
    doen waar hij voor is."""
    schoon = (webshop_url or "").strip().lower()
    return sum(schoon.encode("utf-8")) % 7


def _is_aan_de_beurt(webshop_url, vandaag, alles=False):
    """Of deze klant vandaag gemeten wordt.

    Naast de vaste dag zit er een vangnet in: is een klant meer dan negen dagen
    niet gemeten, dan gebeurt het alsnog. Anders zou een gemiste cron of een
    storing betekenen dat iemand een week overslaat zonder dat het opvalt."""
    if alles:
        return True

    vorige = db.get_previous_score(webshop_url)
    laatste = (vorige or {}).get("aangemaakt_op")

    # Vandaag al gemeten? Dan niet nog een keer. Vuurt de cron door een storing
    # twee keer, of opent iemand de link met de sleutel nog eens om te kijken of
    # hij werkt, dan kreeg elke klant twee keer dezelfde weekmail, kwamen er
    # twee rapporten in zijn verloop, en draaiden de AI-metingen dubbel. Die
    # kosten dus ook dubbel.
    if laatste is not None:
        try:
            if laatste.date() == vandaag.date():
                return False
        except (AttributeError, TypeError):
            pass

    if meetdag(webshop_url) == vandaag.weekday():
        return True

    if laatste is None:
        return True
    try:
        dagen = (vandaag - laatste).days
    except TypeError:
        return True
    if dagen > 9:
        print(f"{webshop_url} is {dagen} dagen niet gemeten, wordt nu alsnog gedaan.")
        return True
    return False


def _shopify_abonnees():
    """De Shopify-winkels die betalen voor monitoring.

    Dit hoort hier omdat het anders stilletjes misgaat: op het scherm in de app
    staat "elke week opnieuw gemeten", en dat is precies wat je verkoopt. Wordt
    deze lijst niet meegenomen in de wekelijkse ronde, dan betaalt iemand 39
    dollar per maand voor iets wat nooit gebeurt, en dat merkt hij pas na
    weken.

    De stand komt elke keer vers van Shopify. Kunnen wij hem niet ophalen, dan
    slaan wij de winkel over in plaats van te gokken: liever een week te laat
    gemeten dan iemand meten die niet betaalt."""
    uit = []
    try:
        winkels = db.get_shopify_winkels()
    except Exception as e:
        print(f"Shopify-abonnees ophalen mislukt: {e}")
        return uit
    for rij in winkels:
        if not rij.get("actief") or not rij.get("toegangssleutel"):
            continue
        if not rij.get("webshop_url"):
            continue
        sleutel = _shopify_sleutel(rij)
        if not sleutel:
            # Verlopen sleutel en geen bruikbare verversleutel. Daar is zonder
            # de winkelier niets aan te doen: hij moet de app een keer openen.
            print(f"Shopify: geen werkende sleutel voor {rij['winkel']}, overgeslagen.")
            continue
        try:
            stand = shopify_billing.huidig_abonnement(rij["winkel"], sleutel)
        except Exception as e:
            print(f"Abonnement nakijken mislukt voor {rij['winkel']}: {e}")
            continue
        if not stand.get("actief"):
            if stand.get("fout"):
                # Wij WETEN het niet. Deze winkel wordt deze week overgeslagen
                # terwijl op zijn scherm staat dat hij elke week gemeten wordt.
                # Dat mag niet stil gebeuren.
                _meld_aan_beheer(
                    "Abonnement niet na te kijken",
                    f"Bij {rij['winkel']} lukte het niet om het abonnement bij Shopify "
                    f"op te vragen: {stand['fout']}. Die winkel is deze ronde "
                    f"overgeslagen. Kijk of hij nog klant is.")
            continue
        adres = (rij.get("email") or "").strip()
        if not adres or not _EMAIL_VORM.match(adres):
            # Hier stond een verzonnen adres. Dat ziet eruit als "we hebben hem
            # bericht" terwijl de mail nergens aankomt, en op het scherm staat
            # dat hij een waarschuwing krijgt als er iets verandert. Dan liever
            # geen mail en wel een melding in de logs.
            print(f"LET OP: geen mailadres voor {rij['winkel']}, deze klant krijgt "
                  f"geen weekbericht. Vul het aan in de database.")
            continue
        uit.append({"webshop_url": rij["webshop_url"], "email": adres,
                    "winkel": rij["winkel"]})
    if uit:
        print(f"{len(uit)} betalende Shopify-winkel(s) meegenomen in de ronde.")
    return uit


def _shopify_automatisch_aanvullen(winkel, base_url):
    """Vult uit onszelf aan bij een winkel met een abonnement.

    Dit is wat er op de prijskaart staat: nieuwe producten worden opgepakt en
    ingevuld. Zonder deze functie was dat een belofte zonder dekking.

    Let op wat hier anders is dan bij de knop. Bij de knop ziet de eigenaar
    elk voorstel voordat er iets gebeurt. Hier niet, want er is niemand die
    kijkt. Wat hij koopt is juist dat wij het doen zonder dat hij ernaar hoeft
    te kijken. Daarom drie dingen: hij kan het uitzetten, hij krijgt achteraf
    een mail met precies wat er veranderd is, en elke wijziging blijft met een
    knop terug te draaien. Dat laatste is de reden dat dit te verantwoorden is.

    Verder gelden alle gewone regels nog: alleen invullen waar het leeg is,
    nooit iets overschrijven, en de oude waarde eerst bewaren."""
    rij = db.get_shopify_winkel(winkel) or {}
    if not rij.get("toegangssleutel") or not rij.get("webshop_url"):
        return None
    if not rij.get("automatisch", True):
        print(f"Automatisch aanvullen staat uit voor {winkel}.")
        return None

    # Niet twee keer op een dag. Draait de cron dubbel, dan zou dat dubbele
    # kosten bij het model geven voor hetzelfde werk.
    laatst = rij.get("automatisch_op")
    if laatst:
        try:
            if (datetime.now(timezone.utc) - laatst).days < 5:
                return None
        except (TypeError, AttributeError):
            pass

    webshop_url = rij["webshop_url"]
    ruimte = kosten.mag_doorgaan(webshop_url=webshop_url)
    if not ruimte["mag"]:
        print(f"Automatisch aanvullen overgeslagen voor {winkel}: {ruimte['reden']}")
        return None

    sleutel = _shopify_sleutel(rij)
    if not sleutel:
        print(f"Automatisch aanvullen overgeslagen voor {winkel}: geen werkende sleutel.")
        return None

    try:
        markt_gegevens = _markt_van(webshop_url)
        uitkomst = shopify_werk.maak_voorstellen(winkel, sleutel, markt_gegevens)
    except Exception as e:
        print(f"Automatisch aanvullen mislukt voor {winkel}: {e}")
        return None

    gedaan = []
    for voorstel in (uitkomst.get("voorstellen") or [])[:shopify_werk.AUTOMATISCH_PER_WEEK]:
        # Elke keer opnieuw opvragen. Vijfentwintig wijzigingen kunnen langer
        # duren dan het uur dat een sleutel geldig is.
        sleutel = _shopify_sleutel(rij)
        if not sleutel:
            print(f"Automatisch aanvullen afgebroken voor {winkel}: sleutel verlopen.")
            break
        uit = shopify_werk.pas_toe(winkel, sleutel, voorstel, webshop_url)
        if uit.get("gelukt"):
            gedaan.append({"wat": voorstel.get("wat"), "waar": voorstel.get("waar"),
                           "nieuw": voorstel.get("nieuw")})
            db.tel_shopify_wijziging(winkel)

    db.markeer_shopify_automatisch(winkel)
    if not gedaan:
        return None

    print(f"Automatisch aangevuld bij {winkel}: {len(gedaan)} wijziging(en).")
    adres = (rij.get("email") or "").strip()
    if adres and _EMAIL_VORM.match(adres):
        try:
            emailing.send_shopify_bijgewerkt(
                adres, webshop_url, gedaan,
                _app_adres_in_beheerscherm(winkel),
                taal=_mailtaal(webshop_url))
        except Exception as e:
            print(f"Bericht over bijwerken mislukt voor {winkel}: {e}")
    return gedaan


def _draai_wekelijkse_scans(base_url, alles=False):
    """Doet de scans op de achtergrond. Draait los van het verzoek, zodat de
    aanroeper niet hoeft te wachten en er niets vastloopt, ook niet als er
    straks honderd abonnees zijn.

    Deze functie mag elke dag aangeroepen worden. Er wordt dan per dag alleen
    het deel van de klanten gedaan dat die dag aan de beurt is, waardoor elke
    klant een keer per week gemeten wordt en de kosten over de week verdeeld
    zijn. Met alles=True wordt iedereen gedaan, ongeacht de dag."""
    try:
        vandaag = datetime.now(timezone.utc)
        customers = payments.list_active_monitoring_customers() + _shopify_abonnees()
        aan_de_beurt = [c for c in customers
                        if _is_aan_de_beurt(c["webshop_url"], vandaag, alles)]
        print(f"{len(customers)} actieve klant(en), {len(aan_de_beurt)} vandaag aan de beurt.")
        for c in aan_de_beurt:
            try:
                scan_result = run_scan(c["webshop_url"])
                if "error" in scan_result:
                    print(f"Scan mislukt voor {c['webshop_url']}, overgeslagen.")
                    continue

                db.zet_platform(c["webshop_url"], scan_result.get("platform"))
                klant_token = db.get_or_create_klant(c["webshop_url"], c["email"])
                vorige = db.get_previous_score(c["webshop_url"])
                vorige_score = vorige["score"] if vorige else None

                db.save_report("monitoring", c["webshop_url"], c["email"], scan_result.get("score", 0),
                                scan_result.get("checks", []), None, None, klant_token)
                monitoring_url = f"{base_url}/monitoring/{klant_token}" if klant_token else None

                # Fase 5 stap 3: dezelfde ronde meteen gebruiken om de
                # koopvragen aan de AI-modellen te stellen.
                #
                # Dit gebeurde eerst NA de mail, zodat een storing bij een
                # AI-aanbieder de wekelijkse update nooit kon tegenhouden. Die
                # zorg is terecht, maar de prijs was hoog: de mail ging dan over
                # de meting van vorige week, en kon dus alleen het technische
                # cijfer melden. "Je score is nog steeds 51 van 100, er is niets
                # veranderd" is geen reden om 39 euro per maand te betalen. Waar
                # een klant voor betaalt is of AI hem noemt.
                #
                # Nu meten wij eerst en mailen daarna. De zorg blijft opgelost
                # doordat de mail hieronder buiten deze try staat: mislukt de
                # meting, dan gaat de mail gewoon uit, alleen zonder het blok
                # over vermeldingen.
                try:
                    _meet_en_beoordeel(c["webshop_url"], c["email"], klant_token, base_url)
                except Exception as e:
                    print(f"Meting mislukt voor {c['webshop_url']}: {e}")

                vermeldingen = None
                try:
                    vermeldingen = (_klantgegevens(c["webshop_url"]) or {}).get("vermeldingen")
                except Exception as e:
                    print(f"Vermeldingen ophalen mislukt voor {c['webshop_url']}: {e}")

                emailing.send_weekly_update_email(
                    c["email"], c["webshop_url"], scan_result, monitoring_url, vorige_score,
                    taal=_mailtaal(c["webshop_url"]), vermeldingen=vermeldingen,
                )

                # Is dit een Shopify-winkel met een abonnement, dan vullen wij
                # ook uit onszelf aan. Dat staat op de prijskaart en zonder dit
                # is het een belofte zonder dekking.
                if c.get("winkel"):
                    try:
                        _shopify_automatisch_aanvullen(c["winkel"], base_url)
                    except Exception as e:
                        print(f"Automatisch aanvullen mislukt voor {c['winkel']}: {e}")
            except Exception as e:
                print(f"Wekelijkse scan mislukt voor {c.get('webshop_url')}: {e}")
        print("Ronde afgerond.")
    except Exception as e:
        print(f"Wekelijkse scan volledig mislukt: {e}")


@app.route("/api/cron/weekly-scans", methods=["GET", "POST"])
def weekly_scans():
    """Wordt DAGELIJKS aangeroepen. Per dag is een deel van de klanten aan de
    beurt, zo verdeelt het werk en de kosten zich over de week en wordt elke
    klant een keer per week gemeten.

    Draait de cron nog wekelijks, zet er dan &alles=ja achter, dan wordt
    iedereen in een keer gedaan zoals vroeger. Bij meer dan ongeveer veertig
    klanten loopt dat tegen de dagelijkse kostenrem aan, dus dat is alleen
    bedoeld voor de overgang.

    Antwoordt meteen, het werk gebeurt op de achtergrond."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not _sleutel_klopt(request.args.get("key"), cron_key):
        return "", 404

    alles = request.args.get("alles") == "ja"
    base_url = get_base_url()
    threading.Thread(target=_draai_wekelijkse_scans, args=(base_url, alles), daemon=True).start()
    return "ok", 200


@app.after_request
def _shopify_inbed_kop(antwoord):
    """Een ingebedde app moet per verzoek zeggen wie hem in een venster mag zetten.

    Shopify eist dit voor de App Store, en het is tegelijk de enige bescherming
    tegen een willekeurige andere site die ons app-scherm in een onzichtbaar
    venster zet en de winkelier daarin laat klikken."""
    if not request.path.startswith("/shopify"):
        return antwoord
    winkel = shopify_app._schoon(request.args.get("shop") or "")
    if shopify_app.geldige_winkel(winkel):
        toegestaan = f"https://{winkel} https://admin.shopify.com"
    else:
        # Geen winkel in het verzoek, dus wij weten niet wie hem mag inbedden.
        # Dan niemand. Shopify stuurt bij het openen van het app-scherm altijd
        # de winkel mee, dus dit raakt geen echte bezoeker.
        toegestaan = "'none'"
    antwoord.headers["Content-Security-Policy"] = f"frame-ancestors {toegestaan};"
    return antwoord


def _benadering_ronde():
    """Eén rondje van de automatische benadering. Draait op de achtergrond.

    De volgorde is met opzet zo: eerst adressen zoeken (kost niets), dan meten
    (kost geld bij de modellen), dan pas mailen. Zo staat er altijd een voorraad
    gemeten winkels klaar en hoeft de post nooit te wachten op een meting.

    Alles wat deze ronde doet wordt onderweg opgeschreven in `verslag` en aan
    het eind bewaard. Dat is er bij gekomen omdat de lijst dagenlang op precies
    dezelfde standen bleef staan terwijl er elk uur een ronde langskwam, en van
    buitenaf niet te zien was welke van de zeven remmen dat deed. Nu staat het
    per ronde op de beheerpagina."""
    verslag = {"adressen": None, "gemeten_klaar": None, "ingepland": 0,
               "doorgezet": 0, "gemaild": 0, "mislukt": [], "redenen": []}
    benadering.onthoud_ronde()

    # Eerst kijken of de lijst zichzelf moet aanvullen. Zonder dit raakt de
    # benaderlijst gewoon op: bij vijftien mails per dag is tweehonderd winkels
    # binnen twee weken leeg, en dan staat de machine stil zonder dat er iets
    # kapot is. Dat gebeurt alleen als de voorraad onder de grens zakt, anders
    # betaal je voor namen die weken blijven liggen.
    try:
        aanvulling = winkelvinder.vul_aan_indien_nodig(
            ronde=benadering.rondenummer())
        verslag["gevonden_winkels"] = aanvulling.get("nieuw", 0)
        if aanvulling.get("gezocht") and aanvulling.get("reden"):
            verslag["redenen"].append(aanvulling["reden"])
    except Exception as e:
        verslag["mislukt"].append(f"winkels zoeken: {e}")
        print(f"Benadering, winkels zoeken mislukt: {e}")

    try:
        gevonden = benadering.zoek_adressen()
        verslag["adressen"] = gevonden
        print(f"Benadering, adressen: {gevonden}")
    except Exception as e:
        verslag["mislukt"].append(f"adressen zoeken: {e}")
        print(f"Benadering, adressen zoeken mislukt: {e}")

    try:
        # Aan beide kanten door dezelfde schrijfwijze halen voordat wij
        # vergelijken.
        #
        # Waarom: dit is de vergelijking die bepaalt of een winkel van "meten"
        # naar "gemeten" gaat, en dus of hij ooit post krijgt. Klopt hij niet,
        # dan wordt dezelfde winkel elk uur opnieuw gemeten en gaat er nooit
        # iets uit, zonder dat er ergens een foutmelding verschijnt. De
        # rapporten van voor september staan nog in de oude schrijfwijze, met
        # www ervoor of http in plaats van https, en die zouden hier stil langs
        # elkaar heen lopen.
        # LET OP de ondergrens hieronder. Een winkel telt pas als gemeten als de
        # meting ook bruikbaar is voor post. Stond hier "meer dan nul vragen", dan
        # gebeurde dit: een winkel met vijf vragen ging naar "gemeten", de mail
        # weigerde hem omdat er minstens tien nodig zijn, de ronde zette hem terug
        # op "adres", en de volgende ronde zag "meer dan nul" en zette hem weer op
        # "gemeten". Eeuwig rond, en nooit post.
        # LET OP: dit hangt NIET meer aan het demorapport. Dat rapport werd
        # maandenlang niet bewaard door een NOT NULL op de kolom email, en
        # daardoor gold geen enkele meting als bruikbaar terwijl er 55 winkels
        # met beoordeelde antwoorden stonden. "Bruikbaar" hoort te hangen aan
        # het enige dat telt: genoeg meegetelde vragen om post te kunnen sturen.
        al_gemeten = {scan_engine.normalize_url(u)
                      for u in db.winkels_met_genoeg_vragen(MINIMUM_VRAGEN_VOOR_POST)}
        verslag["gemeten_klaar"] = len(al_gemeten)
        # Opruimen gaat voor de geldcontrole uit, en dat is geen detail. Zolang
        # dit binnen te_meten zat werd er bij een lege dagpot niets vrijgemaakt,
        # en bleven winkels voorgoed op "meten" staan. Opruimen kost niets.
        verslag["vrijgemaakt"] = benadering.maak_vastgelopen_metingen_vrij(al_gemeten)

        # De wachtrij staat in het geheugen en verdwijnt bij elke herstart van
        # Render, ook bij een nieuwe versie. Winkels bleven dan op "meten" staan
        # terwijl er niets meer liep, en kwamen pas zes uur later weer aan de
        # beurt. Ondertussen zette elke ronde er vijf nieuwe bij, dus de teller
        # "meten" liep op naar vijfenzestig zonder dat er iets gebeurde.
        #
        # Nu: staat de wachtrij leeg en loopt er niets, dan pakken wij eerst op
        # wat er al op "meten" staat, voordat wij er nieuwe bij zetten.
        verslag["opnieuw_opgepakt"] = _hervat_onderbroken_metingen()

        # En niet nog meer inplannen zolang er nog werk ligt. Zonder deze rem
        # groeit de lijst sneller dan de werker hem afwerkt, en dan zegt de
        # pagina "65 in meting" terwijl er een voor een gemeten wordt.
        in_de_rij = len(_demo_wachtrij) + _metingen_bezig()
        verslag["in_de_rij"] = in_de_rij
        ruimte = kosten.ruimte_voor_benadering()
        verslag["dagpot"] = {
            "besteed": (round(ruimte["besteed"], 2)
                        if ruimte.get("besteed") is not None else None),
            "grens": (round(ruimte["grens"], 2)
                      if ruimte.get("grens") is not None else None),
            "past_nog": ruimte.get("past_nog"),
        }
        # Niet meer inplannen dan er met de rest van de dagpot betaald kan
        # worden. Zonder deze grens plande een ronde er gewoon vijf in, ook als
        # er nog maar twee euro over was. Die metingen worden dan halverwege
        # afgekapt door de rem: wel betaald bij de modellen, geen uitkomst, en
        # de winkel blijft op "meten" staan tot hij na zes uur opnieuw mag.
        past = ruimte.get("past_nog")
        hoeveel = None if past is None else min(
            past, benadering.instellingen()["metingen_per_ronde"])
        mag_meten = (ruimte["mag"] and (hoeveel is None or hoeveel > 0)
                     and in_de_rij < WACHTRIJ_VOL)
        klaar_te_meten = (benadering.te_meten(hoeveel=hoeveel, al_gemeten=al_gemeten)
                          if mag_meten else [])
        if in_de_rij >= WACHTRIJ_VOL:
            verslag["redenen"].append(
                f"Er staan al {in_de_rij} metingen in de rij, dus er zijn er geen "
                f"nieuwe bij gezet. Een meting duurt minuten en ze gaan een voor "
                f"een.")
        if ruimte["mag"] and hoeveel == 0:
            verslag["redenen"].append("Er is nog wel dagpot over, maar niet genoeg "
                                      "voor een hele meting.")
            print("Benadering, geen metingen deze ronde: er is nog wel dagpot over, "
                  "maar niet genoeg voor een hele meting.")
        if not ruimte["mag"]:
            verslag["redenen"].append(ruimte["reden"])
            print(f"Benadering, geen metingen deze ronde: {ruimte['reden']}")
        if ruimte["mag"] and (hoeveel is None or hoeveel > 0) and not klaar_te_meten:
            verslag["redenen"].append("Er stond geen enkele winkel klaar om te "
                                      "meten: alles staat al op gemeten, in de "
                                      "meting, of zonder adres.")
        if klaar_te_meten:
            # EERST vastleggen dat deze winkels in de meting zitten, en pas
            # daarna de meting starten. Andersom gaat er een ronde overheen
            # waarin ze nog op "adres" staan, komen ze opnieuw aan de beurt, en
            # betaal je twee keer voor dezelfde meting. Dat is precies wat er
            # gebeurd is: vijf winkels, elk drie tot vijf keer gemeten.
            benadering.markeer_in_meting(klaar_te_meten)
            erbij = _demo_inplannen(klaar_te_meten, benchmark_stand=True,
                                    vragen=BENADERING_VRAGEN)
            verslag["ingepland"] = len(klaar_te_meten)
            verslag["winkels"] = [str(u) for u in klaar_te_meten[:5]]
            if not erbij:
                # Dit is het geval waar wij eerder blind voor waren: de winkels
                # gaan wel op "meten" maar de wachtrij pakt ze niet op, en dan
                # blijft de lijst dagenlang op precies dezelfde standen staan.
                verslag["redenen"].append(
                    f"{len(klaar_te_meten)} winkel(s) klaargezet, maar de meetrij "
                    f"nam er geen enkele aan.")
            print(f"Benadering, in de meetrij gezet: {len(klaar_te_meten)}")
        # Winkels waarvan de meting inmiddels klaar is doorzetten naar 'gemeten'.
        # Ook de winkels die nu op "meten" staan, want daar zit de winst: die
        # zijn betaald en moeten niet nog een keer.
        doorgezet = 0
        for winkel in db.get_benaderingen(stand=("adres", "meten")):
            if scan_engine.normalize_url(winkel["webshop_url"]) in al_gemeten:
                db.zet_benadering(winkel["webshop_url"], stand="gemeten")
                doorgezet += 1
        verslag["doorgezet"] = doorgezet

        # En de andere kant op: staat een winkel op "gemeten" terwijl zijn meting
        # niet bruikbaar is, dan hoort hij daar niet te staan.
        #
        # Waarom dit nodig is. Op 11 september stonden er 43 winkels op "gemeten"
        # en zei de pagina "43 winkels staan klaar om post te krijgen". Dat was
        # niet waar: die waren allemaal gemeten toen de kostenrem nog na drie
        # vragen afkapte, en de mail weigert onder de tien. Elke ronde probeerde
        # er drie, kreeg drie keer nul, en zette er drie terug. Dat zijn vijftien
        # rondes om de lijst één keer door te komen, en ondertussen stond er een
        # getal op het scherm dat niets betekende.
        #
        # Nu gebeurt het in één keer en klopt de teller meteen.
        terug = 0
        opgegeven = 0
        for winkel in db.get_benaderingen(stand="gemeten"):
            if scan_engine.normalize_url(winkel["webshop_url"]) in al_gemeten:
                # Deze had wel genoeg vragen. Teller schoon, want de
                # geschiedenis doet er niet meer toe.
                benadering.vergeet_meetpogingen(winkel["webshop_url"])
                continue
            # Hoe vaak hebben wij het bij deze winkel al geprobeerd? Dit is de
            # rem die er niet was. Zonder deze telling kwam dezelfde winkel elke
            # dag terug, kostte elke dag geld, en werd elke dag opnieuw
            # geweigerd voor de mail. Dat is geen storing die overgaat: bij
            # sommige winkels noemt AI bij die koopvragen gewoon nooit een
            # winkel, en dan is er morgen ook niets te melden.
            poging = benadering.tel_meetpoging(winkel["webshop_url"])
            if poging >= benadering.MAX_MEETPOGINGEN:
                db.zet_benadering(
                    winkel["webshop_url"], stand="afgevallen",
                    notitie=(f"Na {poging} metingen nog steeds te weinig vragen waar "
                             f"AI een winkel noemt. Hier valt geen eerlijke uitkomst "
                             f"over te sturen, dus wij stoppen ermee."))
                opgegeven += 1
                continue
            db.zet_benadering(
                winkel["webshop_url"], stand="adres",
                notitie=(f"Meting haalde te weinig vragen, opnieuw ingepland "
                         f"(poging {poging} van {benadering.MAX_MEETPOGINGEN})."))
            terug += 1
        verslag["terug_naar_meten"] = terug
        verslag["opgegeven"] = opgegeven
        if terug:
            verslag["redenen"].append(
                f"{terug} winkel(s) stonden op 'gemeten' met een meting die te weinig "
                f"vragen haalde. Die worden opnieuw gemeten.")
    except Exception as e:
        verslag["mislukt"].append(f"meten: {e}")
        print(f"Benadering, meten mislukt: {e}")

    try:
        mag, reden = benadering.hoeveel_mag_er_nu()
        if not mag:
            verslag["redenen"].append(reden)
            print(f"Benadering, geen post deze ronde: {reden}")
            benadering.onthoud_rondeverslag(verslag)
            return
        beurt = benadering.te_mailen(mag)
        if not beurt:
            verslag["redenen"].append("Er mocht wel post uit, maar geen enkele winkel "
                                      "was aan de beurt: gemeten, adres bekend en nog "
                                      "nooit gemaild.")
        for winkel in beurt:
            gelukt, fout = _stuur_onderzoeksmail(winkel["webshop_url"], winkel["email"],
                                                 winkel.get("land"))
            benadering.markeer_gemaild(winkel["webshop_url"], gelukt, fout)
            if gelukt:
                # Ook in het winkelprofiel, want dat is wat de beheerpagina
                # toont. Stond het alleen op de benaderlijst, dan zag je daar
                # een lege kolom en drukte je met de hand nog eens op versturen.
                db.markeer_onderzoeksmail(winkel["webshop_url"])
                verslag["gemaild"] += 1
                # De namen erbij, niet alleen het aantal. "gemaild: 2" laat je
                # nog steeds raden of het echt gebeurd is en naar wie.
                verslag.setdefault("naar", []).append(
                    f"{winkel['webshop_url']} ({winkel['email']})")
            else:
                verslag["mislukt"].append(
                    f"mail {winkel['webshop_url']}: {str(fout)[:120]}")
            print(f"Benadering, mail naar {winkel['webshop_url']}: "
                  f"{'gelukt' if gelukt else fout}")
    except Exception as e:
        verslag["mislukt"].append(f"mailen: {e}")
        print(f"Benadering, mailen mislukt: {e}")

    # Het warmste publiek dat er is: mensen die zelf hun mailadres invulden voor
    # de gratis test. Die kregen tot nu toe hun uitkomst en daarna nooit meer
    # iets. Bewust NA de benadering, want dit gaat om een handvol mails per dag
    # en de benaderlijst is groter.
    try:
        verslag["opgevolgd"] = _volg_gratis_tests_op()
    except Exception as e:
        verslag["mislukt"].append(f"opvolging: {e}")
        print(f"Opvolging gratis tests mislukt: {e}")

    benadering.onthoud_rondeverslag(verslag)
    _dagbericht_sturen()


# Hoeveel dagen na de gratis test wij nog een keer schrijven. Kort genoeg dat
# iemand het zich herinnert, lang genoeg dat het niet als een verkoopmachine
# leest.
OPVOLGEN_NA_DAGEN = int(os.environ.get("OPVOLGEN_NA_DAGEN", "3"))
OPVOLGEN_PER_RONDE = int(os.environ.get("OPVOLGEN_PER_RONDE", "3"))


def _volg_gratis_tests_op():
    """Stuurt een tweede bericht aan aanvragers van de gratis test.

    Houdt zich aan dezelfde klok en dezelfde schakelaar als de rest van de post.
    Staat de benadering uit, dan gaat hier ook niets uit: dat is een schakelaar
    voor alle ongevraagde post, niet alleen voor de benaderlijst.

    Wat hier anders is dan bij de benadering: deze mensen hebben er zelf om
    gevraagd. Ze krijgen precies een herinnering en daarna nooit meer."""
    inst = benadering.instellingen()
    if not inst["aan"] or not benadering.binnen_kantooruren():
        return 0
    gedaan = 0
    for lead in db.leads_om_op_te_volgen(na_dagen=OPVOLGEN_NA_DAGEN,
                                         hoeveel=OPVOLGEN_PER_RONDE):
        try:
            if db.is_afgemeld(lead["webshop_url"]):
                db.markeer_lead_opgevolgd(lead["id"])
                continue
            gelukt = emailing.send_opvolging_gratis_test(
                lead["email"], lead["webshop_url"], get_base_url(),
                taal=_mailtaal(lead["webshop_url"]))
            # Ook bij een mislukte verzending afvinken. Blijft hij openstaan,
            # dan probeert elke ronde hetzelfde adres opnieuw, en een adres dat
            # blijft weigeren is precies wat je reputatie sloopt.
            db.markeer_lead_opgevolgd(lead["id"])
            if gelukt:
                gedaan += 1
            print(f"Opvolging naar {lead['email']} voor {lead['webshop_url']}: "
                  f"{'gelukt' if gelukt else 'mislukt'}")
        except Exception as e:
            print(f"Opvolging mislukt voor {lead.get('email')}: {e}")
    return gedaan


def _dagbericht_sturen():
    """Eén keer per dag een berichtje aan jezelf over hoe de benadering loopt.

    Dit bestaat omdat de lijst drie dagen stilstond en dat pas opviel toen er
    met de hand op de beheerpagina gekeken werd. Een machine die stilstaat en
    daar niets over zegt kost elke dag geld en levert niets op. Liever een mail
    te veel dan nog een keer drie dagen niets.

    Faalt hij, dan gebeurt er verder niets. Een bericht over de ronde mag de
    ronde zelf nooit omgooien."""
    ontvanger = os.environ.get("BEHEERDER_EMAIL")
    if not ontvanger:
        return
    try:
        if benadering.dagbericht_al_gestuurd():
            return
        # Alleen binnen de uren dat er post uitgaat, anders krijg je het bericht
        # om zes uur 's ochtends terwijl de dag nog niets gedaan heeft.
        if not benadering.binnen_kantooruren():
            return
        bezig = len([1 for stand in _demo_status.values()
                     if stand and stand != "klaar" and not stand.startswith("mislukt")])
        dagpot = kosten.ruimte_voor_benadering()
        diagnose = benadering.waarom_gaat_er_niets_uit(
            moment_laatste_ronde=benadering.laatste_ronde(),
            meetruimte=dagpot, metingen_bezig=bezig)
        onderwerp, regels = benadering.dagbericht_tekst(
            diagnose, dagpot=dagpot, trechter=db.trechter_benadering())
        body = "".join(f"<p>{emailing.veilig(r)}</p>" for r in regels)
        if emailing.send_email(ontvanger, onderwerp, body):
            benadering.onthoud_dagbericht()
    except Exception as e:
        print(f"Dagbericht mislukt: {e}")


def _nu_meten_en_mailen(webshop_url):
    """Eén winkel meteen meten en daarna zijn uitkomst mailen.

    Dit staat naast de gewone ronde en niet erin, met opzet. De ronde houdt zich
    aan de dagpot, aan de klok en aan de rondelimiet, en dat hoort ook zo. Maar
    als er dagenlang niets uitgaat wil je één winkel kunnen pakken en met eigen
    ogen zien waar het stukloopt, in plaats van nog een uur te wachten op een
    ronde die het weer stil overslaat.

    Wat hij wel blijft respecteren: de kostenrem per meting en het feit dat een
    winkel maar één keer post krijgt. Hij mag dus geld kosten, maar hij kan geen
    dubbele mail sturen."""
    verslag = {"handmatig": webshop_url, "gemaild": 0, "mislukt": [], "redenen": []}
    try:
        winkel = None
        for rij in db.get_benaderingen(alleen_niet_afgemeld=False):
            if scan_engine.normalize_url(rij["webshop_url"]) == webshop_url:
                winkel = rij
                break
        if winkel is None:
            verslag["redenen"] = ["Deze winkel staat niet op de benaderlijst."]
        elif winkel.get("gemaild_op"):
            verslag["redenen"] = ["Deze winkel heeft al post gehad, dus er gaat niets uit."]
        elif not winkel.get("email"):
            verslag["redenen"] = ["Van deze winkel kennen wij geen algemeen "
                                  "e-mailadres, dus er kan niets heen."]
        else:
            benadering.markeer_in_meting([webshop_url])
            _demo_draaien(webshop_url, benchmark_stand=True,
                          vragen=BENADERING_VRAGEN)
            stand = _demo_status.get(webshop_url) or ""
            if stand.startswith("mislukt"):
                verslag["redenen"] = [f"De meting is mislukt: {stand[:160]}"]
                db.zet_benadering(webshop_url, stand="adres", notitie=stand[:400])
            else:
                db.zet_benadering(webshop_url, stand="gemeten")
                gelukt, fout = _stuur_onderzoeksmail(
                    webshop_url, winkel["email"], winkel.get("land"))
                benadering.markeer_gemaild(webshop_url, gelukt, fout)
                if gelukt:
                    db.markeer_onderzoeksmail(webshop_url)
                    verslag["gemaild"] = 1
                    verslag["redenen"] = [f"Gemeten en gemaild naar {winkel['email']}."]
                else:
                    verslag["redenen"] = [f"Wel gemeten, mail mislukt: {str(fout)[:160]}"]
                    verslag["mislukt"].append(str(fout)[:160])
    except Exception as e:
        verslag["mislukt"].append(str(e)[:200])
        verslag["redenen"] = [f"Er ging iets mis: {str(e)[:160]}"]
    print(f"Handmatig, {webshop_url}: {'; '.join(verslag['redenen'])}")
    benadering.onthoud_rondeverslag(verslag)


# Hoeveel vragen een meting voor de benadering stelt.
#
# Dit getal MOET boven MINIMUM_VRAGEN_VOOR_POST liggen, en daar zat een fout die
# alle post tegenhield zonder dat er ergens een foutmelding verscheen. De
# benadering mat met de benchmarkstand, en die stelt er vijf. De mail weigert
# onder de tien. Elke winkel werd dus keurig gemeten, kostte geld, en kreeg
# daarna te horen "er zijn maar 5 vragen meegeteld, dat is te weinig". Nul post,
# elke dag opnieuw, met de rekening er wel bij. Een test bewaakt nu dat deze
# twee getallen elkaar niet meer stilletjes kunnen tegenspreken.
#
# Vijftien en niet elf, omdat niet elke gestelde vraag ook meetelt: een model dat
# uitvalt of een antwoord dat niets oplevert telt niet mee. Met vijftien houd je
# marge boven de tien en blijft de meting binnen de schatting van 75 cent.
BENADERING_VRAGEN = int(os.environ.get("BENADERING_VRAGEN", "15"))

# Onder hoeveel meegetelde vragen wij geen post sturen.
#
# Tien is de ondergrens waaronder een uitkomst niets zegt. Een winkel die bij 0
# van de 4 vragen genoemd wordt, kan bij 30 vragen prima drie keer voorkomen.
# Ongevraagde post met zo'n cijfer erin is niet alleen zwak, hij is misleidend.
MINIMUM_VRAGEN_VOOR_POST = 10

# Vanaf hoeveel gemeten winkels wij onszelf een onderzoek mogen noemen in de
# vergelijkingsregel. Onder dit aantal laten wij die regel weg.
MINIMUM_WINKELS_VOOR_VERGELIJKING = 25


def _stuur_onderzoeksmail(webshop_url, email, land=None):
    """Stuurt één winkel zijn eigen uitkomst. Geeft (gelukt, reden) terug.

    Eén plek voor zowel de knop met de hand als de automatische ronde, zodat er
    nooit twee versies van deze mail ontstaan."""
    if not email or not _EMAIL_VORM.match(email or ""):
        return False, "Geen geldig mailadres."
    # De enige plek waar de onderzoeksmail vandaan komt, dus ook de enige plek
    # waar de afmelding gecontroleerd hoeft te worden. Zowel de knop met de
    # hand als de automatische ronde komt hier langs.
    if db.is_afgemeld(webshop_url):
        return False, "Deze winkel heeft zich afgemeld. Er gaat geen post meer heen."
    token = db.get_benchmark_token(webshop_url)
    if not token:
        return False, "Er kon geen link naar de uitkomst gemaakt worden."
    try:
        gegevens = _klantgegevens(webshop_url)
        v = gegevens.get("vermeldingen") or {}
        if not v.get("telbaar"):
            return False, "Deze winkel is nog niet gemeten."
        # Een uitkomst op een handjevol vragen is geen uitkomst. Krijgt iemand
        # ongevraagd post met "genoemd bij 0 van de 4 vragen", dan is de eerste
        # gedachte niet "goh" maar "dit stelt niets voor", en dat is terecht.
        # Zo'n meting is een afgebroken ronde, en die hoort niet de deur uit.
        if v["telbaar"] < MINIMUM_VRAGEN_VOOR_POST:
            # En dan niet op "gemeten" laten staan. Doe je dat wel, dan komt deze
            # winkel elke ronde opnieuw langs, wordt elke ronde opnieuw
            # geweigerd, en krijgt hij nooit post. Ondertussen bezet hij wel een
            # plek in de rij van winkels die wel klaar zijn. Terug naar "adres"
            # betekent: opnieuw meten, nu met vijftien vragen.
            return False, (f"TE_WEINIG_VRAGEN: er zijn maar {v['telbaar']} vragen "
                           f"meegeteld, dat is te weinig voor een uitkomst. De meting "
                           f"is halverwege gestopt of dateert van voor 10 september, "
                           f"toen er nog met vijf vragen gemeten werd. Deze winkel "
                           f"wordt opnieuw gemeten.")

        c = benchmark.tel_op(db.benchmark_regels())
        # De vergelijking met de andere winkels alleen meesturen als er ook echt
        # iets te vergelijken valt.
        #
        # Deze mail heet een onderzoek en leunt op dat woord. Staat er "van de 5
        # gemeten winkels", dan leest de ontvanger terecht: dit is geen
        # onderzoek, dit is een verkoopmail met een jasje aan. Onder de grens
        # laten wij die regel gewoon weg; de mail werkt ook zonder.
        genoeg = (c.get("gemeten") or 0) >= MINIMUM_WINKELS_VOOR_VERGELIJKING
        basis = get_base_url()
        gelukt = emailing.send_onderzoeksmail(
            email, webshop_url, f"{basis}/uitkomst/{token}",
            genoemd=v.get("genoemd"), telbaar=v.get("telbaar"),
            nooit_genoemd=c.get("nooit_genoemd") if genoeg else None,
            gemeten=c.get("gemeten") if genoeg else None,
            afmeld_url=f"{basis}/afmelden/{token}", land=land)
        return bool(gelukt), None if gelukt else "Verzenden mislukt, kijk in de logs."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:200]


@app.route("/wakker")
def wakker():
    """Een piepklein antwoord om de app wakker te houden.

    Render zet een app die vijftien minuten niets te doen heeft in de slaap.
    De eerstvolgende bezoeker wacht dan een halve minuut op een leeg scherm,
    en dat is precies wat er gebeurde bij het openen van de Shopify-app.

    Roep dit elke tien minuten aan. Bewust zonder sleutel en zonder database:
    dit moet het altijd doen en niets kosten."""
    return "ok", 200


@app.route("/api/cron/benadering", methods=["GET", "POST"])
def cron_benadering():
    """Elk uur aanroepen vanuit Render. Doet per keer een klein stukje.

    Antwoordt meteen, het werk gebeurt op de achtergrond."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not _sleutel_klopt(request.args.get("key"), cron_key):
        return "", 404
    threading.Thread(target=_benadering_ronde, daemon=True).start()
    return "ok", 200


@app.route("/afmelden/<token>", methods=["GET", "POST"])
def afmelden(token):
    """De afmeldlink uit de mail. Eén klik, geen vragen, geen formulier.

    Elke mail die je stuurt aan iemand die er niet om vroeg moet dit hebben, en
    hij moet echt werken. Een afmeldlink die om een bevestiging vraagt is de
    reden dat mensen op 'spam' drukken in plaats van op de link.

    Ook op POST, want de knop 'Afmelden' die Gmail zelf bovenaan de mail zet
    stuurt een POST en geen GET. Zonder dat doet die knop niets."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url:
        if request.method == "POST":
            return "", 404
        return render_template("afgemeld.html", gelukt=False), 404

    # Kijken of het echt bewaard is. Een bevestigingsscherm tonen terwijl er
    # niets is opgeslagen is erger dan een foutmelding: hij denkt dat het
    # geregeld is en krijgt toch weer post.
    bewaard = db.meld_benadering_af(webshop_url)
    if not bewaard:
        print(f"LET OP: afmelding NIET bewaard voor {webshop_url}")
        if request.method == "POST":
            return "", 500
        return render_template("afgemeld.html", gelukt=False), 500

    if request.method == "POST":
        return "", 200
    return render_template("afgemeld.html", gelukt=True, winkel=webshop_url)


@app.route("/admin/benadering", methods=["GET", "POST"])
def admin_benadering():
    """De machinekamer van de benadering: de lijst erin, de rem instellen, en
    zien wat er gebeurd is."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        actie = (request.form.get("actie") or "").strip()
        if actie == "lijst":
            uit = benadering.voeg_lijst_toe(request.form.get("lijst") or "")
            melding = (f"{uit['nieuw']} nieuwe winkels toegevoegd, "
                       f"{uit['al_bekend']} stonden er al op.")
            if uit["fout"]:
                melding += f" {len(uit['fout'])} regel(s) overgeslagen: {uit['fout'][:3]}"
        elif actie == "instellingen":
            db.zet_instelling("benadering_aan",
                              "ja" if request.form.get("aan") == "ja" else "nee")
            for veld in ("mail_per_dag", "mail_per_ronde", "adressen_per_ronde",
                         "metingen_per_ronde"):
                waarde = (request.form.get(veld) or "").strip()
                if waarde.isdigit():
                    db.zet_instelling(veld, int(waarde))
            melding = "Instellingen bewaard."
        elif actie == "ronde":
            threading.Thread(target=_benadering_ronde, daemon=True).start()
            melding = ("Een ronde is gestart. Ververs deze pagina over een minuut "
                       "of twee, dan zie je het resultaat.")
        elif actie == "nu":
            url = scan_engine.normalize_url((request.form.get("url") or "").strip())
            if not url or "." not in url:
                melding = "Vul een webadres in, bijvoorbeeld voorbeeldwinkel.nl."
            else:
                threading.Thread(target=_nu_meten_en_mailen, args=(url,),
                                 daemon=True).start()
                melding = (f"{url} wordt nu gemeten en daarna gemaild. Dit duurt een "
                           f"paar minuten. Ververs deze pagina, de uitkomst komt in "
                           f"het logboek hierboven te staan.")
        elif actie == "stand":
            url = (request.form.get("url") or "").strip()
            nieuwe = (request.form.get("stand") or "").strip()
            if db.zet_benadering(url, stand=nieuwe):
                melding = f"{url} staat nu op {nieuwe}."
            else:
                melding = "Dat lukte niet."

    inst = benadering.instellingen()
    mag, reden = benadering.hoeveel_mag_er_nu()
    # Hoeveel metingen er op dit moment echt lopen. Zonder dit getal lijkt een
    # ronde die gewoon aan het werk is precies op een ronde die vastligt.
    bezig = _metingen_bezig()
    return render_template(
        "admin_benadering.html",
        diagnose=benadering.waarom_gaat_er_niets_uit(
            moment_laatste_ronde=benadering.laatste_ronde(),
            meetruimte=kosten.ruimte_voor_benadering(),
            metingen_bezig=bezig),
        trechter=db.trechter_benadering(),
        verslagen=benadering.rondeverslagen(),
        meetfouten=benadering.meetfouten(),
        wachtrij=len(_demo_wachtrij),
        nu_bezig=[u for u, st in _demo_status.items()
                  if st and st != "klaar" and not st.startswith("mislukt")][:5],
        nu_bezig_stand=dict(list(_demo_status.items())[-5:]),
        dagpot=kosten.ruimte_voor_benadering(),
        regels=db.get_benaderingen(alleen_niet_afgemeld=False),
        tellingen=db.tel_benaderingen(),
        instellingen=inst,
        mag_nu=mag,
        reden=reden,
        standen=db.BENADER_STANDEN,
        melding=melding,
        sleutel=admin_key,
    )


@app.route("/monitoring/<klant_token>")
@app.route("/monitoring/<klant_token>/details")
def monitoring_pagina(klant_token):
    """De klantpagina. Twee weergaven op dezelfde gegevens.

    Standaard krijgt een klant alleen zijn takenlijst. De cijfers, citaten,
    concurrenten en de dertien controlepunten staan op /details.

    Dat is bewust zo gesplitst. Alles op een pagina zetten leverde tien blokken
    op waar een winkeleigenaar niet doorheen kwam, en dan is het niet meer
    duidelijk wat hij moet doen. De cijfers zijn de onderbouwing, niet het
    product."""
    details = request.path.endswith("/details")
    klant = db.get_klant(klant_token)
    if klant is None:
        return "Deze pagina bestaat niet of is niet meer geldig.", 404

    rapporten = db.get_klant_rapporten(klant_token)
    laatste = rapporten[0] if rapporten else None
    vorige = rapporten[1] if len(rapporten) > 1 else None

    # Loopt er echt een abonnement? Een klant die alleen de uitvoering van 149
    # euro kocht krijgt dezelfde pagina, en die las tot nu toe "je betaalt 39
    # euro per maand" met een opzegknop eronder. Dat is een onjuiste mededeling
    # over een betalingsverplichting, en het is precies het soort fout waar
    # iemand zijn geld voor terugvraagt.
    abonnement = any((r.get("type") or "") == "monitoring" for r in rapporten)

    verschil = None
    nieuwe_problemen = []
    checks_by_categorie = {}

    if laatste:
        if vorige:
            verschil = laatste["score"] - vorige["score"]
            vorige_problemen = {
                c["titel"] for c in vorige["checks"] if c["status"] != "ok"
            }
            nieuwe_problemen = [
                c for c in laatste["checks"]
                if c["status"] != "ok" and c["titel"] not in vorige_problemen
            ]
        for c in laatste["checks"]:
            checks_by_categorie.setdefault(c.get("categorie", "overig"), []).append(c)

    verloop = list(reversed(rapporten))[-8:]

    # Fase 5 stap 7: de vermeldingen bij AI, als die er zijn. Staat er nog
    # niets, dan tonen we hier ook niets. Een lege sectie met nullen erin leest
    # als een slechte uitkomst, terwijl er alleen nog niet gemeten is.
    gegevens = _klantgegevens(klant["webshop_url"])

    pagina = _paginagegevens(klant["webshop_url"])
    return render_template(
        "monitoring_details.html" if details else "monitoring.html",
        t=pagina["t"],
        paginataal=pagina["taal"],
        shopify_beheer=pagina["shopify_beheer"],
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        bronnen=gegevens["bronnen"],
        actieplan=gegevens["actieplan"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"],
            taal=_mailtaal(klant["webshop_url"])),
        webshop_url=klant["webshop_url"],
        klant_token=klant_token,
        laatste=laatste,
        verschil=verschil,
        verloop=verloop,
        nieuwe_problemen=nieuwe_problemen,
        checks_by_categorie=checks_by_categorie,
        uitvoering=_laatste_uitvoering(klant["webshop_url"]),
        wijzigingen=db.get_wijzigingen(klant["webshop_url"]),
        abonnement=abonnement,
        status_labels=_standlabels(pagina["t"]),
    )


@app.route("/rapport/<token>")
def rapport(token):
    report = db.get_report(token)
    if report is None:
        return "Rapport niet gevonden.", 404

    checks = report["checks"]
    by_categorie = {}
    for c in checks:
        by_categorie.setdefault(c.get("categorie", "overig"), []).append(c)

    history = db.get_history(report["webshop_url"]) if report["type"] == "monitoring" else []

    return render_template(
        "rapport.html",
        type=report["type"],
        webshop_url=report["webshop_url"],
        score=report["score"],
        fixes=report.get("fixes"),
        checks_by_categorie=by_categorie,
        history=history,
        aangemaakt_op=report["aangemaakt_op"].strftime("%d-%m-%Y"),
        status_labels=_standlabels(
            paginataal.teksten(_mailtaal(report["webshop_url"]))),
    )


def _standlabels(t):
    """De labels bij de dertien controlepunten, in de taal van de pagina.

    Stonden hard in drie render-aanroepen, alle drie in het Nederlands. Een
    Engelse winkel zag daardoor "verbeterpunt" tussen verder Engelse tekst."""
    return {"ok": t["stand_ok"], "deels": t["stand_deels"],
            "probleem": t["stand_probleem"]}


def _paginagegevens(webshop_url):
    """De taal van de klantpagina, en het adres van de app als dit een
    Shopify-winkel is.

    Twee dingen die bij elkaar horen omdat ze op dezelfde pagina thuishoren en
    door twee routes gebruikt worden: de echte klantpagina en de
    voorbeeldweergave. Zouden die het elk zelf uitrekenen, dan is de
    voorbeeldweergave niet meer waar hij voor bedoeld is: laten zien wat een
    klant precies ziet."""
    taal = _mailtaal(webshop_url)
    beheer = None
    try:
        rij = db.shopify_winkel_bij_webadres(webshop_url)
        if rij and rij.get("winkel"):
            beheer = _app_adres_in_beheerscherm(rij["winkel"])
    except Exception as e:
        print(f"Shopify-winkel zoeken mislukt voor {webshop_url}: {e}")
    return {"taal": taal, "t": paginataal.teksten(taal), "shopify_beheer": beheer}


def _markt_van(webshop_url):
    """In welke taal en voor welk land we deze winkel meten.

    Weten we het niet, dan komt er Nederlands uit, want dat is wat Krillo altijd
    al deed en wat voor alle bestaande klanten klopt."""
    try:
        profiel = db.get_winkelprofiel(webshop_url) or {}
        return markt.bepaal(profiel.get("taal"), profiel.get("land"))
    except Exception as e:
        print(f"Markt ophalen mislukt voor {webshop_url}: {e}")
        return markt.bepaal(None, None)


def _genereer_koopvragen_achtergrond(webshop_url, vervang=False):
    """Draait op de achtergrond, want scannen plus vragen bedenken duurt een
    minuut of meer. De pagina hoeft daar niet op te wachten."""
    try:
        scan_result = run_scan(webshop_url)
        extra = scan_result.get("gevonden_paginas") if "error" not in scan_result else None
        m = _markt_van(webshop_url)
        print(f"Koopvragen voor {webshop_url} in {markt.omschrijving(m)}.")
        resultaat = koopvragen.genereer_koopvragen(
            webshop_url, extra, taal=m["taal"], landnaam=m["land"])
        if resultaat is None:
            print(f"Koopvragen genereren mislukt voor {webshop_url}")
            return
        nieuw = db.bewaar_koopvragen(webshop_url, resultaat["omschrijving"],
                                     resultaat["vragen"], vervang=vervang,
                                     winkelnaam=resultaat.get("naam"))
        print(f"Koopvragen klaar voor {webshop_url}: {len(resultaat['vragen'])} vragen, {nieuw} nieuw opgeslagen.")
        _vul_koopvragen_aan(webshop_url)
    except Exception as e:
        print(f"Koopvragen genereren mislukt voor {webshop_url}: {e}")


def _vul_koopvragen_aan(webshop_url):
    """Vult de vragenset weer aan tot het doel per intentie.

    Nodig na ontdubbelen en na een generatie die te weinig vragen opleverde.
    Zonder dit krimpt de set bij elke klik en hou je uiteindelijk twee
    winkelvragen over."""
    try:
        actief = [dict(v) for v in db.get_koopvragen(webshop_url, alleen_actief=True)]
        tekort = koopvragen.tel_tekort(actief)
        if not tekort:
            return
        profiel = db.get_winkelprofiel(webshop_url)
        omschrijving = profiel.get("omschrijving") if profiel else ""
        alles = db.get_koopvragen(webshop_url, alleen_actief=False)
        m = _markt_van(webshop_url)
        extra = koopvragen.vul_vragen_aan(
            webshop_url, omschrijving, tekort, [v["vraag"] for v in alles],
            taal=m["taal"], landnaam=m["land"]
        )
        if extra:
            db.bewaar_koopvragen(webshop_url, omschrijving, extra, vervang=False)
        print(f"Aangevuld voor {webshop_url}: tekort {tekort}, {len(extra)} vragen erbij.")
    except Exception as e:
        print(f"Aanvullen mislukt voor {webshop_url}: {e}")


@app.route("/admin/koopvragen")
def admin_koopvragen():
    """Nog niet zichtbaar voor klanten. Hiermee kan je per webshop de
    koopvragen laten genereren, beoordelen en ontdubbelen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    if not webshop_url:
        return render_template("admin_koopvragen.html", webshop_url="geen webshop opgegeven",
                                status="leeg", vragen=[], groepen={}, dubbelen=0, sleutel=admin_key)

    bestaand = db.get_koopvragen(webshop_url)
    opnieuw = request.args.get("opnieuw") == "ja"

    if not bestaand or opnieuw:
        threading.Thread(target=_genereer_koopvragen_achtergrond,
                         args=(webshop_url, opnieuw), daemon=True).start()
        return render_template("admin_koopvragen.html", webshop_url=webshop_url,
                                status="bezig", vragen=[], groepen={}, dubbelen=0, sleutel=admin_key)

    vragen = [{"vraag": v["vraag"], "intentie": v["intentie"]} for v in bestaand]

    # Alleen aanvullen, zonder eerst dubbelingen te zoeken.
    if request.args.get("aanvul") == "ja":
        threading.Thread(target=_vul_koopvragen_aan, args=(webshop_url,), daemon=True).start()
        return redirect(f"/admin/koopvragen?key={admin_key}&url={webshop_url}&aangevuld=ja")

    # Zoeken naar dubbelingen kost een AI-aanroep, dus dat doen we alleen als
    # erom gevraagd wordt. Deed hij dat bij elke keer verversen, dan betaal je
    # voor elke pagina die je opent.
    zoeken = request.args.get("dubbel") == "ja" or request.args.get("ontdubbel") == "ja"
    dubbelingen = koopvragen.vind_dubbele_vragen(vragen, webshop_url=webshop_url) if zoeken else []
    if request.args.get("ontdubbel") == "ja" and dubbelingen:
        for d in dubbelingen:
            db.zet_vraag_uit(webshop_url, d["weglaten"])
        threading.Thread(target=_vul_koopvragen_aan, args=(webshop_url,), daemon=True).start()
        return redirect(f"/admin/koopvragen?key={admin_key}&url={webshop_url}&aangevuld=ja")

    weg_te_laten = {d["weglaten"]: d["houden"] for d in dubbelingen}
    groepen = {}
    for v in vragen:
        v = dict(v)
        lijkt_op = weg_te_laten.get(v["vraag"])
        v["dubbel"] = (lijkt_op[:40] + "...") if lijkt_op else None
        groepen.setdefault(v["intentie"] or "overig", []).append(v)

    profiel = db.get_winkelprofiel(webshop_url)
    return render_template(
        "admin_koopvragen.html",
        webshop_url=webshop_url,
        status="klaar",
        omschrijving=profiel.get("omschrijving") if profiel else "",
        vragen=vragen,
        groepen=groepen,
        dubbelen=len(dubbelingen),
        te_veel=len(vragen) > metingen.VRAGEN_PER_RONDE,
        per_ronde=metingen.VRAGEN_PER_RONDE,
        aanvullen_bezig=request.args.get("aangevuld") == "ja",
        gezocht=zoeken,
        tekort=koopvragen.tel_tekort([dict(v) for v in bestaand]),
        sleutel=admin_key,
    )


_metingen_bezig = set()
_metingen_slot = threading.Lock()


def _meet_achtergrond(webshop_url):
    """Een meetronde duurt al gauw een paar minuten, dus die laten we niet op
    het verzoek wachten.

    De set eromheen voorkomt dat er twee rondes tegelijk lopen voor dezelfde
    webshop. Zonder die controle start elke keer verversen een nieuwe ronde en
    betaal je twee of drie keer voor dezelfde meting."""
    try:
        metingen.meet_webshop(webshop_url)
    except Exception as e:
        print(f"Meting mislukt voor {webshop_url}: {e}")
    finally:
        with _metingen_slot:
            _metingen_bezig.discard(webshop_url)


def _start_meting(webshop_url):
    """Geeft terug of er een nieuwe ronde gestart is."""
    with _metingen_slot:
        if webshop_url in _metingen_bezig:
            return False
        _metingen_bezig.add(webshop_url)
    threading.Thread(target=_meet_achtergrond, args=(webshop_url,), daemon=True).start()
    return True


@app.route("/admin/metingen")
def admin_metingen():
    """Fase 5 stap 3. Laat zien wat de AI-modellen antwoordden op de
    koopvragen van een webshop. Nog niet zichtbaar voor klanten: het
    beoordelen van die antwoorden is stap 4."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    aanbieders = metingen.beschikbare_aanbieders()

    if not webshop_url:
        return render_template(
            "admin_metingen.html", webshop_url="", sleutel=admin_key,
            aanbieders=aanbieders, metingen_aan=metingen.METINGEN_AAN,
            webshops=db.get_webshops_met_koopvragen(),
            rondes=[], antwoorden=[], meting_id=None, gestart=False,
        )

    if request.args.get("start") == "ja":
        # Meteen doorsturen naar de pagina zonder start=ja. Anders start elke
        # keer verversen een nieuwe meetronde.
        _start_meting(webshop_url)
        return redirect(f"/admin/metingen?key={admin_key}&url={webshop_url}&gestart=ja")

    net_gestart = request.args.get("gestart") == "ja"
    meting_id = request.args.get("meting") or None
    antwoorden = [dict(a) for a in db.get_ai_antwoorden(webshop_url, meting_id)]
    for a in antwoorden:
        a["naam_gevonden"] = metingen.ruwe_naamtreffer(a.get("antwoord"), webshop_url)

    return render_template(
        "admin_metingen.html",
        webshop_url=webshop_url,
        sleutel=admin_key,
        aanbieders=aanbieders,
        metingen_aan=metingen.METINGEN_AAN,
        webshops=db.get_webshops_met_koopvragen(),
        rondes=db.get_metingen(webshop_url),
        antwoorden=antwoorden,
        meting_id=meting_id,
        gestart=net_gestart,
    )


_beoordelen_bezig = set()


def _beoordeel_achtergrond(webshop_url, meting_id, winkelnaam):
    try:
        beoordeling.beoordeel_ronde(webshop_url, meting_id, winkelnaam)
    except Exception as e:
        print(f"Beoordelen mislukt voor {webshop_url}: {e}")
    finally:
        with _metingen_slot:
            _beoordelen_bezig.discard(webshop_url)


def _meet_en_beoordeel(webshop_url, email=None, klant_token=None, base_url=None,
                       stap=None, max_vragen=None, controleer=True, bronnen_aan=True):
    """De hele keten van fase 5 achter elkaar: meten, beoordelen, controleren en
    zo nodig waarschuwen.

    Draait wekelijks na de gewone scan. De volgorde ligt vast omdat elke stap op
    de vorige leunt: zonder antwoorden valt er niets te beoordelen, en zonder
    beoordeling zijn er geen uitspraken om te controleren.

    Elke stap in een eigen try, want een storing bij een AI-aanbieder mag nooit
    de rest tegenhouden.

    Met stap= kan een aanroeper meelezen waar de keten is. Die keten duurt
    minuten, dus zonder terugmelding lijkt een demopagina stil te staan."""
    def melden(tekst):
        if stap:
            try:
                stap(tekst)
            except Exception:
                pass

    # Zonder koopvragen valt er niets te meten. Bij een nieuwe abonnee bestaan
    # die nog niet, dus die maken we hier alsnog aan. Anders zou een klant die
    # net 39 euro betaald heeft een lege pagina zien terwijl op de site staat
    # dat we elke week dertig vragen stellen.
    if not db.get_koopvragen(webshop_url, alleen_actief=True):
        print(f"Nog geen koopvragen voor {webshop_url}, die maken we eerst.")
        melden("koopvragen maken")
        _genereer_koopvragen_achtergrond(webshop_url, vervang=False)

    winkelnaam = _winkelnaam(webshop_url)

    melden("vragen stellen aan AI")
    samenvatting = metingen.meet_webshop(webshop_url, max_vragen=max_vragen) or {}
    meting_id = samenvatting.get("meting_id")
    if not meting_id:
        # BEWUST GEEN TERUGVAL op db.laatste_meting_id(). Die stond hier, en
        # dan ging de hele keten bij een mislukte meting vrolijk verder op de
        # ronde van vorige week: opnieuw beoordelen (kost geld), bronnen
        # zoeken bij oude antwoorden, en een klantpagina met cijfers van zeven
        # dagen oud onder de datum van vandaag. Liever niets dan oud nieuws
        # dat zich voordoet als vers.
        reden = samenvatting.get("reden") or "onbekende reden"
        melden(f"mislukt: er is niets gemeten ({reden})")
        print(f"Meting overgeslagen voor {webshop_url}: {reden}")
        # Gaat dit mis bij een BETALENDE klant, dan moet jij dat weten. Hij las
        # net in zijn welkomstmail "reken op ongeveer een kwartier", kijkt een
        # kwartier later, en ziet "er is nog niet gemeten". Voor 39 euro per
        # maand. Zonder dit bericht kwam dat alleen in de logs van Render.
        #
        # Alleen bij een klant, niet bij een demo of de benadering: die hebben
        # hun eigen logboek en zouden dit tot tientallen berichten per dag maken.
        if klant_token:
            _meld_aan_beheer(
                "Meting mislukt bij een klant",
                f"De meting voor {webshop_url} ({email}) leverde niets op: {reden}. "
                f"Deze klant ziet op zijn pagina 'er is nog niet gemeten'. Kijk of de "
                f"sleutels van de AI-aanbieders werken en of de kostenrem niet dicht "
                f"staat.")
        return

    # Is de ronde halverwege gestopt, dan is dat geen normale ronde. De klant
    # mag geen "genoemd bij 1 van de 3 vragen" te zien krijgen alsof dat een
    # volledige week is.
    #
    # Hier stond alleen een print. Dat betekende dat precies het scherm waar
    # deze regels voor waarschuwen gewoon getoond werd: de dagpot is gedeeld
    # met alle klanten, dus op een drukke dag kon een winkel na drie van de
    # dertig vragen stoppen en las zijn pagina "genoemd bij 1 van de 3". Dat is
    # geen klein cijfer, dat is een verkeerd cijfer, en het staat op de pagina
    # waar hij voor betaalt.
    #
    # De grens van 75 procent is dezelfde die waarschuwing.py gebruikt om twee
    # rondes vergelijkbaar te noemen. Onder die grens beoordelen wij niets en
    # tonen wij niets: liever geen cijfer dan een verkeerd cijfer.
    if samenvatting.get("gestopt_door_rem"):
        gedaan = samenvatting.get("gelukt") or 0
        bedoeld = samenvatting.get("gesteld") or gedaan
        deel = (gedaan / bedoeld) if bedoeld else 0
        print(f"LET OP: de meetronde voor {webshop_url} is halverwege gestopt na "
              f"{gedaan} van {bedoeld} vragen: {samenvatting.get('reden')}")
        if deel < 0.75:
            melden("mislukt: er is niets gemeten "
                   f"(de ronde stopte na {gedaan} van {bedoeld} vragen)")
            return

    try:
        melden("antwoorden beoordelen")
        beoordeling.beoordeel_ronde(webshop_url, meting_id, winkelnaam)
    except Exception as e:
        print(f"Beoordelen mislukt voor {webshop_url}: {e}")

    # Bij een benchmark slaan we de uitspraakcontrole over. Die kost een extra
    # AI-aanroep per winkel en levert een oordeel op over die ene winkel, terwijl
    # een benchmark alleen naar het patroon over alle winkels kijkt. Over zestig
    # winkels scheelt dat zo een tientje voor iets wat je toch niet gebruikt.
    controle_samenvatting = None
    if controleer:
        melden("uitspraken controleren")
        controle_samenvatting = _controleer_uitspraken(webshop_url, meting_id, winkelnaam)

    # Fase 5 punt 14. Staat bewust ná het beoordelen, want die bepaalt bij
    # welke vragen we ontbreken en welke concurrenten er wel opdoken. Zonder
    # dat weet de bronanalyse niet waar hij moet kijken.
    #
    # Ook bewust in een eigen try en overslaanbaar: valt de zoekmachine uit of
    # is er geen sleutel, dan mist er die week een blok op de klantpagina en
    # draait de rest gewoon door. Dat is beter dan een meetronde die klapt op
    # een dienst die niets met de meting zelf te maken heeft.
    if bronnen_aan:
        melden("externe bronnen zoeken")
        _zoek_bronnen(webshop_url, meting_id, winkelnaam, melden)

    # Fase 5 punt 15. Het plan samenstellen en de kant-en-klare oplossingen
    # laten schrijven, zodat ze klaarstaan als de klant zijn pagina opent.
    # Hier en niet daar: een pagina die staat te wachten op een AI is
    # onbruikbaar, en verversen zou elke keer opnieuw geld kosten.
    try:
        melden("actieplan klaarzetten")
        _maak_taakoplossingen(webshop_url, _klantgegevens(webshop_url)["actieplan"], melden)
    except Exception as e:
        print(f"Taakoplossingen klaarzetten mislukt voor {webshop_url}: {e}")

    # Alleen mailen als er iets te melden valt. Een wekelijks bericht dat er
    # niets veranderd is, leert een klant om je mail weg te klikken.
    try:
        beweging = waarschuwing.vergelijk(
            [dict(b) for b in db.get_beoordelingen_rondes(webshop_url, rondes=2)], winkelnaam)
        tekst = waarschuwing.bericht(webshop_url, beweging, controle_samenvatting)
        if tekst and email:
            monitoring_url = f"{base_url}/monitoring/{klant_token}" if (base_url and klant_token) else None
            emailing.send_vermeldingen_update(email, webshop_url, tekst, monitoring_url,
                                              taal=_mailtaal(webshop_url))
    except Exception as e:
        print(f"Waarschuwing versturen mislukt voor {webshop_url}: {e}")


# Wat de laatste bronanalyse per winkel deed. Alleen in het geheugen, dus na
# een herstart van Render is dit leeg. Dat is prima: het is bedoeld om te zien
# waarom een poging niets opleverde, niet om te bewaren. De echte uitkomsten
# staan in de database.
_bronnen_status = {}


def _zet_bronnen_status(webshop_url, tekst, klaar=False):
    _bronnen_status[webshop_url] = {"tekst": tekst, "klaar": klaar}
    print(f"Bronnen {webshop_url}: {tekst}")


# Voor elke taak laten we een tekst schrijven, ook voor de onjuistheden.
#
# Dat was eerst niet zo, en dat was fout. Juist bij "AI zegt dat je 30 dagen
# retour geeft terwijl het er 100 zijn" wil een winkelier niet horen dat hij
# het moet rechtzetten, maar de zin lezen die hij op zijn site kan plakken.
# Die taak heeft de kant-en-klare tekst het hardst nodig, niet het minst.
GEEN_OPLOSSING_NODIG = set()


def _laatste_uitvoering(webshop_url):
    """De meest recente opdracht "wij doen het" van deze winkel, of None.

    Bewust de nieuwste en niet de eerste: bestelt iemand het een jaar later nog
    eens, dan hoort de klantpagina die tweede opdracht te tonen en niet de
    afgeronde van vorig jaar. Afgebroken opdrachten laten we weg, want daar
    hoeft een klant niets meer van te zien."""
    try:
        for u in db.get_uitvoeringen(webshop_url):
            if u.get("stand") != "afgebroken":
                return u
    except Exception as e:
        print(f"Uitvoering ophalen mislukt voor {webshop_url}: {e}")
    return None


def _maak_taakoplossingen(webshop_url, plan, melden=None):
    """Laat voor elke taak in het plan de kant-en-klare oplossing schrijven,
    en bewaart die.

    Gebeurt hier, in de wekelijkse keten, en niet bij het openen van de
    klantpagina. Twee redenen: een pagina die een halve minuut staat te denken
    is onbruikbaar, en een klant die vijf keer ververst zou vijf keer betalen.

    Al geschreven oplossingen worden overgeslagen. Een taak die blijft staan
    krijgt dus dezelfde tekst als vorige week, en dat hoort ook: hetzelfde
    probleem met een andere formulering laat het lijken alsof er iets veranderd
    is."""
    uitkomsten = []
    if not plan or not plan.get("acties"):
        return uitkomsten

    # Op welk winkelplatform deze shop draait, zodat de tekst bij "waar zet je
    # dit neer" de menunamen van dat platform gebruikt. Weten we het niet, dan
    # blijft het None en vraagt de prompt om twee routes. Nooit gokken: een
    # route in Shopify voorschrijven aan iemand met WooCommerce laat het hele
    # product onbetrouwbaar lijken.
    platform = None
    try:
        profiel = db.get_winkelprofiel(webshop_url) or {}
        platform = profiel.get("platform")
    except Exception as e:
        print(f"Platform ophalen mislukt voor {webshop_url}: {e}")

    bestaand = db.get_taakoplossingen(webshop_url)
    for actie in plan["acties"]:
        taak_id = actie.get("id")
        if not taak_id or taak_id in GEEN_OPLOSSING_NODIG:
            continue
        if taak_id in bestaand:
            uitkomsten.append({"titel": actie["titel"], "gelukt": True, "fout": None,
                               "was_er_al": True})
            continue
        if melden:
            try:
                melden(f"oplossing schrijven: {actie['titel'][:40]}")
            except Exception:
                pass
        # In de taal van de winkel. De tekst die hieruit komt plakt de eigenaar
        # letterlijk op zijn eigen website, dus een Nederlandse zin op een
        # Amerikaanse winkel is niet onhandig maar onbruikbaar.
        m = _markt_van(webshop_url)
        uitkomst = ai_content.genereer_taakoplossing(
            webshop_url, taak_id, actie["titel"], actie["hoe"],
            platform=platform,
            taal="nl" if m["is_nederlands"] else "en") or {}
        if uitkomst.get("gelukt"):
            db.bewaar_taakoplossing(webshop_url, taak_id, uitkomst["titel"],
                                    uitkomst["oplossing"], uitkomst["waar"],
                                    taal="nl" if m["is_nederlands"] else "en")
            uitkomsten.append({"titel": actie["titel"], "gelukt": True, "fout": None,
                               "was_er_al": False})
        else:
            uitkomsten.append({"titel": actie["titel"], "gelukt": False,
                               "fout": uitkomst.get("fout") or "onbekende reden",
                               "was_er_al": False})
    return uitkomsten


def _zoek_bronnen(webshop_url, meting_id=None, winkelnaam=None, melden=None):
    """Fase 5 punt 14. Zoekt de externe pagina's op waar de concurrenten wel
    staan en de klant niet.

    Leunt op het klantbeeld van deze ronde, dus op precies dezelfde cijfers als
    de klant op zijn pagina ziet. Zou dit zijn eigen selectie maken, dan kan de
    bronanalyse over andere vragen gaan dan de meting erboven, en dan staan er
    twee waarheden op een pagina."""
    try:
        if not bronnen.beschikbaar():
            _zet_bronnen_status(webshop_url, bronnen.waarom_niet(), klaar=True)
            return None

        # BEWUST de nieuwste BEOORDEELDE ronde en niet de nieuwste gemeten
        # ronde. Anders kan de bronanalyse over een andere ronde gaan dan de
        # cijfers die de klant erboven ziet, en dan staan er twee waarheden op
        # een pagina. De klantpagina kiest via get_beoordelingen() dezelfde.
        meting_id = meting_id or db.laatste_beoordeelde_meting_id(webshop_url)
        if not meting_id:
            gemeten = db.laatste_meting_id(webshop_url)
            if gemeten:
                _zet_bronnen_status(
                    webshop_url,
                    f"Er is wel gemeten (ronde {gemeten[:8]}) maar nog niets beoordeeld. "
                    f"Zonder beoordeling weten we niet bij welke vragen je ontbreekt en "
                    f"welke concurrenten er opdoken. Beoordeel die ronde eerst.",
                    klaar=True)
            else:
                _zet_bronnen_status(
                    webshop_url,
                    "Er is nog geen enkele meetronde voor deze winkel. Meet eerst.",
                    klaar=True)
            return None

        beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)]
        if not beoordelingen:
            _zet_bronnen_status(
                webshop_url,
                f"Ronde {meting_id[:8]} heeft geen beoordelingen. Beoordeel die ronde eerst.",
                klaar=True)
            return None

        klantbeeld = beoordeling.klantbeeld(webshop_url, beoordelingen)
        vragen = bronnen.kies_vragen(klantbeeld)
        concurrenten = bronnen.kies_concurrenten(klantbeeld)
        if not vragen:
            _zet_bronnen_status(
                webshop_url,
                "Geen vragen om na te trekken: deze winkel wordt bij elke meetellende vraag "
                "genoemd en aanbevolen. Dan valt er hier niets te halen.", klaar=True)
            return None
        if not concurrenten:
            _zet_bronnen_status(
                webshop_url,
                "Geen concurrenten gevonden in de beoordelingen van deze ronde. "
                "De bronanalyse zoekt naar winkels die AI wel noemt, en die zijn er niet.",
                klaar=True)
            return None

        _zet_bronnen_status(webshop_url,
                            f"Bezig: {len(vragen)} vragen natrekken bij {len(concurrenten)} concurrenten.")

        # In het land van de winkel zoeken. Een winkel in Texas moet in
        # Amerikaanse zoekresultaten gezocht worden; zoeken we daar met de
        # Nederlandse instelling, dan vinden we pagina's waar hij nooit op zou
        # staan en klopt de hele bronanalyse niet.
        m = _markt_van(webshop_url)
        vindplaatsen = bronnen.analyseer(
            webshop_url, klantbeeld, winkelnaam=winkelnaam,
            meting_id=meting_id, melden=melden,
            land=m["zoek_land"], taal=m["zoek_taal"],
        )
        if vindplaatsen:
            # Eerst weg wat er van deze ronde stond, dan pas bewaren. Anders
            # stapelen de resultaten van elke poging op elkaar en blijf je
            # kijken naar vindplaatsen die met oudere, soepelere regels
            # binnengekomen zijn. Dan zie je nooit of een verbetering geholpen
            # heeft.
            weg = db.verwijder_bronvindplaatsen(webshop_url, meting_id)
            bewaard = db.bewaar_bronvindplaatsen(webshop_url, meting_id, vindplaatsen)
            _zet_bronnen_status(
                webshop_url,
                f"Klaar: {bewaard} vindplaatsen over {len(vragen)} vragen"
                + (f", {weg} oude regels vervangen." if weg else "."), klaar=True)
        else:
            _zet_bronnen_status(
                webshop_url,
                f"Klaar, maar niets gevonden. {len(vragen)} vragen gezocht en geen enkele "
                f"pagina bevatte onze winkel of een van de concurrenten. Test hieronder de "
                f"zoekmachine: geeft die ook niets terug, dan zit het probleem daar.",
                klaar=True)
        return bronnen.vat_samen(vindplaatsen, winkelnaam)
    except Exception as e:
        _zet_bronnen_status(webshop_url, f"Mislukt: {type(e).__name__}: {e}"[:400], klaar=True)
        return None


def _controleer_uitspraken(webshop_url, meting_id=None, winkelnaam=None):
    """Fase 5 stap 9. Legt de uitspraken van AI naast wat er op de site staat.

    Haalt de sitetekst vers op, want die staat bewust niet in de database: het
    zijn duizenden tekens die bij elke scan veranderen."""
    try:
        meting_id = meting_id or db.laatste_meting_id(webshop_url)
        if not meting_id:
            return None
        beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)]
        uitspraken = controle.verzamel_uitspraken(beoordelingen)
        if not uitspraken:
            return None
        sitetekst = scan_engine.haal_sitetekst(webshop_url, controle.MAX_SITETEKST)
        if not sitetekst:
            print(f"Controle overgeslagen voor {webshop_url}: site niet te lezen.")
            return None
        uitkomsten = controle.controleer(webshop_url, winkelnaam, uitspraken, sitetekst)
        db.bewaar_uitspraakcontroles(webshop_url, meting_id, uitkomsten)
        return controle.vat_samen(uitkomsten)
    except Exception as e:
        print(f"Uitspraken controleren mislukt voor {webshop_url}: {e}")
        return None


def _winkelnaam(webshop_url):
    """De naam zoals de winkel zichzelf noemt.

    Eerst het veld waar het model de naam apart in zet. Staat dat er niet
    (oudere winkels), dan de oude manier: de omschrijving splitsen op " is ".
    Beide gaan langs dezelfde controle."""
    profiel = db.get_winkelprofiel(webshop_url) or {}
    uit_veld = scan_engine.bruikbare_winkelnaam(profiel.get("winkelnaam"))
    if uit_veld:
        return uit_veld
    omschrijving = profiel.get("omschrijving") or ""
    if " is " in omschrijving:
        return scan_engine.bruikbare_winkelnaam(omschrijving.split(" is ")[0])
    return None


def _klantgegevens(webshop_url):
    """Alles wat zowel de klantpagina als de voorbeeldweergave nodig heeft.

    Op een plek, zodat een abonnee en de voorbeeldweergave nooit iets anders
    kunnen laten zien."""
    # De klant ziet de nieuwste ronde. Voor stijgen of dalen zijn er twee
    # nodig, en die haalt get_beoordelingen niet op.
    beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url)]
    twee_rondes = [dict(b) for b in db.get_beoordelingen_rondes(webshop_url, rondes=2)]
    vermeldingen = beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None
    winkelnaam = _winkelnaam(webshop_url)
    # Alles op deze pagina komt uit DEZELFDE ronde. Zonder dat zou je de
    # bronnen en de controles van vorige week naast de cijfers van deze week
    # kunnen zetten, en dan klopt het verhaal niet meer. Liever niets tonen dan
    # iets dat bij een andere meting hoort.
    #
    # Voor de uitspraakcontrole stond hier eerder geen ronde. Die pakte dan de
    # nieuwste ronde waarvoor toevallig controles bestonden. Mislukte de
    # controle deze week, dan zag de klant de cijfers van deze week met daaronder
    # de fouten van vorige week, en die kwamen als FEIT bovenaan zijn takenlijst,
    # citaat en al, terwijl AI dat deze week misschien niet meer zegt.
    ronde = db.laatste_beoordeelde_meting_id(webshop_url)
    controles = ([dict(c) for c in db.get_uitspraakcontroles(webshop_url, ronde)]
                 if ronde else [])
    vindplaatsen = ([dict(v) for v in db.get_bronvindplaatsen(webshop_url, ronde)]
                    if ronde else [])
    controle_samenvatting = controle.vat_samen(controles) if controles else None
    bronnen_samenvatting = bronnen.vat_samen(vindplaatsen, winkelnaam) if vindplaatsen else None

    # Fase 5 punt 15. Leunt op alles hierboven en op de verklaring uit de
    # scan, dus die halen we er hier bij. Bewust op deze ene plek berekend,
    # zodat de klantpagina en de voorbeeldweergave nooit een ander plan kunnen
    # tonen dan elkaar.
    checks = (db.get_rapporten_voor_webshop(webshop_url) or [{}])[0].get("checks") or []
    #
    # De taal van het advies volgt de markt van de winkel. Een Amerikaanse
    # winkel kreeg tot nu toe een Engels scherm met Nederlands advies eronder.
    # Weten we de markt niet, dan geeft _markt_van Nederlands terug, dus voor
    # bestaande klanten verandert er niets.
    m = _markt_van(webshop_url)
    plantaal = "nl" if m["is_nederlands"] else "en"
    plan = actieplan.maak_actieplan(
        verklaring=verklaring.maak_verklaring(checks, vermeldingen, taal=plantaal),
        klantbeeld=vermeldingen,
        bronnen=bronnen_samenvatting,
        controle=controle_samenvatting,
        winkelnaam=winkelnaam,
        taal=plantaal,
    )

    # De bewaarde oplossingen aan de taken hangen. Alleen lezen, nooit
    # schrijven: dat gebeurt in de wekelijkse keten.
    if plan and plan.get("acties"):
        # Alleen oplossingen in de taal die deze winkel ook op het scherm ziet.
        # Staat er een Nederlandse tekst van vorige week onder een Engels kopje,
        # dan lijkt het alsof er iets kapot is. Liever niets, want de volgende
        # ronde maakt hem alsnog, dan wel in de goede taal.
        opgeslagen = db.get_taakoplossingen(webshop_url, taal=plantaal)
        for actie in plan["acties"]:
            bewaard = opgeslagen.get(actie.get("id"))
            if bewaard:
                actie["oplossing"] = bewaard.get("oplossing")
                actie["waar"] = bewaard.get("waar")

    return {
        "vermeldingen": vermeldingen,
        "controle": controle_samenvatting,
        "beweging": waarschuwing.vergelijk(twee_rondes, winkelnaam),
        "bronnen": bronnen_samenvatting,
        "actieplan": plan,
    }


_demo_status = {}
_demo_wachtrij = []
_demo_slot = threading.Lock()
_demo_werker_draait = [False]


# Na hoeveel mislukte metingen wij een winkel laten vallen. Een site die drie
# keer niet te bereiken is, is er gewoon niet, en elke volgende poging kost een
# plek in de rij en een stukje dagpot.
MISLUKT_GENOEG = int(os.environ.get("MISLUKT_GENOEG", "3"))

# Vanaf hoeveel wachtende metingen een ronde er geen nieuwe meer bij zet.
WACHTRIJ_VOL = int(os.environ.get("WACHTRIJ_VOL", "5"))

# Hoe lang een winkel op "meten" mag staan zonder dat er iets loopt, voordat wij
# hem opnieuw oppakken. Kort, want als de wachtrij leeg is en er loopt niets, is
# er niets om op te wachten.
HERVAT_NA_MINUTEN = int(os.environ.get("HERVAT_NA_MINUTEN", "20"))


def _metingen_bezig():
    """Hoeveel metingen er op dit moment echt lopen."""
    return len([1 for stand in _demo_status.values()
                if stand and stand != "klaar" and not stand.startswith("mislukt")])


def _hervat_onderbroken_metingen():
    """Pakt winkels op die op "meten" staan terwijl er niets meer loopt.

    Geeft terug hoeveel er opnieuw ingepland zijn."""
    if _demo_wachtrij or _metingen_bezig():
        return 0
    grens = datetime.now(benadering.KLOK) - timedelta(minutes=HERVAT_NA_MINUTEN)
    hervatten = []
    for winkel in db.get_benaderingen(stand="meten", limiet=WACHTRIJ_VOL):
        begonnen = winkel.get("meting_gestart_op")
        if begonnen is not None and begonnen.tzinfo is None and benadering.KLOK:
            begonnen = begonnen.replace(tzinfo=benadering.KLOK)
        if begonnen is not None and begonnen > grens:
            continue
        hervatten.append(winkel["webshop_url"])
    if not hervatten:
        return 0
    benadering.markeer_in_meting(hervatten)
    _demo_inplannen(hervatten, benchmark_stand=True, vragen=BENADERING_VRAGEN,
                    opnieuw=False)
    print(f"Benadering, onderbroken metingen opnieuw opgepakt: {len(hervatten)}")
    return len(hervatten)


def _demo_werker():
    """Werkt de wachtrij een voor een af.

    Met opzet een enkele werker en geen thread per winkel. Twintig winkels
    tegelijk meten betekent twintig keer zoveel aanroepen per minuut, en dan
    krijg je van OpenAI en Google precies de 429's terug waar we eerder al last
    van hadden. Rustig achter elkaar duurt langer maar levert bruikbare
    metingen op, en dat is het enige wat telt."""
    while True:
        with _demo_slot:
            if not _demo_wachtrij:
                _demo_werker_draait[0] = False
                return
            regel = _demo_wachtrij.pop(0)
            url, benchmark_stand = regel[0], regel[1]
            vragen = regel[2] if len(regel) > 2 else None
        _demo_draaien(url, benchmark_stand, vragen=vragen)
        _meting_afgerond_melden(url)


def _meting_afgerond_melden(webshop_url):
    """Schrijft de uitkomst van een meting terug naar de benaderlijst.

    Dit ontbrak, en daardoor was "er wordt wel gemeten maar er komt niets af"
    van buitenaf niet te verklaren. De reden van een mislukking stond alleen in
    het geheugen van de server en in de uitdraai van Render. Elke ronde meldde
    keurig "ingepland: 5, doorgezet naar gemeten: 0" en daar hield het op.

    Een mislukte meting gaat meteen terug naar "adres" met de reden erbij, in
    plaats van zes uur op "meten" te blijven staan. Er is niets om op te wachten:
    hij is al mislukt."""
    stand = _demo_status.get(webshop_url) or ""
    try:
        # Zoeken over de HELE lijst, niet alleen bij wat op "meten" staat.
        #
        # Dat was een gat waar geld doorheen liep. Werd een winkel tijdens zijn
        # meting door de opruimronde teruggezet op "adres", dan stond hij bij
        # het afronden niet meer op "meten", vond deze functie hem niet, en gaf
        # hij op. De mislukking werd dus nooit geteld en de winkel kwam de
        # volgende ronde gewoon weer aan de beurt. Zo kon dezelfde onbereikbare
        # site acht keer op een dag geprobeerd worden.
        kaal = scan_engine.normalize_url(webshop_url)
        rij = None
        for r in db.get_benaderingen(alleen_niet_afgemeld=False):
            if scan_engine.normalize_url(r["webshop_url"]) == kaal:
                rij = r
                break
        if rij is None:
            return  # geen winkel van de benadering, dus niets te melden
        if (rij.get("stand") or "") == "afgevallen":
            # Al opgegeven. Niets meer doen, en zeker niet terugzetten op
            # "adres", want dan begint het hele rondje opnieuw.
            return
        if stand.startswith("mislukt"):
            # Hoe vaak deze winkel al mislukt is. Zonder dit blijft een winkel
            # die gewoon niet bestaat elk uur opnieuw aan de beurt komen: in het
            # logboek van 11 september stond woefwinkel.be acht keer op een dag,
            # steeds met "we konden deze website niet bereiken". Elke poging
            # bezet een plek in de rij van winkels die het wel doen.
            #
            # Dit telde eerst uit het foutenlogboek, en dat bewaart maar tien
            # regels. Bij vijftien metingen per dag is de vorige poging daar
            # allang uit gerold, begint het tellen weer bij nul, en valt een
            # winkel dus nooit af. Daarom nu een eigen teller die blijft staan.
            pogingen = benadering.tel_meetpoging(rij["webshop_url"])
            if pogingen >= MISLUKT_GENOEG:
                db.zet_benadering(
                    rij["webshop_url"], stand="afgevallen",
                    notitie=f"Na {pogingen} pogingen niet te meten: {stand[:300]}")
                print(f"Benadering, {webshop_url} afgevallen na {pogingen} pogingen.")
            else:
                db.zet_benadering(rij["webshop_url"], stand="adres", notitie=stand[:400])
            benadering.onthoud_meetfout(rij["webshop_url"], stand)
            print(f"Benadering, meting mislukt voor {webshop_url}: {stand[:160]}")
        elif stand == "klaar":
            db.zet_benadering(rij["webshop_url"], stand="gemeten", notitie="")
    except Exception as e:
        print(f"Uitkomst van de meting bewaren mislukt voor {webshop_url}: {e}")


def _demo_inplannen(urls, benchmark_stand=False, opnieuw=False, vragen=None):
    """Zet winkels in de wachtrij en start de werker als die stilstaat.

    Geeft terug hoeveel er echt bijgekomen zijn. Een winkel die al in de rij
    staat, al loopt, of al een afgeronde meting heeft, komt er niet nog een keer
    bij: dan zou je twee keer betalen voor dezelfde meting.

    Die laatste controle gaat tegen de database aan en niet tegen het geheugen,
    en dat is precies het punt. Bij een benchmark van zestig winkels loopt de
    wachtrij uren. Herstart Render tussendoor, dan is de wachtrij weg terwijl de
    afgeronde metingen gewoon bewaard zijn. Zonder deze controle zou je de lijst
    opnieuw plakken en alles nog een keer betalen."""
    al_gedaan = set()
    if not opnieuw:
        try:
            al_gedaan = {w["webshop_url"] for w in db.get_demo_webshops()
                         if (w.get("vragen") or 0) >= MINIMUM_VRAGEN_VOOR_POST}
        except Exception as e:
            print(f"Kon niet nakijken welke demo's al gedaan zijn: {e}")

    # De laatste sluis: wie opgegeven is, komt er niet meer in.
    #
    # Dit staat hier expres dubbel. Er zijn drie wegen naar de wachtrij (de
    # gewone ronde, het hervatten van onderbroken metingen, en de beheerpagina)
    # en het is een kwestie van tijd voor er een vierde bij komt. Een winkel die
    # afgevallen is hoort via geen enkele weg nog geld te kosten.
    opgegeven = set()
    try:
        opgegeven = {scan_engine.normalize_url(w["webshop_url"])
                     for w in db.get_benaderingen(stand="afgevallen",
                                                  alleen_niet_afgemeld=False)}
    except Exception as e:
        print(f"Kon de afgevallen winkels niet ophalen: {e}")

    toegevoegd = 0
    overgeslagen = 0
    with _demo_slot:
        for url in urls:
            if scan_engine.normalize_url(url) in opgegeven:
                overgeslagen += 1
                print(f"Meting overgeslagen: {url} is al afgevallen.")
                continue
            huidig = _demo_status.get(url, "")
            bezig = huidig and huidig != "klaar" and not huidig.startswith("mislukt")
            if url in al_gedaan:
                overgeslagen += 1
                _demo_status.setdefault(url, "klaar")
                continue
            if any(w[0] == url for w in _demo_wachtrij) or bezig:
                continue
            _demo_wachtrij.append((url, benchmark_stand, vragen))
            _demo_status[url] = "in de wachtrij"
            toegevoegd += 1
        starten = toegevoegd and not _demo_werker_draait[0]
        if starten:
            _demo_werker_draait[0] = True
    if starten:
        threading.Thread(target=_demo_werker, daemon=True).start()
    if overgeslagen:
        print(f"{overgeslagen} winkel(s) overgeslagen, die waren al gemeten.")
    return toegevoegd


BENCHMARK_VRAGEN = int(os.environ.get("BENCHMARK_VRAGEN", "5"))


def _demo_draaien(webshop_url, benchmark_stand=False, vragen=None):
    """De hele keten voor een winkel die geen klant is, in één keer.

    Bewust dezelfde route als bij een echte klant: eerst de gewone scan, dan
    koopvragen, meten, beoordelen en controleren. Zou de demo een eigen kortere
    weg nemen, dan laat je iets zien wat een klant nooit krijgt.

    Er gaat geen mail uit. _meet_en_beoordeel verstuurt alleen als er een
    e-mailadres meegegeven wordt, en dat doen we hier niet. Dat is de reden dat
    deze functie geen e-mailadres kent: dan kan het ook niet per ongeluk.
    """
    try:
        _demo_status[webshop_url] = "site scannen"
        resultaat = run_scan(webshop_url)
        if "error" in resultaat:
            _demo_status[webshop_url] = f"mislukt: {resultaat['error'][:120]}"
            return

        # Als demo bewaren, niet als scan of monitoring. Daaraan herkennen we
        # later welke winkels demo's zijn, en het houdt ze buiten de cijfers
        # over echte klanten.
        # De uitkomst NAKIJKEN. Dit ging mis en het bleef maandenlang onzichtbaar:
        # de kolom email stond op NOT NULL terwijl een demo geen klant heeft, dus
        # elke poging mislukte. Er werd wel gemeten en betaald, maar het rapport
        # werd nooit bewaard. De benchmarkpagina bleef leeg en niemand kon zien
        # waarom.
        if not db.save_report("demo", resultaat["url"], None,
                              resultaat.get("score", 0),
                              resultaat.get("checks", [])):
            _demo_status[webshop_url] = ("mislukt: de meting is gelukt maar het rapport "
                                         "kon niet bewaard worden")
            return
        db.zet_platform(resultaat["url"], resultaat.get("platform"))

        _meet_en_beoordeel(
            resultaat["url"],
            stap=lambda t: _demo_status.__setitem__(webshop_url, t),
            max_vragen=vragen or (BENCHMARK_VRAGEN if benchmark_stand else None),
            controleer=not benchmark_stand,
            # In de benchmarkstand ook de bronanalyse overslaan. Die kost per
            # winkel een paar zoekopdrachten en tientallen paginabezoeken, en
            # een benchmark kijkt alleen naar het patroon over alle winkels
            # samen. Over zestig winkels scheelt dat uren wachttijd voor iets
            # wat in de optelling niet gebruikt wordt.
            bronnen_aan=not benchmark_stand,
        )
        _demo_status[webshop_url] = "klaar"
    except Exception as e:
        print(f"Demo mislukt voor {webshop_url}: {e}")
        _demo_status[webshop_url] = f"mislukt: {str(e)[:120]}"


@app.route("/admin/demo", methods=["GET", "POST"])
def admin_demo():
    """Demo-uitkomsten: de volledige meting voor een winkel die geen klant is.

    Bedoeld om in een gesprek te laten zien wat iemand krijgt, in plaats van
    het uit te leggen. Kost ongeveer een euro per winkel, dus het starten
    gebeurt alleen op een knop en nooit vanzelf bij het openen van de pagina."""
    admin_key = os.environ.get("ADMIN_KEY")
    # Deze pagina kent ook een sleutel in het FORMULIER, want de knoppen sturen
    # hem mee. Die manier blijft werken; voor de rest gaat het net als bij de
    # andere beheerpagina's via het inlogscherm.
    if request.method == "POST" and _sleutel_klopt(request.form.get("key"), admin_key):
        session.permanent = True
        session["beheer"] = True
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    # Meerdere winkels tegelijk mag: gescheiden door een nieuwe regel, een komma
    # of een spatie. Dat is nodig voor een benchmark over tientallen winkels,
    # die je niet een voor een wil intypen.
    ruw = (request.form.get("url") if request.method == "POST" else None) or request.args.get("url") or ""
    urls = [scan_engine.normalize_url(u.strip())
            for u in re.split(r"[\s,;]+", ruw) if u.strip()]

    if urls and (request.args.get("start") == "ja" or request.form.get("start") == "ja"):
        benchmark_stand = (request.form.get("benchmark") == "ja"
                           or request.args.get("benchmark") == "ja")
        # De "opnieuw"-link naast een winkel moet wel opnieuw meten. Een lijst
        # plakken niet: dan wil je alleen de winkels die nog niet gedaan zijn.
        opnieuw = request.args.get("opnieuw") == "ja"
        _demo_inplannen(urls, benchmark_stand, opnieuw)
        # Terug zonder start=ja, anders begint elke keer verversen opnieuw.
        return redirect(f"/admin/demo?key={admin_key}")

    winkels = db.get_demo_webshops()
    bekend = {w["webshop_url"] for w in winkels}
    # Winkels die net gestart zijn staan nog niet in de database, maar moeten
    # wel zichtbaar zijn, anders lijkt de knop niets gedaan te hebben.
    for url, status in _demo_status.items():
        if url not in bekend:
            winkels.append({"webshop_url": url, "laatste": None, "score": None, "vragen": 0})
    for w in winkels:
        w["status"] = _demo_status.get(w["webshop_url"], "")

    return render_template("admin_demo.html", winkels=winkels, sleutel=admin_key,
                           wachtrij=len(_demo_wachtrij),
                           bezig=any(w["status"] and w["status"] not in ("klaar",)
                                     and not w["status"].startswith("mislukt") for w in winkels))


@app.route("/admin/onderzoeksmail", methods=["GET", "POST"])
def admin_onderzoeksmail():
    """De gemeten winkels, met per winkel de link naar zijn eigen uitkomst en
    een knop om hem die te mailen.

    Bewust één voor één en geen knop die alles ineens verstuurt. Zestig mails
    tegelijk naar mensen die er niet om gevraagd hebben is precies het verschil
    tussen een onderzoek en spam, en het is ook de snelste manier om je
    mailadres bij Brevo op een zwarte lijst te krijgen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        webshop_url = scan_engine.normalize_url((request.form.get("url") or "").strip())
        email = (request.form.get("email") or "").strip()
        actie = (request.form.get("actie") or "bewaren").strip()

        if not webshop_url:
            melding = "Er ontbrak een winkel."
        elif not email or not _EMAIL_VORM.match(email):
            melding = "Vul een geldig e-mailadres in."
        else:
            db.zet_contact_email(webshop_url, email)
            if actie != "versturen":
                melding = f"Adres bewaard bij {webshop_url}."
            else:
                # Dezelfde functie als de automatische ronde gebruikt. Eén mail,
                # één plek, geen twee versies die uit elkaar gaan lopen.
                land = ((db.get_benadering(webshop_url) or {}).get("land"))
                verstuurd, fout = _stuur_onderzoeksmail(webshop_url, email, land)
                if verstuurd:
                    db.markeer_onderzoeksmail(webshop_url)
                    db.zet_benadering(webshop_url, stand="gemaild", gemaild=True)
                    melding = f"Verstuurd naar {email}."
                else:
                    # BEWUST niet als verstuurd markeren. Anders sla je hem
                    # over bij de volgende ronde terwijl hij niets gehad
                    # heeft.
                    melding = (f"De mail is NIET verstuurd. {fout or ''} "
                               "Kijk zo nodig in de logs van Render.")

    regels = []
    for r in db.benchmark_regels():
        url = r.get("webshop_url")
        profiel = db.get_winkelprofiel(url) or {}
        lijstregel = db.get_benadering(url) or {}
        regels.append({
            "webshop_url": url,
            "genoemd": r.get("genoemd"),
            "vragen": r.get("vragen"),
            "score": r.get("score"),
            "email": profiel.get("contact_email") or lijstregel.get("email"),
            # Beide plekken, want de automatische ronde en de knop met de hand
            # schrijven allebei. Zie je hier een lege kolom terwijl er al post
            # uit is, dan druk je nog een keer en krijgt iemand twee mails.
            "gemaild_op": profiel.get("onderzoeksmail_op") or lijstregel.get("gemaild_op"),
            "afgemeld": bool(profiel.get("afgemeld_op") or lijstregel.get("afgemeld")),
            "token": profiel.get("benchmark_token"),
        })

    return render_template(
        "admin_onderzoeksmail.html",
        regels=regels,
        melding=melding,
        basis=get_base_url(),
        sleutel=admin_key,
    )


@app.route("/onderzoek")
def onderzoek():
    """De publieke uitkomst van de benchmark.

    Dit is geen verkooppagina maar een onderzoek. Er staan aantallen in en geen
    namen van winkels: het patroon gaat naar buiten, de losse winkel blijft
    binnen. Dat is ook precies waarom een gemeten winkelier hem durft te openen
    en waarom een vakblad hem durft over te nemen.

    De cijfers komen uit dezelfde optelling als de beheerpagina, zodat er nooit
    twee verschillende uitkomsten in omloop zijn."""
    regels = db.benchmark_regels()
    cijfers = benchmark.tel_op(regels)
    platforms = benchmark.per_platform(regels)
    return render_template(
        "onderzoek.html",
        c=cijfers,
        platforms=platforms,
        zinnen=benchmark.kernzinnen(cijfers, platforms),
        # Geen winkelnamen mee naar de sjabloon. Wat er niet is kan er ook niet
        # per ongeluk op komen te staan.
    )


@app.route("/uitkomst/<token>")
def uitkomst(token):
    """De eigen uitkomst van een winkel die wij in de benchmark gemeten hebben.

    Deze link gaat naar iemand die er niet om gevraagd heeft. Daarom drie
    dingen: het kenmerk is niet te raden, de pagina wordt niet geïndexeerd, en
    er staat bovenaan waarom hij deze mail kreeg en hoe hij eraf komt.

    Bewust geen actielijst met kant-en-klare teksten. Dat is het betaalde deel.
    Hier staat wat we gemeten hebben en hoe hij het doet ten opzichte van de
    rest, en dat is genoeg om te willen weten wat je eraan doet."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url:
        return render_template(
            "fout.html", titel="Deze link werkt niet meer",
            bericht="Vraag ons om een nieuwe, of doe de gratis scan op de homepage."), 404

    # Alleen tellen dat de pagina geopend is. Zonder dit weet je na honderd
    # verstuurde mails alleen dat er honderd verstuurd zijn.
    db.noteer_uitkomst_bekeken(webshop_url)

    gegevens = _klantgegevens(webshop_url)
    laatste = (db.get_rapporten_voor_webshop(webshop_url) or [None])[0]
    cijfers = benchmark.tel_op(db.benchmark_regels())

    return render_template(
        "uitkomst.html",
        webshop_url=webshop_url,
        # Het kenmerk meegeven zodat de afmeldknop op deze pagina kan staan.
        # Er stond alleen "mail ons", en iemand die zich overvallen voelt door
        # ongevraagde post klikt eerder op de spamknop van zijn mailprogramma
        # dan dat hij een mail gaat typen. Een spamklacht kost je je domein,
        # een afmelding kost je een adres.
        afmeld_token=token,
        winkelnaam=_winkelnaam(webshop_url),
        vermeldingen=gegevens["vermeldingen"],
        actieplan=gegevens["actieplan"],
        laatste=laatste,
        c=cijfers,
        token=token,
    )


@app.route("/uitkomst/<token>/verder")
def uitkomst_verder(token):
    """De knop op de uitkomstpagina. Telt de doorklik en stuurt dan door.

    Een eigen route en geen gewone link, want dit is de enige stap in de hele
    trechter die over geld gaat. Zonder dit weet je wel hoeveel mensen hun
    uitkomst openen, maar niet of ze daarna ook iets willen."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url:
        return redirect("/#prijzen")
    db.noteer_doorgeklikt(webshop_url)
    return redirect(f"/?winkel={quote(webshop_url)}#prijzen")


@app.route("/admin/benchmark")
def admin_benchmark():
    """Telt op wat er over alle gemeten winkels uitkwam.

    Dit is de pagina waar je je publiceerbare zinnen vandaan haalt. De losse
    winkels staan eronder zodat je kan controleren of een uitschieter klopt,
    maar wat je naar buiten brengt zijn alleen de aantallen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    regels = db.benchmark_regels()
    cijfers = benchmark.tel_op(regels)
    platforms = benchmark.per_platform(regels)
    return render_template(
        "admin_benchmark.html",
        # Ruwe tellingen erbij. Zonder deze stond er alleen "er is nog geen
        # enkele demo gedraaid", terwijl de benaderpagina 45 gemeten winkels
        # meldde. Twee schermen die elkaar tegenspreken zonder dat je kunt zien
        # welke van de twee liegt.
        diagnose=db.benchmark_diagnose(),
        regels=regels,
        c=cijfers,
        platforms=platforms,
        zinnen=benchmark.kernzinnen(cijfers, platforms),
        sleutel=admin_key,
    )


@app.route("/admin/voorbeeld")
def admin_voorbeeld():
    """Laat de klantpagina zien voor een webshop naar keuze, zonder dat daar een
    abonnement voor hoeft te bestaan.

    Nodig omdat de monitoringpagina alleen bereikbaar is via een klant_token dat
    pas ontstaat bij een betaald abonnement. Zonder deze route kan je niet
    controleren hoe een klant zijn eigen pagina ziet."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    if not webshop_url:
        return "Geef een webshop op met &url=...", 400

    rapporten = db.get_rapporten_voor_webshop(webshop_url)
    laatste = rapporten[0] if rapporten else None
    vorige = rapporten[1] if len(rapporten) > 1 else None

    verschil = laatste["score"] - vorige["score"] if (laatste and vorige) else None
    checks_by_categorie = {}
    if laatste:
        for c in laatste["checks"]:
            checks_by_categorie.setdefault(c.get("categorie", "overig"), []).append(c)

    gegevens = _klantgegevens(webshop_url)

    plan = gegevens["actieplan"]
    maand = db.kosten_per_klant_deze_maand(webshop_url) or {}
    uitgegeven = float(maand.get("kosten") or 0)
    taakstand = {
        "met_tekst": [a["titel"] for a in (plan or {}).get("acties", []) if a.get("oplossing")],
        "zonder_tekst": [a["titel"] for a in (plan or {}).get("acties", []) if not a.get("oplossing")],
        "uitgegeven": uitgegeven,
        "grens": kosten.GRENS_PER_KLANT_MAAND_EURO,
        "rem_dicht": uitgegeven >= kosten.GRENS_PER_KLANT_MAAND_EURO,
    }

    pagina = _paginagegevens(webshop_url)
    return render_template(
        "monitoring_details.html" if request.args.get("details") == "ja" else "monitoring.html",
        t=pagina["t"],
        paginataal=pagina["taal"],
        shopify_beheer=pagina["shopify_beheer"],
        webshop_url=webshop_url,
        klant_token=None,
        voorbeeld=True,
        sleutel=admin_key,
        taakstand=taakstand,
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        bronnen=gegevens["bronnen"],
        actieplan=gegevens["actieplan"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"],
            taal=_mailtaal(webshop_url)),
        laatste=laatste,
        verschil=verschil,
        verloop=list(reversed(rapporten))[-8:],
        nieuwe_problemen=[],
        checks_by_categorie=checks_by_categorie,
        uitvoering=_laatste_uitvoering(webshop_url),
        wijzigingen=db.get_wijzigingen(webshop_url),
        abonnement=True,
        status_labels=_standlabels(pagina["t"]),
    )


@app.route("/admin/beoordelingen")
def admin_beoordelingen():
    """Fase 5 stap 4. Laat zien wat er uit de antwoorden gehaald is: welke
    winkels genoemd worden, of onze winkel erbij staat, en of dat een
    vermelding of een echte aanbeveling was."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    meting_id = request.args.get("meting") or None

    # Opnieuw beoordelen gooit de oordelen van deze ronde weg en doet ze over.
    # Kost opnieuw geld, dus alleen op verzoek. Nodig zodra de beoordelaar iets
    # nieuws kan bepalen wat er bij de oude oordelen nog niet in zat.
    if webshop_url and request.args.get("opnieuw") == "ja":
        weg = db.verwijder_beoordelingen(webshop_url, meting_id)
        print(f"{weg} beoordelingen weggegooid voor {webshop_url}, worden opnieuw gedaan.")

    if webshop_url and (request.args.get("start") == "ja" or request.args.get("opnieuw") == "ja"):
        # De winkelnaam uit het profiel meegeven, want in de antwoorden staat
        # Dille & Kamille en niet dille-kamille.nl.
        profiel = db.get_winkelprofiel(webshop_url)
        omschrijving = (profiel or {}).get("omschrijving") or ""
        winkelnaam = _winkelnaam(webshop_url)
        start = False
        with _metingen_slot:
            if webshop_url not in _beoordelen_bezig:
                _beoordelen_bezig.add(webshop_url)
                start = True
        if start:
            threading.Thread(target=_beoordeel_achtergrond,
                             args=(webshop_url, meting_id, winkelnaam), daemon=True).start()
        return redirect(f"/admin/beoordelingen?key={admin_key}&url={webshop_url}&bezig=ja")

    if webshop_url and request.args.get("controleer") == "ja":
        start = False
        with _metingen_slot:
            if webshop_url not in _beoordelen_bezig:
                _beoordelen_bezig.add(webshop_url)
                start = True
        if start:
            def klus():
                try:
                    _controleer_uitspraken(webshop_url, meting_id, _winkelnaam(webshop_url))
                finally:
                    with _metingen_slot:
                        _beoordelen_bezig.discard(webshop_url)
            threading.Thread(target=klus, daemon=True).start()
        return redirect(f"/admin/beoordelingen?key={admin_key}&url={webshop_url}&bezig=ja")

    beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)] if webshop_url else []
    samenvatting = beoordeling.vat_samen(beoordelingen)

    # Onze eigen winkel oplichten in de concurrentietabel.
    for c in samenvatting["concurrenten"]:
        c["wij"] = scan_engine.is_eigen_winkel(webshop_url, c["naam"])

    return render_template(
        "admin_beoordelingen.html",
        webshop_url=webshop_url,
        sleutel=admin_key,
        beoordelingen=beoordelingen,
        s=samenvatting,
        bezig=request.args.get("bezig") == "ja",
        controle=controle.vat_samen(
            [dict(c) for c in db.get_uitspraakcontroles(webshop_url)]) if webshop_url else None,
        verklaring=verklaring.maak_verklaring(
            (db.get_rapporten_voor_webshop(webshop_url) or [{}])[0].get("checks") or [],
            beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None,
            taal=_mailtaal(webshop_url),
        ) if webshop_url else None,
    )


@app.route("/admin/oplossingen")
def admin_oplossingen():
    """Laat de kant-en-klare teksten van het actieplan los schrijven.

    Bestaat omdat het anders niet te doen is: de teksten worden normaal in de
    wekelijkse keten geschreven, en die hele keten opnieuw draaien kost tien
    minuten en ongeveer een euro. Als je alleen wil zien of het schrijven
    werkt, is dat zonde. Hier gebeurt alleen dat laatste stukje, en je ziet per
    taak wat eruit kwam of wat er misging.

    Met &opnieuw=ja gooit hij de bewaarde teksten eerst weg, zodat je een
    nieuwe versie kan laten schrijven na een aanpassing aan de opdracht."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    if not webshop_url:
        return "Geef een webshop op met &url=...", 400

    gegevens = _klantgegevens(webshop_url)
    plan = gegevens["actieplan"]

    if request.args.get("opnieuw") == "ja" and plan:
        for actie in plan.get("acties", []):
            if actie.get("id"):
                db.verwijder_taakoplossing(webshop_url, actie["id"])
        plan = _klantgegevens(webshop_url)["actieplan"]

    uitkomsten = _maak_taakoplossingen(webshop_url, plan)

    regels = []
    for u in uitkomsten:
        if u["was_er_al"]:
            stand = "stond er al"
        elif u["gelukt"]:
            stand = "nieuw geschreven"
        else:
            stand = f"MISLUKT: {u['fout']}"
        regels.append(f"{u['titel']}\n    {stand}")

    if not plan:
        tekst = ("Er is nog geen actieplan voor deze winkel. Draai eerst de keten via "
                 "/admin/demo, of wacht op de wekelijkse ronde.")
    elif not regels:
        tekst = "Het actieplan heeft geen taken die een geschreven tekst nodig hebben."
    else:
        tekst = "\n\n".join(regels)

    maand = db.kosten_per_klant_deze_maand(webshop_url) or {}
    uitgegeven = float(maand.get("kosten") or 0)

    return Response(
        f"Taakoplossingen voor {webshop_url}\n"
        f"{'=' * (22 + len(webshop_url))}\n\n"
        f"{tekst}\n\n"
        f"Deze maand uitgegeven aan deze winkel: {uitgegeven:.2f} van "
        f"{kosten.GRENS_PER_KLANT_MAAND_EURO:.2f} euro\n\n"
        f"Bekijk het resultaat op /admin/voorbeeld?key={admin_key}&url={webshop_url}\n"
        f"Opnieuw laten schrijven: voeg &opnieuw=ja toe aan dit adres.\n",
        mimetype="text/plain; charset=utf-8")


@app.route("/admin/bronnen")
def admin_bronnen():
    """Fase 5 punt 14. Laat zien welke externe pagina's er gevonden zijn en wie
    daarop staat.

    Hier controleer je het belangrijkste risico van deze stap: dat een naam
    verkeerd herkend wordt. Zie je een pagina waarvan je weet dat de winkel er
    wel op staat terwijl er nee staat, dan klopt de naamherkenning niet en moet
    dat eerst opgelost worden. Een verkeerde vindplaats is erger dan geen
    vindplaats, want de klant gaat erop af."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    meting_id = request.args.get("meting") or None

    # Opnieuw zoeken kost echt geld, dus alleen op een knop en nooit vanzelf
    # bij het openen van de pagina. Dezelfde afspraak als bij de demo.
    if webshop_url and request.args.get("start") == "ja":
        start = False
        with _metingen_slot:
            if webshop_url not in _beoordelen_bezig:
                _beoordelen_bezig.add(webshop_url)
                start = True
        if start:
            _zet_bronnen_status(webshop_url, "Gestart, bezig met voorbereiden.")

            def klus():
                try:
                    _zoek_bronnen(webshop_url, meting_id, _winkelnaam(webshop_url))
                finally:
                    with _metingen_slot:
                        _beoordelen_bezig.discard(webshop_url)
            threading.Thread(target=klus, daemon=True).start()
        else:
            # Niet stilzwijgend niets doen. Eerder gebeurde er dan schijnbaar
            # niets terwijl de knop wel ingedrukt was, en dan zit je te wachten
            # op iets dat nooit komt.
            _zet_bronnen_status(
                webshop_url,
                "Er liep al een taak voor deze winkel (beoordelen, controleren of zoeken). "
                "Wacht tot die klaar is en probeer het dan opnieuw.", klaar=True)
        return redirect(f"/admin/bronnen?key={admin_key}&url={webshop_url}")

    # De zoekmachine los testen. Kost een halve cent en bewijst in een keer of
    # de sleutel werkt. Zonder dit sta je te gissen of het aan de zoekmachine
    # ligt of aan de winkel.
    proef = None
    if webshop_url and request.args.get("proef") == "ja":
        proef = bronnen.test_zoekmachine(
            (request.args.get("vraag") or "").strip() or None, webshop_url=webshop_url)

    vindplaatsen = [dict(v) for v in db.get_bronvindplaatsen(webshop_url, meting_id)] if webshop_url else []
    winkelnaam = _winkelnaam(webshop_url) if webshop_url else None

    # Waarom levert dit niets op? Alles wat de bronanalyse nodig heeft, op een
    # rij, zonder dat er iets gezocht of betaald wordt.
    diagnose = None
    if webshop_url:
        beoordeeld = meting_id or db.laatste_beoordeelde_meting_id(webshop_url)
        gemeten = db.laatste_meting_id(webshop_url)
        beoordelingen = ([dict(b) for b in db.get_beoordelingen(webshop_url, beoordeeld)]
                         if beoordeeld else [])
        klantbeeld = beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None
        diagnose = {
            "gemeten_ronde": gemeten,
            "meting_id": beoordeeld,
            # Is er wel gemeten maar niet beoordeeld, dan is dat precies wat je
            # moet weten, en dan hoort er een knop bij die het oplost.
            "onbeoordeelde_ronde": bool(gemeten and gemeten != beoordeeld),
            "beoordelingen": len(beoordelingen),
            "vragen": bronnen.kies_vragen(klantbeeld) if klantbeeld else [],
            "concurrenten": bronnen.kies_concurrenten(klantbeeld) if klantbeeld else [],
            "genoemd": (klantbeeld or {}).get("genoemd"),
            "telbaar": (klantbeeld or {}).get("telbaar"),
        }

    status = _bronnen_status.get(webshop_url) if webshop_url else None

    return render_template(
        "admin_bronnen.html",
        webshop_url=webshop_url,
        sleutel=admin_key,
        winkelnaam=winkelnaam,
        vindplaatsen=vindplaatsen,
        s=bronnen.vat_samen(vindplaatsen, winkelnaam) if vindplaatsen else None,
        status=status,
        diagnose=diagnose,
        proef=proef,
        werkt=bronnen.beschikbaar(),
        waarom_niet=bronnen.waarom_niet(),
        aanbieder=bronnen.ZOEK_AANBIEDER,
    )


@app.route("/admin/modellen")
def admin_modellen():
    """Laat per aanbieder zien of de ingestelde modelnaam werkt, en welke namen
    deze sleutel wel mag gebruiken. Mislukken alle metingen bij een aanbieder,
    dan is een verkeerde modelnaam veruit de meest voorkomende oorzaak."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    resultaten = []
    for a in metingen.AANBIEDERS:
        if not os.environ.get(a["sleutel_naam"]):
            continue
        resultaten.append({
            "toonnaam": a["toonnaam"],
            "provider": a["provider"],
            "model": a["model"],
            "test": metingen.test_aanbieder(a) if a["model"] else
                    {"gelukt": False, "antwoord": "", "fout": "Geen modelnaam ingesteld."},
            "lijst": metingen.haal_modellijst(a["provider"]),
        })

    return render_template("admin_modellen.html", resultaten=resultaten, sleutel=admin_key)


@app.route("/admin/bezoekers")
def admin_bezoekers():
    """Wat er op de site gebeurt: hoeveel gratis scans, waar ze vandaan komen,
    welke winkels het vaakst gescand worden en hoeveel er betaalden.

    Zonder dit lanceer je blind: komt er niemand, of komen ze wel en haken ze
    af? Dat zijn twee verschillende problemen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    dagen = int(request.args.get("dagen", 30))
    overzicht = db.scanoverzicht(dagen)
    totaal = overzicht["totaal"] or {}
    scans = totaal.get("scans") or 0
    betaald = totaal.get("betaald") or 0
    return render_template(
        "admin_bezoekers.html",
        dagen=dagen,
        totaal=totaal,
        # Bewust als "x van de y" en niet als percentage: bij kleine aantallen
        # suggereert een percentage een precisie die er niet is.
        betaald=betaald,
        scans=scans,
        per_dag=overzicht["per_dag"],
        per_herkomst=overzicht["per_herkomst"],
        per_bron=overzicht.get("per_bron") or [],
        top_winkels=overzicht["top_winkels"],
        leads=db.zichtbaarheidstest_leads(),
        sleutel=admin_key,
    )


@app.route("/admin/kosten")
def admin_kosten():
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    dagen = int(request.args.get("dagen", 30))

    # Alleen op een knop, nooit vanzelf bij het openen van de pagina.
    #
    # Dit stond hier eerst bij elke keer laden, en dat heeft de hele site
    # platgelegd. Ook nu het snel is blijft het een opdracht die de database
    # aanpast, en zoiets hoort niet te gebeuren omdat iemand toevallig een
    # pagina opent. Een verversing in de browser is geen opdracht.
    hersteld = 0
    if request.args.get("herstel") == "ja":
        hersteld = db.herstel_onbekende_kosten(kosten.zoek_prijs)
        print(f"Kostenpagina: {hersteld} aanroepen alsnog van een prijs voorzien.")

    overzicht = db.kostenoverzicht(dagen)
    return render_template(
        "admin_kosten.html",
        dagen=dagen,
        hersteld=hersteld,
        # Welk model er precies onbekend is. Zonder die naam weet je niet wat je
        # in kosten.py moet zetten.
        onbekende_modellen=db.onbekende_modellen(dagen),
        totaal=overzicht["totaal"],
        per_klant=overzicht["per_klant"],
        marges=kosten.marge_per_klant([
            dict(r, kosten=kosten.naar_maand(float(r.get("kosten") or 0), dagen))
            for r in overzicht["per_klant"]
        ]),
        abonnement=kosten.ABONNEMENT_PER_MAAND,
        per_model=overzicht["per_model"],
        grenzen={
            "scan_euro": kosten.GRENS_PER_SCAN_EURO,
            "scan_aanroepen": kosten.GRENS_PER_SCAN_AANROEPEN,
            "klant_maand": kosten.GRENS_PER_KLANT_MAAND_EURO,
            "dag_totaal": kosten.GRENS_TOTAAL_DAG_EURO,
            "pogingen": kosten.MAX_POGINGEN,
        },
    )


@app.route("/admin/bestellingen")
def admin_bestellingen():
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    orders = payments.list_recent_orders()
    return render_template("admin_bestellingen.html", orders=orders)


@app.route("/admin/uitvoeringen", methods=["GET", "POST"])
def admin_uitvoeringen():
    """De werklijst voor "wij voeren het uit".

    Zolang dit handwerk is, is dit de belangrijkste pagina van het hele systeem:
    hier staat wie betaald heeft en nog zit te wachten. Een klant die betaalt en
    daarna niets hoort is erger dan een klant die nooit betaalt."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        uitvoering_id = request.form.get("id")
        stand = (request.form.get("stand") or "").strip()
        notitie = (request.form.get("notitie") or "").strip() or None
        if uitvoering_id and db.zet_uitvoering_stand(uitvoering_id, stand, notitie):
            melding = "Opgeslagen."
        else:
            melding = "Dat is niet gelukt. Controleer de stand."

    return render_template(
        "admin_uitvoeringen.html",
        uitvoeringen=db.get_uitvoeringen(),
        standen=db.UITVOERING_STANDEN,
        standtekst=db.UITVOERING_STAND_TEKST,
        melding=melding,
        sleutel=admin_key,
    )


# ---------------------------------------------------------------------------
# De Shopify-app
# ---------------------------------------------------------------------------
#
# Stap 1: installeren en de verplichte webhooks. Nog geen scherm met cijfers en
# nog geen betaling; die komen in de volgende stappen. Dit stuk moet eerst
# kloppen, want zonder een geldige installatie en zonder die webhooks komt de
# app de beoordeling van Shopify niet door.


# Waar de meting van een Shopify-winkel is. Alleen in het geheugen: na een
# herstart van Render is dit leeg, en dan ziet de winkelier gewoon de laatste
# uitkomst uit de database. De echte gegevens staan nooit alleen hier.
_shopify_status = {}


def _shopify_meten(winkel, webshop_url, email=None):
    """Scant de winkel en meet daarna bij ChatGPT en Gemini.

    Draait op de achtergrond, want dit duurt minuten. De winkelier ziet
    ondertussen waar we zijn.

    Bewust dezelfde keten als bij een betalende monitoringklant, zodat een
    winkel via Shopify en een winkel via krillo.nl nooit iets anders te zien
    krijgen bij dezelfde uitkomst."""
    def melden(tekst, klaar=False):
        _shopify_status[winkel] = {"tekst": tekst, "klaar": klaar,
                                   "mislukt": False}
        print(f"Shopify {winkel}: {tekst}")

    try:
        melden("je winkel doorlezen")
        resultaat = run_scan(webshop_url)
        if "error" in resultaat:
            _shopify_status[winkel] = {
                "tekst": "We konden je winkel niet inlezen. Staat er een wachtwoord op?",
                "klaar": True, "mislukt": True}
            return

        db.zet_platform(resultaat["url"], "Shopify")
        # Het e-mailadres MOET mee. De rapportentabel eist het, en zonder
        # rapport is er geen verklaring, en zonder verklaring blijft het
        # actieplan leeg terwijl er wel gemeten is. Dat ging hier eerst mis en
        # het viel alleen op in de logs, niet op het scherm.
        db.save_report("shopify", resultaat["url"], email or f"shopify@{winkel}",
                       resultaat.get("score", 0), resultaat.get("checks", []))
        _meet_en_beoordeel(resultaat["url"], stap=lambda t: melden(t))
        melden("klaar", klaar=True)
    except Exception as e:
        print(f"Shopify-meting mislukt voor {winkel}: {e}")
        _shopify_status[winkel] = {
            "tekst": "Er ging iets mis bij het meten. Probeer het zo nog eens.",
            "klaar": True, "mislukt": True}


# De voortgangsteksten in het Engels.
#
# Waarom een tabel en niet overal een taalparameter: die teksten worden gemaakt
# in de meetketen, en die keten is gedeeld met krillo.nl en met de wekelijkse
# ronde. Zou die keten talen moeten kennen, dan moet elke stap in elk bestand
# aangepast worden, en dan gaat er ergens eentje mis. Nu vertalen wij op één
# plek: vlak voordat het scherm het te zien krijgt.
#
# Staat een tekst hier niet in, dan gaat hij onvertaald door. Dat is met opzet:
# liever een Nederlandse regel dan een lege balk of een foutmelding.
STAND_ENGELS = {
    "we beginnen": "starting",
    "je winkel doorlezen": "reading your store",
    "koopvragen maken": "writing shopping questions",
    "vragen stellen aan AI": "asking the AI assistants",
    "antwoorden beoordelen": "reading the answers",
    "uitspraken controleren": "checking what they say about you",
    "externe bronnen zoeken": "looking for pages you are missing from",
    "actieplan klaarzetten": "putting your plan together",
    "we kijken je winkel na": "checking your store",
    "klaar": "done",
    "We konden je winkel niet inlezen. Staat er een wachtwoord op?":
        "We could not read your store. Is it password protected?",
    "Er ging iets mis bij het meten. Probeer het zo nog eens.":
        "Something went wrong while measuring. Please try again in a moment.",
    "Er ging iets mis bij het nakijken van je winkel.":
        "Something went wrong while checking your store.",
}


# Wat een Engelse winkelier ziet als er iets misgaat en wij de reden niet
# kunnen vertalen. De reden zelf komt uit de kostenrem of uit de meetketen en
# staat in het Nederlands, met bedragen en interne begrippen erin. Die laten wij
# bewust weg in plaats van hem onvertaald te tonen: een halve Nederlandse zin op
# een Engels scherm is erger dan een net gebrek aan detail. In de logboeken
# staat de echte reden wel, dus wij kunnen het altijd nazoeken.
MISLUKT_ENGELS = "Something went wrong. Please try again in a moment."


def _stand_in_taal(stand, markt):
    """De voortgangstekst in de taal van de winkel.

    Een Engelse winkelier las "Working: vragen stellen aan AI" op zijn eigen
    beheerscherm. Dat is precies het soort detail waaraan je ziet dat een app
    niet af is."""
    if not stand or (markt or {}).get("is_nederlands", True):
        return stand
    uit = dict(stand)
    tekst = stand.get("tekst")
    vertaald = STAND_ENGELS.get(tekst)
    if vertaald is None and tekst:
        # Niet in de tabel. Zit er een reden achter, dan is dat vrije
        # Nederlandse tekst uit de rem of uit de meetketen. Die tonen wij niet.
        vertaald = MISLUKT_ENGELS if str(tekst).startswith("mislukt") else tekst
    uit["tekst"] = vertaald
    return uit


def _voorstel_voor_scherm(voorstel, markt=None):
    """Een voorstel klaarmaken om te tonen.

    De HTML-versie gaat er bewust uit: die hoeft het scherm niet te weten en
    het scheelt een hoop overbodig verkeer."""
    if not voorstel:
        return None
    uit = {k: v for k, v in voorstel.items() if k != "nieuw_html"}
    woord = _wijziging_soort_woord(voorstel.get("id"), markt)
    if woord:
        uit["wat"] = woord
    uit["nieuw"] = _zonder_opmaak(uit.get("nieuw"))
    uit["oud"] = _zonder_opmaak(uit.get("oud"))
    return uit


def _voorstel_uit_wijziging(wijziging):
    """Bouwt een voorstel terug uit een teruggezette wijziging.

    Nodig als de app tussendoor opnieuw opgestart is en de voorstellen uit het
    geheugen weg zijn. Alles wat pas_toe nodig heeft staat in het kenmerk:
    "shopify:alt:<product>:<foto>", "shopify:tekst:<product>" of
    "shopify:faq"."""
    delen = (wijziging.get("taak_id") or "").split(":")
    if len(delen) < 2 or delen[0] != "shopify":
        return None
    soort = delen[1]
    nieuw = wijziging.get("nieuwe_waarde") or ""
    voorstel = {"id": wijziging["taak_id"], "soort": soort,
                "wat": wijziging.get("wat"), "waar": wijziging.get("waar"),
                "oud": wijziging.get("oude_waarde") or "",
                "nieuw": _zonder_opmaak(nieuw), "nieuw_html": nieuw}
    try:
        if soort == "alt" and len(delen) >= 4:
            voorstel["product_id"] = int(delen[2])
            voorstel["afbeelding_id"] = int(delen[3])
            voorstel["nieuw"] = nieuw
            voorstel.pop("nieuw_html", None)
        elif soort == "tekst" and len(delen) >= 3:
            voorstel["product_id"] = int(delen[2])
        elif soort != "faq":
            return None
    except ValueError:
        return None
    return voorstel


def _zonder_opmaak(tekst):
    """Haalt de HTML eruit, zodat er tekst op het scherm komt en geen code.

    Wij bewaren de HTML wel, want die moet ongewijzigd terug de winkel in
    kunnen bij het terugzetten. Alleen bij het TONEN hoort hij weg."""
    if not tekst:
        return ""
    kaal = re.sub(r"<br\s*/?>|</p>|</h[1-6]>", " ", str(tekst), flags=re.I)
    kaal = re.sub(r"<[^>]+>", "", kaal)
    kaal = (kaal.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", kaal).strip()


def _wijziging_soort_woord(taak_id, markt):
    """Het soort wijziging, in de taal van de winkel van nu.

    Het kenmerk ziet eruit als "shopify:tekst:123". Dat middelste woord is het
    enige wat in een vaste taal vastligt, dus daar rekenen wij mee, en niet met
    het woord dat ooit is opgeslagen."""
    delen = (taak_id or "").split(":")
    if len(delen) < 2:
        return None
    sleutel = {"alt": "alt", "tekst": "tekst", "faq": "faq"}.get(delen[1])
    if not sleutel:
        return None
    return shopify_werk._label(markt, sleutel)


def _app_adres_in_beheerscherm(winkel):
    """Het adres waarop deze app in het beheerscherm van de winkelier staat.

    Dit is waar wij hem naartoe sturen nadat hij bij Shopify betaald heeft, en
    nadat het installeren klaar is.

    Waarom via de winkel zelf en niet via admin.shopify.com/store/x/apps/naam:
    dat laatste adres hangt aan de naam die de app in de winkel heeft, en die
    naam kennen wij niet met zekerheid. Klopt hij niet, dan krijgt de winkelier
    een 404 direct nadat hij akkoord is gegaan met 39 dollar per maand. Dat is
    het slechtst denkbare moment voor een lege pagina.

    Het adres hieronder werkt met ons eigen klantnummer bij Shopify. Dat weten
    wij altijd, want zonder dat nummer draait de app helemaal niet. Shopify
    zoekt er zelf de juiste app bij en stuurt door naar het nieuwe
    beheerscherm."""
    api_key = (os.environ.get("SHOPIFY_API_KEY") or "").strip()
    if api_key:
        return f"https://{winkel}/admin/apps/{api_key}"
    # Zonder klantnummer draait er niets, maar dan liever de appslijst dan een
    # kapot adres.
    winkelnaam_kort = winkel.replace(".myshopify.com", "")
    print("LET OP: SHOPIFY_API_KEY ontbreekt, terugkeer gaat naar de appslijst.")
    return f"https://admin.shopify.com/store/{winkelnaam_kort}/apps"


def _shopify_scherm(winkel, rij):
    """Het scherm dat de winkelier binnen Shopify ziet."""
    webshop_url = rij.get("webshop_url") or ""
    gegevens = _klantgegevens(webshop_url) if webshop_url else {}
    laatste = (db.get_rapporten_voor_webshop(webshop_url) or [None])[0] if webshop_url else None

    return render_template(
        "shopify_app.html",
        api_key=os.environ.get("SHOPIFY_API_KEY", ""),
        winkel=winkel,
        winkelnaam=rij.get("naam") or webshop_url,
        webshop_url=webshop_url,
        vermeldingen=gegevens.get("vermeldingen"),
        actieplan=gegevens.get("actieplan"),
        bronnen=gegevens.get("bronnen"),
        laatste=laatste,
        markt=_markt_van(webshop_url) if webshop_url else None,
        stand=_stand_in_taal(_shopify_status.get(winkel), _markt_van(webshop_url)
                             if webshop_url else None),
        gratis_totaal=shopify_werk.GRATIS_WIJZIGINGEN,
    )


# Hoeveel seconden voor het verlopen wij al gaan verversen. Een meting duurt
# minuten, dus een sleutel die over dertig seconden verloopt is voor ons al
# verlopen. Zonder deze marge valt een lange meting halverwege om.
SLEUTEL_MARGE_SECONDEN = 300


def _shopify_sleutel(rij):
    """Geeft een sleutel die nu echt werkt, of None.

    Overal waar wij met Shopify praten moet dit ertussen zitten. Sleutels zijn
    een uur geldig, dus de sleutel die een uur geleden in de database gezet is
    doet het niet meer, en dat is precies de 403 waar dit voor gebouwd is.

    Er wordt niets teruggegeven zonder dat het nieuwe paar eerst opgeslagen is.
    Gebruiken wij een verse sleutel zonder hem op te slaan, dan vervalt de oude
    verversleutel en zijn wij de winkel voorgoed kwijt."""
    if not rij:
        return None
    winkel = rij.get("winkel")
    sleutel = rij.get("toegangssleutel")
    tot = rij.get("sleutel_tot")

    if sleutel and tot:
        over = (tot - datetime.now(timezone.utc)).total_seconds()
        if over > SLEUTEL_MARGE_SECONDEN:
            return sleutel

    verversleutel = rij.get("verversleutel")
    if not winkel or not verversleutel:
        # Geen verversleutel: dit is nog een sleutel van de oude soort, of de
        # winkel is nooit goed opgeslagen. Verversen kan niet, de winkelier
        # moet de app een keer openen zodat wij een nieuw kaartje krijgen.
        return None

    uitkomst = shopify_app.ververs_sleutel(winkel, verversleutel)
    if not uitkomst.get("gelukt"):
        print(f"Shopify: verversen mislukt voor {winkel}: {uitkomst.get('fout')}")
        if uitkomst.get("voorgoed_mislukt"):
            db.wis_shopify_verversleutel(winkel)
        return None

    bewaard = db.vervang_shopify_sleutelpaar(
        winkel, uitkomst["sleutel"], uitkomst.get("geldig_seconden"),
        uitkomst.get("verversleutel"), uitkomst.get("verversleutel_seconden"),
        rechten=uitkomst.get("rechten"))
    if not bewaard:
        # Niet opgeslagen betekent: niet gebruiken. Wij mogen de oude
        # verversleutel niet laten vervallen voor een sleutel die wij straks
        # nergens meer kunnen terugvinden.
        print(f"LET OP: nieuw sleutelpaar voor {winkel} is NIET opgeslagen. Niet gebruikt.")
        return None

    # De rij die de aanroeper vasthoudt bijwerken, anders pakt de volgende
    # regel in dezelfde functie nog de oude sleutel.
    rij["toegangssleutel"] = uitkomst["sleutel"]
    rij["verversleutel"] = uitkomst.get("verversleutel")
    rij["sleutel_tot"] = datetime.now(timezone.utc) + timedelta(
        seconds=int(uitkomst.get("geldig_seconden") or 0))
    return uitkomst["sleutel"]


def _shopify_uit_kaartje(id_token, winkel_uit_link=None):
    """Controleert het kaartje van Shopify en zorgt dat we een sleutel hebben.

    Geeft (winkel, rij) terug, of (None, None) als het kaartje niet deugt. Bij
    een winkel die we nog niet kennen, of waarvan de sleutel weg is, ruilen we
    het kaartje meteen in. Zo is een winkel die de app opnieuw installeert
    zonder gedoe weer werkend."""
    inhoud = shopify_app.controleer_id_token(id_token)
    if not inhoud:
        return None, None
    winkel = inhoud["winkel"]
    # Als er ook een winkel in de link staat, moet die dezelfde zijn. Anders
    # zou iemand met een geldig kaartje van zijn eigen winkel de gegevens van
    # een andere winkel kunnen opvragen.
    if winkel_uit_link and winkel_uit_link != winkel:
        print(f"Shopify: kaartje van {winkel} maar link zegt {winkel_uit_link}. Geweigerd.")
        return None, None

    rij = db.get_shopify_winkel(winkel)
    # Hebben wij al een sleutel die het doet, of een verversleutel waarmee wij
    # er een kunnen halen, dan is er niets aan de hand.
    #
    # Wat hier NIET mag staan is "hebben wij een sleutel, klaar". Een winkel
    # met een sleutel van de oude eeuwige soort komt dan nooit meer aan een
    # nieuwe, en elke aanroep bij Shopify geeft 403. Juist nu wij een geldig
    # kaartje in handen hebben is het moment om die om te ruilen.
    if rij and rij.get("toegangssleutel") and _shopify_sleutel(rij):
        return winkel, rij

    uitkomst = shopify_app.wissel_id_token(winkel, id_token)
    if not uitkomst.get("gelukt"):
        print(f"Shopify: inwisselen mislukt voor {winkel}: {uitkomst.get('fout')}")
        return winkel, None

    sleutel = uitkomst["sleutel"]
    gegevens = shopify_app.winkelgegevens(winkel, sleutel) or {}
    webshop_url = scan_engine.normalize_url(shopify_app.winkeladres(winkel, sleutel))
    db.bewaar_shopify_winkel(winkel, sleutel, rechten=uitkomst.get("rechten"),
                             webshop_url=webshop_url, email=gegevens.get("email"),
                             naam=gegevens.get("naam"),
                             geldig_seconden=uitkomst.get("geldig_seconden"),
                             verversleutel=uitkomst.get("verversleutel"),
                             verversleutel_seconden=uitkomst.get("verversleutel_seconden"))
    # Shopify vertelt ons de taal en het land van de winkel. Dat leggen we
    # meteen vast, want zonder dat krijgt een winkel in Texas Nederlandse
    # koopvragen. Dit moet gebeuren VOORDAT er gemeten wordt.
    if webshop_url:
        db.zet_markt(webshop_url, gegevens.get("taal"), gegevens.get("land"))
    threading.Thread(target=shopify_app.meld_webhooks_aan,
                     args=(winkel, sleutel, get_base_url()), daemon=True).start()
    return winkel, db.get_shopify_winkel(winkel)


@app.route("/shopify")
def shopify_start():
    """Waar Shopify de winkelier heen stuurt.

    Twee gevallen, en die moeten allebei werken:

    1. Er staat een id_token in de link. Dan heeft Shopify het installeren zelf
       geregeld en zit de winkelier in het beheerscherm naar ons scherm te
       kijken. Wij controleren het kaartje en tonen zijn cijfers.
    2. Er staat alleen ?shop=... in de link. Dan komt hij via de oude manier
       binnen en beginnen we het installeren zelf.

    Allebei nodig zolang de app nog op de oude installatiemanier staat
    ingesteld. Zodra dat omgezet is loopt alles via geval 1, en dan blijft
    geval 2 gewoon werken zonder kwaad te kunnen."""
    winkel = (request.args.get("shop") or "").strip().lower()
    id_token = request.args.get("id_token")

    if not shopify_app.beschikbaar():
        print(f"Shopify-installatie geweigerd: {shopify_app.waarom_niet()}")
        return render_template(
            "fout.html",
            titel="De Shopify-app is nog niet actief",
            bericht=("We zijn de app aan het klaarzetten. Probeer het later opnieuw, "
                     "of mail hallo@krillo.nl.")), 503

    # Geval 1: Shopify heeft het installeren zelf gedaan en stuurt ons een
    # kaartje mee. Dan is dit geen installatiepagina maar het scherm van de app.
    if id_token:
        echte_winkel, rij = _shopify_uit_kaartje(
            id_token, winkel if shopify_app.geldige_winkel(winkel) else None)
        if not echte_winkel:
            return "Ongeldig verzoek.", 401
        if not rij or not rij.get("toegangssleutel"):
            return render_template(
                "fout.html", titel="We konden je winkel niet openen",
                bericht=("Verwijder de app en installeer hem opnieuw. Blijft het "
                         "misgaan, mail dan hallo@krillo.nl.")), 502
        return _shopify_scherm(echte_winkel, rij)

    if not winkel:
        return render_template(
            "fout.html",
            titel="Installeren vanuit je Shopify-winkel",
            bericht=("Deze pagina hoort geopend te worden vanuit de Shopify App Store "
                     "of vanuit je eigen beheerscherm. Ga naar krillo.nl als je wilt "
                     "zien wat Krillo doet.")), 400

    if not shopify_app.geldige_winkel(winkel):
        # BEWUST het opgegeven adres niet terugtonen op de pagina. Dat komt van
        # buiten en hoort niet in onze HTML terecht te komen.
        print(f"Shopify-installatie geweigerd, geen geldig winkeladres: {winkel!r}")
        return render_template(
            "fout.html",
            titel="Dit is geen geldig winkeladres",
            bericht="Open de app vanuit je eigen Shopify-beheerscherm."), 400

    # Heeft deze winkel de app AL, dan tonen wij gewoon het scherm.
    #
    # Hier stond eerder meteen een doorverwijzing naar het toestemmingsscherm
    # van Shopify. Dat is een van de dingen waarop een app afgekeurd wordt:
    # iemand die al toestemming gaf en de app opent via een bewaarde link,
    # kreeg opnieuw de vraag of Krillo bij zijn producten mag.
    rij = db.get_shopify_winkel(winkel)
    if rij and rij.get("toegangssleutel") and rij.get("actief"):
        return _shopify_scherm(winkel, rij)

    link = shopify_app.installatielink(winkel, get_base_url())
    if not link:
        return render_template(
            "fout.html", titel="Installeren lukt nu niet",
            bericht="Probeer het zo nog eens, of mail hallo@krillo.nl."), 503

    # NIET met een gewone doorverwijzing. Shopify weigert zijn eigen
    # toestemmingspagina in een venster binnen het beheerscherm, en dan ziet de
    # winkelier een lege bladzijde in plaats van een scherm. Daarom een klein
    # paginaatje dat het BOVENSTE venster verplaatst. Werkt ook gewoon als de
    # app buiten Shopify geopend wordt, want dan is het bovenste venster het
    # enige venster.
    return render_template("shopify_doorsturen.html", link=link)


def _shopify_uit_kop():
    """Haalt de winkel uit het kaartje in de Authorization-kop.

    Het scherm binnen Shopify vraagt bij elke actie een vers kaartje op en
    stuurt dat mee. Zo hoeft er geen sessie of cookie te bestaan, en kan een
    verzoek niet van een andere winkel komen dan het kaartje zegt."""
    kop = request.headers.get("Authorization") or ""
    if not kop.lower().startswith("bearer "):
        return None, None
    return _shopify_uit_kaartje(kop[7:].strip())


@app.route("/shopify/api/meten", methods=["POST"])
def shopify_api_meten():
    """Start de meting voor deze winkel."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401

    webshop_url = rij.get("webshop_url")
    if not webshop_url:
        return jsonify({"error": "We weten het adres van je winkel nog niet."}), 400

    markt = _markt_van(webshop_url)
    bezig = _shopify_status.get(winkel)
    if bezig and not bezig.get("klaar"):
        # Al bezig. Twee metingen tegelijk kosten dubbel en leveren niets
        # extra's op, dus we melden gewoon waar de lopende meting is.
        return jsonify({"stand": _stand_in_taal(bezig, markt)})

    _shopify_status[winkel] = {"tekst": "we beginnen", "klaar": False, "mislukt": False}
    threading.Thread(target=_shopify_meten,
                     args=(winkel, webshop_url, rij.get("email")), daemon=True).start()
    return jsonify({"stand": _stand_in_taal(_shopify_status[winkel], markt)})


_shopify_voorstellen = {}
_shopify_werk_status = {}


def _shopify_voorstellen_maken(winkel, sleutel, webshop_url):
    """Kijkt wat er ontbreekt en schrijft de teksten. Zet nog niets in de winkel."""
    _shopify_werk_status[winkel] = {"tekst": "we kijken je winkel na", "klaar": False,
                                    "mislukt": False}
    try:
        markt_gegevens = _markt_van(webshop_url)
        uitkomst = shopify_werk.maak_voorstellen(winkel, sleutel, markt_gegevens)
        _shopify_voorstellen[winkel] = {v["id"]: v for v in uitkomst["voorstellen"]}
        betaalt = False
        try:
            rij = db.get_shopify_winkel(winkel) or {}
            if rij.get("toegangssleutel"):
                betaalt = shopify_billing.huidig_abonnement(
                    winkel, _shopify_sleutel(rij))["actief"]
        except Exception as e:
            print(f"Abonnement nakijken mislukt voor {winkel}: {e}")
        rij_nu = db.get_shopify_winkel(winkel) or {}
        al_gedaan = max(
            len([w for w in db.get_wijzigingen(webshop_url or "")
                 if (w.get("taak_id") or "").startswith("shopify:")]),
            int(rij_nu.get("wijzigingen_ooit") or 0))
        _shopify_werk_status[winkel] = {
            "tekst": "klaar", "klaar": True, "mislukt": False,
            "betaalt": betaalt,
            "gratis_over": None if betaalt else max(
                0, shopify_werk.GRATIS_WIJZIGINGEN - al_gedaan),
            "gratis_totaal": shopify_werk.GRATIS_WIJZIGINGEN,
            "aantallen": uitkomst["aantallen"],
            "fouten": uitkomst["fouten"],
            "voorstellen": [_voorstel_voor_scherm(stuk, markt_gegevens)
                            for stuk in uitkomst["voorstellen"]],
        }
    except Exception as e:
        print(f"Voorstellen maken mislukt voor {winkel}: {e}")
        _shopify_werk_status[winkel] = {
            "tekst": "Er ging iets mis bij het nakijken van je winkel.",
            "klaar": True, "mislukt": True}


@app.route("/shopify/api/voorstellen", methods=["POST"])
def shopify_api_voorstellen():
    """Maak voorstellen: wat wij zouden invullen, en wat er dan komt te staan.

    Dit is met opzet een aparte stap van het toepassen. De eigenaar moet eerst
    zien wat er in zijn winkel komt te staan. Het is zijn winkel."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401
    markt = _markt_van(rij.get("webshop_url") or "")
    bezig = _shopify_werk_status.get(winkel)
    if bezig and not bezig.get("klaar"):
        return jsonify({"stand": _stand_in_taal(bezig, markt)})
    threading.Thread(
        target=_shopify_voorstellen_maken,
        args=(winkel, _shopify_sleutel(rij), rij.get("webshop_url")),
        daemon=True).start()
    return jsonify({"stand": _stand_in_taal(
        {"tekst": "we kijken je winkel na", "klaar": False, "mislukt": False}, markt)})


@app.route("/shopify/api/werkstand")
def shopify_api_werkstand():
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Niet toegestaan."}), 401
    return jsonify({"stand": _stand_in_taal(
        _shopify_werk_status.get(winkel),
        _markt_van(rij.get("webshop_url") or ""))})


@app.route("/shopify/api/toepassen", methods=["POST"])
def shopify_api_toepassen():
    """Zet de gekozen voorstellen echt in de winkel.

    Alleen wat de eigenaar aangevinkt heeft, en alleen voorstellen die wij zelf
    net gemaakt hebben. Wij nemen geen tekst aan die het scherm meestuurt: dan
    zou iemand met een eigen verzoek elke tekst in zijn winkel kunnen laten
    zetten via ons, en dat is precies het soort gat waar je later spijt van
    krijgt."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401
    webshop_url = rij.get("webshop_url")
    if not webshop_url:
        return jsonify({"error": "We weten het adres van je winkel nog niet."}), 400

    gevraagd = (request.get_json(silent=True) or {}).get("ids") or []
    bekend = _shopify_voorstellen.get(winkel) or {}
    if not bekend:
        return jsonify({"error": "De voorstellen zijn verlopen. Kijk je winkel "
                                 "opnieuw na, dan maken we ze vers."}), 409

    # Hoeveel er gratis nog in mogen. Wij tellen wat er al echt in de winkel
    # staat, niet wat er in deze ronde gevraagd wordt: anders kan iemand door
    # de knop vaker in te drukken alsnog alles gratis krijgen.
    betaalt = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))["actief"]
    al_gedaan = len([w for w in db.get_wijzigingen(webshop_url)
                     if (w.get("taak_id") or "").startswith("shopify:")])
    # De teller loopt alleen op. Hier stond eerder het aantal wijzigingen dat NU
    # in de winkel staat, en dat betekende: drie keer toepassen, drie keer
    # terugzetten, en je had weer drie gratis. Dan doet Krillo al het werk voor
    # niets.
    ooit = max(al_gedaan, int(rij.get("wijzigingen_ooit") or 0))
    over = 10_000 if betaalt else max(0, shopify_werk.GRATIS_WIJZIGINGEN - ooit)

    gedaan, mislukt, overgeslagen, geblokkeerd = [], [], [], []
    for kenmerk in gevraagd[:50]:
        voorstel = bekend.get(kenmerk)
        if not voorstel:
            continue
        if over <= 0:
            geblokkeerd.append({"id": kenmerk, "waar": voorstel.get("waar")})
            continue
        uit = shopify_werk.pas_toe(winkel, _shopify_sleutel(rij), voorstel, webshop_url)
        if uit.get("gelukt"):
            gedaan.append({"id": kenmerk, "waar": voorstel.get("waar")})
            over -= 1
            db.tel_shopify_wijziging(winkel)
        elif uit.get("overgeslagen"):
            # Overgeslagen kost geen tegoed: er is niets veranderd.
            overgeslagen.append({"id": kenmerk, "waar": voorstel.get("waar"),
                                 "reden": uit.get("fout")})
        else:
            mislukt.append({"id": kenmerk, "waar": voorstel.get("waar"),
                            "reden": uit.get("fout")})
    return jsonify({"gedaan": gedaan, "overgeslagen": overgeslagen, "mislukt": mislukt,
                    "geblokkeerd": geblokkeerd, "betaalt": betaalt,
                    "gratis_over": None if betaalt else over,
                    "gratis_totaal": shopify_werk.GRATIS_WIJZIGINGEN})


@app.route("/shopify/api/wijzigingen")
def shopify_api_wijzigingen():
    """Alles wat wij in deze winkel veranderd hebben, met de oude tekst erbij."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Niet toegestaan."}), 401
    webshop_url = rij.get("webshop_url") or ""
    markt = _markt_van(webshop_url) if webshop_url else None
    regels = []
    for w in db.get_wijzigingen(webshop_url):
        taak_id = w.get("taak_id") or ""
        if not taak_id.startswith("shopify:"):
            continue
        regels.append({
            "id": taak_id,
            # Het soort staat in het kenmerk, en dat is de enige plek waar het
            # in een vaste taal staat. Het opgeslagen woord komt uit de taal van
            # de winkel op het moment van toepassen, en dan las een Engelse
            # winkelier ineens "Producttekst" op zijn eigen scherm.
            "wat": _wijziging_soort_woord(taak_id, markt) or w.get("wat"),
            "waar": w.get("waar"),
            # Zonder dit staat er letterlijk <p> en </p> op het scherm van de
            # winkelier. Wij bewaren de HTML wel, want die moet terug de winkel
            # in kunnen, maar tonen doen wij de tekst.
            "oud": _zonder_opmaak(w.get("oude_waarde"))[:600],
            "nieuw": _zonder_opmaak(w.get("nieuwe_waarde"))[:600],
            "op": w["gedaan_op"].isoformat() if w.get("gedaan_op") else None})
    return jsonify({"wijzigingen": regels})


@app.route("/shopify/api/terugzetten", methods=["POST"])
def shopify_api_terugzetten():
    """Eén wijziging ongedaan maken.

    Dit is geen extraatje. Wij beloven dat alles terug kan, en een belofte die
    alleen in de tekst staat en niet in een knop is geen belofte."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401
    webshop_url = rij.get("webshop_url") or ""
    kenmerk = (request.get_json(silent=True) or {}).get("id") or ""

    wijziging = None
    for w in db.get_wijzigingen(webshop_url):
        if w.get("taak_id") == kenmerk:
            wijziging = w
    if not wijziging:
        return jsonify({"error": "Die wijziging kennen we niet."}), 404

    uit = shopify_werk.zet_terug(winkel, _shopify_sleutel(rij), wijziging, webshop_url)
    if not uit.get("gelukt"):
        return jsonify({"error": uit.get("fout") or "Terugzetten mislukt."}), 502
    db.verwijder_wijziging(webshop_url, kenmerk)

    # Het voorstel weer terugzetten in de lijst.
    #
    # Zonder dit moest je na een klik op "Undo this" opnieuw je hele winkel
    # laten nakijken om die ene wijziging terug te krijgen, en kreeg je er
    # tientallen andere voorstellen bij die je niet gevraagd had. Iemand die
    # per ongeluk klikt hoort hem gewoon weer aan te kunnen zetten.
    voorstel = (_shopify_voorstellen.get(winkel) or {}).get(kenmerk)
    if not voorstel:
        voorstel = _voorstel_uit_wijziging(wijziging)
    if voorstel:
        _shopify_voorstellen.setdefault(winkel, {})[kenmerk] = voorstel

    markt = _markt_van(webshop_url) if webshop_url else None
    return jsonify({"ok": True, "id": kenmerk,
                    "voorstel": _voorstel_voor_scherm(voorstel, markt) if voorstel else None})


@app.route("/shopify/api/abonnement")
def shopify_api_abonnement():
    """Of deze winkel een lopend abonnement heeft. Elke keer vers bij Shopify."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401
    stand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    # Loopt er echt een abonnement, dan is de gratis proefperiode ook echt
    # gebruikt. Pas hier, en niet al bij het maken van de link.
    if stand["actief"] and not rij.get("proef_gehad_op"):
        db.markeer_proef_gehad(winkel)
        # Dit is precies één keer per winkel de eerste keer dat wij een lopend
        # abonnement zien, dus de goede plek voor een bericht aan onszelf. Bij
        # Shopify komt er geen melding van Mollie binnen, dus zonder dit zou een
        # abonnee via de app pas bij de wekelijkse ronde opvallen.
        _meld_nieuwe_klant(
            "Monitoring via de Shopify-app", rij.get("webshop_url") or winkel,
            rij.get("email") or "onbekend, via Shopify",
            f"{shopify_billing.PLAN_PRIJS} {shopify_billing.PLAN_VALUTA} per maand",
            extra=f"Winkel in Shopify: {winkel}")
        rij = db.get_shopify_winkel(winkel) or rij
    return jsonify({
        "actief": stand["actief"],
        "abonnement": stand["abonnement"],
        "prijs": shopify_billing.PLAN_PRIJS,
        "valuta": shopify_billing.PLAN_VALUTA,
        "proefdagen": 0 if rij.get("proef_gehad_op") else shopify_billing.PROEFDAGEN,
        "test": shopify_billing.testmodus(),
    })


@app.route("/shopify/api/abonneren", methods=["POST"])
def shopify_api_abonneren():
    """Start een abonnement en geef de bevestigingslink terug.

    Hier is nog niets afgesloten en niets betaald. Het scherm moet de winkelier
    naar die link sturen in het BOVENSTE venster, niet in het lijstje waar onze
    app in staat: Shopify weigert de betaalpagina in een venster-in-een-venster
    en dan ziet hij een lege bladzijde."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401

    bestaand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    if bestaand["actief"]:
        # Twee abonnementen naast elkaar betekent twee keer betalen. Dat mag
        # nooit gebeuren door een dubbele klik.
        return jsonify({"error": "Je hebt al een lopend abonnement.",
                        "actief": True}), 409

    # Terug naar het INGEBEDDE app-scherm in het beheerscherm van Shopify, niet
    # naar onze eigen /shopify. Die laatste ziet geen kaartje en stuurt de
    # winkelier door naar een nieuw toestemmingsscherm. Iemand die net akkoord
    # is gegaan met 39 dollar en dan opnieuw om toestemming gevraagd wordt, is
    # precies degene die afhaakt.
    terug = _app_adres_in_beheerscherm(winkel)
    # De gratis proefperiode krijg je een keer. Opzeggen en meteen weer starten
    # gaf anders telkens zeven nieuwe gratis dagen, en dat kan eindeloos.
    al_gehad = bool(rij.get("proef_gehad_op"))
    proefdagen = 0 if al_gehad else None
    uit = shopify_billing.start_abonnement(winkel, _shopify_sleutel(rij), terug,
                                           proefdagen=proefdagen)
    if not uit["gelukt"]:
        return jsonify({"error": uit["fout"]}), 502
    # Hier stond dat de proefperiode nu verbruikt was. Dat is te vroeg: op dit
    # punt is er alleen een link gemaakt en heeft de winkelier nog nergens ja
    # op gezegd. Klikt hij die pagina weg, dan was zijn gratis week op zonder
    # dat hij ooit iets had. De volgende keer stond er dan 39 dollar per maand
    # terwijl het scherm zeven dagen gratis belooft.
    #
    # Het verbruiken gebeurt nu pas als er echt een lopend abonnement is, zie
    # de route hieronder die de stand opvraagt.
    return jsonify({"link": uit["link"], "test": uit["test"],
                    "proefdagen": 0 if al_gehad else shopify_billing.PROEFDAGEN})


@app.route("/shopify/api/opzeggen", methods=["POST"])
def shopify_api_opzeggen():
    """Opzeggen vanuit onze eigen app."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Niet toegestaan."}), 401
    stand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    if not stand["actief"]:
        if stand.get("fout"):
            # Wij WETEN het niet, en dat is iets anders dan "er loopt niets".
            # Zou je hier gewoon "er loopt geen abonnement" zeggen, dan denkt
            # iemand dat hij opgezegd heeft terwijl er over vier dagen 39 dollar
            # afgeschreven wordt. Op de prijskaart staat "cancel any time".
            return jsonify({"error": "We konden je abonnement nu niet bij Shopify "
                                     "opvragen. Probeer het zo nog eens."}), 503
        return jsonify({"error": "Er loopt geen abonnement."}), 400
    uit = shopify_billing.zeg_op(winkel, _shopify_sleutel(rij),
                                 (stand["abonnement"] or {}).get("id"))
    if not uit["gelukt"]:
        return jsonify({"error": uit["fout"]}), 502
    return jsonify({"ok": True})


@app.route("/shopify/api/automatisch", methods=["GET", "POST"])
def shopify_api_automatisch():
    """Of wij uit onszelf mogen aanvullen bij deze winkel.

    Moet uit kunnen, en hij moet kunnen zien dat het aanstaat. Een app die
    ongevraagd in andermans winkel schrijft zonder schakelaar is een app waar
    terecht over geklaagd wordt."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Niet toegestaan."}), 401
    if request.method == "POST":
        aan = bool((request.get_json(silent=True) or {}).get("aan"))
        db.zet_shopify_automatisch(winkel, aan)
        rij = db.get_shopify_winkel(winkel) or rij
    return jsonify({"aan": bool(rij.get("automatisch", True)),
                    "laatst": (rij.get("automatisch_op").isoformat()
                               if rij.get("automatisch_op") else None)})


@app.route("/shopify/api/stand")
def shopify_api_stand():
    """Waar de meting is. Het scherm vraagt dit elke paar seconden.

    Dit is de meest zichtbare tekst van de hele app: hij staat er minutenlang
    en ververst elke vijf seconden. Juist hier moet de taal dus kloppen."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Niet toegestaan."}), 401
    return jsonify({"stand": _stand_in_taal(
        _shopify_status.get(winkel), _markt_van(rij.get("webshop_url") or ""))})


@app.route("/shopify/callback")
def shopify_callback():
    """Waar Shopify de winkelier terugstuurt nadat hij toestemming gaf.

    Hier gebeuren drie controles die geen van drieën mogen worden overgeslagen:
    klopt de handtekening, is het winkeladres echt, en hebben wij deze
    installatie zelf in gang gezet."""
    argumenten = request.args.to_dict()
    winkel = (argumenten.get("shop") or "").strip().lower()
    code = argumenten.get("code")
    kenmerk = argumenten.get("state")

    if not shopify_app.klopt_query_handtekening(argumenten):
        print(f"Shopify-callback geweigerd: handtekening klopt niet, winkel {winkel!r}")
        return "Ongeldig verzoek.", 401
    if not shopify_app.geldige_winkel(winkel) or not code:
        print(f"Shopify-callback geweigerd: winkel of code ontbreekt, {winkel!r}")
        return "Ongeldig verzoek.", 400
    if not shopify_app.kenmerk_klopt(kenmerk):
        # Dit gebeurt ook gewoon als Render tussendoor opnieuw is opgestart,
        # want de openstaande installaties staan alleen in het geheugen. Daarom
        # geen enge foutmelding maar de vraag om het nog eens te proberen.
        print(f"Shopify-callback geweigerd: onbekend of verlopen kenmerk, {winkel!r}")
        return render_template(
            "fout.html", titel="De installatie is verlopen",
            bericht="Begin opnieuw vanuit je Shopify-beheerscherm."), 400

    uitkomst = shopify_app.haal_toegangssleutel(winkel, code)
    if not uitkomst.get("gelukt"):
        print(f"Shopify-sleutel ophalen mislukt voor {winkel}: {uitkomst.get('fout')}")
        return render_template(
            "fout.html", titel="Installeren is niet gelukt",
            bericht="Probeer het nog eens. Blijft het misgaan, mail dan hallo@krillo.nl."), 502

    sleutel = uitkomst["sleutel"]
    gegevens = shopify_app.winkelgegevens(winkel, sleutel) or {}
    webshop_url = scan_engine.normalize_url(shopify_app.winkeladres(winkel, sleutel))

    bewaard = db.bewaar_shopify_winkel(
        winkel, sleutel, rechten=uitkomst.get("rechten"), webshop_url=webshop_url,
        email=gegevens.get("email"), naam=gegevens.get("naam"),
        geldig_seconden=uitkomst.get("geldig_seconden"),
        verversleutel=uitkomst.get("verversleutel"),
        verversleutel_seconden=uitkomst.get("verversleutel_seconden"))
    if not bewaard:
        # Zonder opslaan hebben we straks geen sleutel meer en kunnen we niets.
        # Dan liever nu een eerlijke fout dan een app die stil niets doet.
        print(f"LET OP: Shopify-winkel {winkel} is NIET opgeslagen.")
        return render_template(
            "fout.html", titel="Installeren is half gelukt",
            bericht="Verwijder de app en installeer hem opnieuw, of mail hallo@krillo.nl."), 500

    # De taal en het land van de winkel vastleggen. Vergeet je dit, dan valt
    # alles terug op Nederlands en krijgt een winkel in Texas dertig Nederlandse
    # koopvragen over Nederlandse webshops. Dat is geen schoonheidsfoutje: dat
    # is een meting over de verkeerde markt, zonder enige foutmelding.
    if gegevens.get("taal") or gegevens.get("land"):
        db.zet_markt(webshop_url, gegevens.get("taal"), gegevens.get("land"))

    # De verplichte webhooks. Op de achtergrond, want de winkelier hoeft daar
    # niet op te wachten, maar wel meteen: zonder deze webhooks komt de app de
    # beoordeling niet door.
    threading.Thread(
        target=shopify_app.meld_webhooks_aan,
        args=(winkel, sleutel, get_base_url()), daemon=True).start()

    # Terug naar het SCHERM VAN DE APP, niet naar de lijst met alle apps.
    # "Redirect to the app UI after installation" staat letterlijk in de eisen
    # van Shopify, en de appslijst is niet het scherm van de app.
    return redirect(_app_adres_in_beheerscherm(winkel))


def _webhook_binnen(onderwerp):
    """Gemeenschappelijke controle voor elke webhook van Shopify.

    Geeft (winkel, gegevens) terug, of (None, None) als het verzoek niet klopt.
    De handtekening wordt over de RUWE body berekend, want anders klopt hij
    nooit."""
    handtekening = request.headers.get("X-Shopify-Hmac-Sha256")
    ruw = request.get_data()
    if not shopify_app.klopt_webhook_handtekening(ruw, handtekening):
        print(f"Shopify-webhook {onderwerp} geweigerd: handtekening klopt niet.")
        return None, None
    winkel = (request.headers.get("X-Shopify-Shop-Domain") or "").strip().lower()
    try:
        gegevens = json.loads(ruw.decode("utf-8")) if ruw else {}
    except Exception:
        gegevens = {}
    return winkel, gegevens


@app.route("/shopify/webhooks/naleving", methods=["POST"])
def shopify_naleving():
    """Eén adres voor de drie verplichte privacy-webhooks van Shopify.

    Waarom dit erbij komt terwijl de drie losse adressen hieronder al bestaan:
    die drie kan je namelijk NIET aanmelden. Niet via de API (die weigert deze
    onderwerpen), en niet meer in het partnerscherm (die velden zijn weg).
    Ze horen in shopify.app.toml, en daar hoort per blok één adres bij dat alle
    drie de onderwerpen ontvangt. Dit is dat adres.

    Welk onderwerp het is staat in de kop X-Shopify-Topic. Daar kiezen wij op.

    De drie losse adressen blijven bestaan. Dat is geen dubbelop maar met opzet:
    de controle van Shopify klopt soms nog aan op de oude paden, en een 404 daar
    telt als afgekeurd."""
    handtekening = request.headers.get("X-Shopify-Hmac-Sha256")
    ruw = request.get_data()
    if not shopify_app.klopt_webhook_handtekening(ruw, handtekening):
        print("Shopify-nalevingswebhook geweigerd: handtekening klopt niet.")
        return "", 401

    onderwerp = (request.headers.get("X-Shopify-Topic") or "").strip().lower()
    winkel = (request.headers.get("X-Shopify-Shop-Domain") or "").strip().lower()

    if onderwerp == "customers/data_request":
        print(f"AVG-verzoek gegevens van {winkel}: Krillo bewaart geen gegevens van "
              f"kopers van deze winkel. Niets te leveren.")
    elif onderwerp == "customers/redact":
        print(f"AVG-wisverzoek klant van {winkel}: niets opgeslagen, niets gewist.")
    elif onderwerp == "shop/redact":
        if db.wis_shopify_winkel(winkel):
            print(f"Alles gewist voor {winkel} na shop/redact.")
        else:
            print(f"LET OP: wissen na shop/redact MISLUKT voor {winkel}. "
                  f"Handmatig nakijken.")
    else:
        # Een onderwerp dat wij hier niet verwachten. Wel 200 terug, want de
        # handtekening klopte en het kwam echt van Shopify. Blijven herhalen
        # heeft geen zin, maar het moet wel in de logs staan.
        print(f"Onbekend onderwerp op de nalevingswebhook: {onderwerp!r} van {winkel}")
    return "", 200


@app.route("/shopify/webhooks/klantgegevens", methods=["POST"])
def shopify_klantgegevens():
    """customers/data_request. Verplicht.

    Een consument vraagt via de winkelier welke gegevens wij van hem hebben.
    Krillo bewaart geen gegevens van de klanten van een webshop: we meten de
    winkel, niet de kopers. Er is dus niets te leveren, en dat leggen we vast
    zodat we het kunnen laten zien als het gevraagd wordt."""
    winkel, gegevens = _webhook_binnen("customers/data_request")
    if winkel is None:
        return "", 401
    print(f"AVG-verzoek gegevens van {winkel}: Krillo bewaart geen gegevens van "
          f"kopers van deze winkel. Niets te leveren.")
    return "", 200


@app.route("/shopify/webhooks/klant-wissen", methods=["POST"])
def shopify_klant_wissen():
    """customers/redact. Verplicht.

    Zelfde verhaal: wij hebben niets van individuele kopers, dus er valt niets
    te wissen. We antwoorden wel netjes, want anders blijft Shopify het
    opnieuw sturen."""
    winkel, gegevens = _webhook_binnen("customers/redact")
    if winkel is None:
        return "", 401
    print(f"AVG-wisverzoek klant van {winkel}: niets opgeslagen, niets gewist.")
    return "", 200


@app.route("/shopify/webhooks/winkel-wissen", methods=["POST"])
def shopify_winkel_wissen():
    """shop/redact. Verplicht.

    Komt 48 uur nadat de app verwijderd is. Hier moet ALLES van deze winkel
    weg, niet alleen de installatie: ook wat we gemeten en geschreven hebben,
    want dat gaat over hem."""
    winkel, gegevens = _webhook_binnen("shop/redact")
    if winkel is None:
        return "", 401
    if db.wis_shopify_winkel(winkel):
        print(f"Alles gewist voor {winkel} na shop/redact.")
    else:
        # Bewust toch 200 terug: anders blijft Shopify het herhalen terwijl het
        # probleem aan onze kant zit. Wel luid in de logs, want dit is een
        # wettelijke verplichting die we dan niet zijn nagekomen.
        print(f"LET OP: wissen na shop/redact MISLUKT voor {winkel}. Handmatig nakijken.")
    return "", 200


@app.route("/shopify/webhooks/verwijderd", methods=["POST"])
def shopify_verwijderd():
    """app/uninstalled. De winkelier heeft de app eruit gehaald.

    De sleutel werkt vanaf nu toch niet meer, dus die gooien we meteen weg. De
    rest van de gegevens blijft nog 48 uur staan tot shop/redact komt: haalt
    iemand de app er per ongeluk uit en zet hem terug, dan is zijn geschiedenis
    er nog."""
    winkel, gegevens = _webhook_binnen("app/uninstalled")
    if winkel is None:
        return "", 401
    db.shopify_verwijderd(winkel)
    print(f"Shopify-app verwijderd uit {winkel}, sleutel gewist.")
    return "", 200


@app.route("/admin/shopify")
def admin_shopify():
    """Welke winkels de app geïnstalleerd hebben. Voor jou, niet voor klanten."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)
    return render_template(
        "admin_shopify.html",
        winkels=db.get_shopify_winkels(alleen_actief=False),
        actief=shopify_app.beschikbaar(),
        waarom_niet=shopify_app.waarom_niet(),
        rechten=shopify_app.SCOPES,
        sleutel=admin_key,
    )


@app.route("/admin/werkbriefje", methods=["GET", "POST"])
def admin_werkbriefje():
    """Wat jij precies moet doen in de webshop van een klant die betaald heeft.

    Dit is de handmatige uitvoering van het actieplan. De klantpagina toont
    hetzelfde plan aan de klant; deze pagina voegt er toe wat jij nodig hebt om
    het werk te doen: een vak om de OUDE tekst in te plakken voordat je hem
    vervangt, en een vak voor wat je er neergezet hebt.

    Die oude tekst is het hele punt. We beloven de klant dat hij alles kan
    terugzetten, en die belofte is alleen waar als het ergens staat. Plak hem
    dus in voordat je iets vervangt, niet erna, want dan is hij weg."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    melding = None

    if request.method == "POST":
        taak_id = (request.form.get("taak_id") or "").strip()
        actie = (request.form.get("actie") or "opslaan").strip()
        if not webshop_url or not taak_id:
            melding = "Er ontbrak een winkel of een taak."
        elif actie == "verwijderen":
            melding = ("Weggehaald." if db.verwijder_wijziging(webshop_url, taak_id)
                       else "Er stond niets om weg te halen.")
        else:
            gelukt = db.bewaar_wijziging(
                webshop_url, taak_id,
                wat=(request.form.get("wat") or "").strip() or taak_id,
                waar=(request.form.get("waar") or "").strip() or None,
                oude_waarde=(request.form.get("oude_waarde") or "").strip() or None,
                nieuwe_waarde=(request.form.get("nieuwe_waarde") or "").strip() or None,
            )
            melding = "Opgeslagen." if gelukt else "Opslaan is niet gelukt."

    plan = None
    uitvoering = None
    wijzigingen = []
    stek = toepasmodule.ONBEKEND
    if webshop_url:
        plan = _klantgegevens(webshop_url)["actieplan"]
        uitvoering = _laatste_uitvoering(webshop_url)
        wijzigingen = db.get_wijzigingen(webshop_url)

        # De weg door het beheerscherm van dit ene platform bij elke taak. Zonder
        # dit staat er bij elke taak "dit pas je aan in de instellingen van je
        # webshop", en dan zit je alsnog te zoeken in een scherm dat je niet
        # kent. Bij twee klanten is dat vervelend, bij twintig schaalt het niet.
        profiel = db.get_winkelprofiel(webshop_url) or {}
        platform = profiel.get("platform") or (uitvoering or {}).get("platform")
        stek = toepasmodule.stekker(platform)
        plan = toepasmodule.verrijk_plan(plan, platform)

    return render_template(
        "admin_werkbriefje.html",
        webshop_url=webshop_url,
        plan=plan,
        uitvoering=uitvoering,
        stekker=stek,
        # Op taak-id, zodat het formulier bij elke taak meteen laat zien wat er
        # al vastgelegd is en je niet twee keer hetzelfde intypt.
        vastgelegd={w["taak_id"]: w for w in wijzigingen},
        wijzigingen=wijzigingen,
        melding=melding,
        sleutel=admin_key,
    )


@app.route("/admin/oplevering", methods=["GET", "POST"])
def admin_oplevering():
    """Het overzicht dat de klant krijgt als het werk klaar is.

    Bewust een aparte stap en niet automatisch bij "opgeleverd": jij hoort dit
    eerst zelf te lezen voordat het naar een betalende klant gaat."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen")
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    wijzigingen = db.get_wijzigingen(webshop_url) if webshop_url else []
    uitvoering = _laatste_uitvoering(webshop_url) if webshop_url else None
    melding = None

    if request.method == "POST":
        if not wijzigingen:
            melding = "Er is nog niets vastgelegd om te versturen."
        elif not (uitvoering and uitvoering.get("email")):
            melding = "Bij deze winkel staat geen opdracht met een e-mailadres."
        else:
            klant_token = db.get_or_create_klant(webshop_url, uitvoering["email"])
            monitoring_url = (f"{get_base_url()}/monitoring/{klant_token}"
                              if klant_token else None)
            verstuurd = emailing.send_oplevering(
                uitvoering["email"], webshop_url, [dict(w) for w in wijzigingen],
                monitoring_url)
            if verstuurd:
                db.zet_uitvoering_stand(uitvoering["id"], "opgeleverd")
                melding = "Verstuurd, en de opdracht staat nu op opgeleverd."
            else:
                # BEWUST de stand niet aanpassen als de mail mislukte. Anders
                # staat er "opgeleverd" terwijl de klant niets gekregen heeft,
                # en dan valt hij tussen wal en schip.
                melding = ("De mail is NIET verstuurd, dus de opdracht blijft op de "
                           "oude stand staan. Kijk in de logs van Render waarom.")

    return render_template(
        "admin_oplevering.html",
        webshop_url=webshop_url,
        wijzigingen=wijzigingen,
        uitvoering=uitvoering,
        melding=melding,
        sleutel=admin_key,
    )


@app.route("/bedankt")
def bedankt():
    """De pagina waar Mollie de bezoeker naartoe stuurt na het betalen.

    LET OP: Mollie stuurt hierheen bij ELKE afloop, ook bij afbreken,
    mislukken en verlopen, en geeft daarbij geen betaal-id mee dat wij kunnen
    natrekken. Deze pagina kan dus niet weten of er betaald is.

    Daarom staat er nu een tekst die in beide gevallen waar is. Hij stond hier
    als "Bedankt voor je audit, we gaan direct aan de slag", en dat las iemand
    die bij zijn bank op annuleren had gedrukt ook. Die zat vervolgens te
    wachten op een mail die nooit kwam.

    Beter zou zijn om de betaling hier echt na te trekken. Dat vraagt een eigen
    kenmerk dat we bij het aanmaken van de betaling meegeven en opslaan, zodat
    we hier weten welke betaling het was. Staat op de lijst; tot die tijd
    beweren we niets wat we niet weten."""
    checkout_type = request.args.get("type", "audit")

    # Sinds wij het betaalkenmerk in de terugkeerlink zetten kunnen wij hier WEL
    # nakijken wat er gebeurd is. Lukt dat niet, dan valt hij terug op de oude,
    # voorzichtige tekst die in beide gevallen waar is.
    kenmerk = (request.args.get("ref") or "").strip()
    betaald = None
    if kenmerk:
        try:
            stand = payments.get_payment_status(kenmerk)
            if stand is not None:
                betaald = bool(stand.get("is_paid"))
        except Exception as e:
            print(f"Betaling natrekken op de bedanktpagina mislukt: {e}")

    if betaald is False:
        # Afgebroken, mislukt of verlopen. Hier hoort geen vinkje en geen
        # bedankje. Iemand die bij zijn bank op annuleren drukte zat anders te
        # wachten op een mail die nooit zou komen.
        return render_template(
            "bedankt.html", gelukt=False,
            title="De betaling is niet afgerond",
            message=("Er is niets afgeschreven. Dat kan gebeuren: afgebroken, geweigerd "
                     "door de bank, of verlopen. Je kan het gewoon opnieuw proberen."),
            note="Loopt het steeds vast? Mail hallo@krillo.nl, dan regelen wij het met de hand.")

    if checkout_type == "monitoring":
        return render_template(
            "bedankt.html", gelukt=betaald,
            title="Je betaling is verwerkt door Mollie",
            message=("Is de betaling gelukt, dan is je eerste meting nu onderweg en krijg je "
                     "binnen ongeveer een kwartier een mail met de link naar je eigen pagina. "
                     "Daar staat wat je als eerste kan doen."),
            note=("Is er niets afgeschreven en krijg je geen mail, dan is de betaling niet "
                  "afgerond. Je kan het gewoon opnieuw proberen, of mail hallo@krillo.nl."))
    if checkout_type == "uitvoering":
        return render_template(
            "bedankt.html", gelukt=betaald,
            title="Je betaling is verwerkt door Mollie",
            message=("Is de betaling gelukt, dan staat er binnen enkele minuten een mail voor "
                     "je klaar. Daarin staat precies één ding: hoe je ons toegang geeft tot je "
                     "webshop. Zonder die stap kunnen we niet beginnen, dus doe hem even. Het "
                     "kost twee minuten."),
            note=("Niets ontvangen? Kijk eerst in je spamfolder. Is er ook niets afgeschreven, "
                  "dan is de betaling niet afgerond en kan je het opnieuw proberen. Mail "
                  "anders hallo@krillo.nl."))
    return render_template(
        "bedankt.html", gelukt=betaald,
        title="Je betaling is verwerkt door Mollie",
        message=("Is de betaling gelukt, dan gaan we direct aan de slag en ontvang je de "
                 "volledige audit binnen enkele minuten per e-mail."),
        note=("Niets ontvangen? Kijk eerst in je spamfolder. Is er ook niets afgeschreven, dan "
              "is de betaling niet afgerond en kan je het opnieuw proberen. Mail anders "
              "hallo@krillo.nl."))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
