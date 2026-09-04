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

import json
import os
import re
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template, redirect, Response
import scan_engine
from scan_engine import run_scan
import payments
import emailing
import ai_content
import db
import artikelen
import koopvragen
import kosten
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

app = Flask(__name__)
db.init_db()


def get_base_url():
    """Geeft de basis-URL van de site, werkt zowel lokaal als op Render."""
    configured = os.environ.get("BASE_URL")
    if configured:
        return configured.rstrip("/")
    return request.url_root.rstrip("/")


@app.route("/")
def home():
    return render_template("index.html")


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
Het monitoring-abonnement scant elke week automatisch opnieuw.

## Voor wie
Eigenaren van webshops in Nederland en Belgie die dit zelf regelen, zonder
marketingbureau en zonder technische kennis.

## Prijzen
- Gratis scan: 0 euro, geen account nodig
- Volledige audit: 79 euro eenmalig
- Monitoring: 39 euro per maand, maandelijks opzegbaar

## Belangrijke pagina's
- Homepage, gratis scan en gratis zichtbaarheidstest: https://www.krillo.nl/
- Artikelen over AI-zichtbaarheid: https://www.krillo.nl/artikelen
- Hoe we meten: https://www.krillo.nl/zo-meten-we
- Veelgestelde vragen: https://www.krillo.nl/veelgestelde-vragen
- Over Krillo en contact: https://www.krillo.nl/over-ons

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
        zichtbaarheid.draai(test_id, webshop_url,
                            aantal_vragen=zichtbaarheid.VOORPROEF_VRAGEN,
                            max_aanbieders=1)
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

    mag, _ = zichtbaarheid.mag_starten()
    if not mag:
        # Bewust geen foutmelding aan de bezoeker. Hij vroeg hier niet om, hij
        # deed gewoon een scan. Dan hoort hij geen melding te krijgen dat er
        # iets niet kon.
        return jsonify({"status": "uit"}), 200

    # Zonder e-mailadres, dus met een vaste plaatsaanduiding. Dat is geen
    # persoonsgegeven en er gaat nooit mail heen.
    test_id = db.start_zichtbaarheidstest(url, "voorproef@krillo.nl", False, _herkomst(),
                                          soort="voorproef")
    if not test_id:
        return jsonify({"status": "uit"}), 200

    threading.Thread(target=_draai_voorproef, args=(test_id, url), daemon=True).start()
    return jsonify({"test_id": test_id, "status": "bezig"})


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
        test_id = db.start_zichtbaarheidstest(url, email, nieuwsbrief, herkomst, hergebruikt=True)
        if test_id:
            db.zet_zichtbaarheidstest(test_id, "klaar", resultaat=eerder["resultaat"])
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
        return jsonify({"test_id": test_id, "status": "klaar",
                        "resultaat": resultaat, "zin": zin})

    mag, reden = zichtbaarheid.mag_starten()
    if not mag:
        return jsonify({"error": reden}), 429

    test_id = db.start_zichtbaarheidstest(url, email, nieuwsbrief, herkomst)
    if not test_id:
        return jsonify({"error": "Het lukte even niet. Probeer het zo nog eens."}), 500

    threading.Thread(target=_draai_zichtbaarheidstest,
                     args=(test_id, url, email, get_base_url()), daemon=True).start()
    return jsonify({"test_id": test_id, "status": "wachtrij"})


@app.route("/api/zichtbaarheidstest/<int:test_id>")
def api_zichtbaarheidstest_status(test_id):
    """De pagina vraagt hier om de tien seconden of de uitslag er al is.

    Geeft bewust geen e-mailadres terug. Wie het nummer van een test raadt,
    hoort niet te zien wie hem aangevraagd heeft."""
    test = db.get_zichtbaarheidstest(test_id)
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
    if not voorwaarden:
        return jsonify({"error": "Ga akkoord met de voorwaarden en het privacybeleid."}), 400

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    result = payments.create_monitoring_signup(get_base_url(), email, webshop_url,
                                               bedrijfsnaam, bron=bron)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "monitoring", voorwaarden, False)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


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
        if not db.claim_payment(payment_id):
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
                if factuurnummer:
                    emailing.send_factuur_email(email, factuurnummer, omschrijving, bedrag, bedrijfsnaam)

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
            klant_token = db.get_or_create_klant(webshop_url, email)
            monitoring_url = f"{base_url}/monitoring/{klant_token}" if klant_token else None
            emailing.send_uitvoering_welkom(email, webshop_url, platform, monitoring_url)

        elif payment_type == "audit" and webshop_url and email:
            scan_result = run_scan(webshop_url)
            if "error" not in scan_result:
                # Op welk winkelplatform deze shop draait. Werd tot nu toe
                # alleen bij demo's opgeslagen, waardoor we het van betalende
                # klanten juist niet wisten. Zonder dit schrijft de tekst bij
                # "waar zet je dit neer" een route in Shopify voor iemand met
                # WooCommerce.
                db.zet_platform(webshop_url, scan_result.get("platform"))
                ai_fixes = ai_content.generate_ai_fixes(
                    webshop_url, scan_result.get("checks", []), scan_result.get("gevonden_paginas")
                )
                fixes = ai_fixes if ai_fixes is not None else scan_result.get("voorbeeldfixes", [])
                token = db.save_report("audit", webshop_url, email, scan_result.get("score", 0),
                                        scan_result.get("checks", []), fixes, payment_id)
                report_url = f"{base_url}/rapport/{token}" if token else None
                emailing.send_audit_email(email, webshop_url, scan_result, fixes, report_url)

        elif payment_type == "monitoring_first_payment":
            customer_id = metadata.get("customer_id")
            if customer_id:
                payments.create_subscription(customer_id)
            if webshop_url and email:
                scan_result = run_scan(webshop_url)
                if "error" not in scan_result:
                    db.zet_platform(webshop_url, scan_result.get("platform"))
                    klant_token = db.get_or_create_klant(webshop_url, email)
                    db.save_report("monitoring", webshop_url, email, scan_result.get("score", 0),
                                    scan_result.get("checks", []), None, payment_id, klant_token)
                    monitoring_url = f"{base_url}/monitoring/{klant_token}" if klant_token else None
                    emailing.send_monitoring_welcome_email(email, webshop_url, scan_result, monitoring_url)

                    # Meteen de eerste meting bij de AI-modellen, niet pas over
                    # een week. Een nieuwe klant die zeven dagen naar een lege
                    # pagina kijkt, zegt op voordat hij iets gezien heeft.
                    threading.Thread(
                        target=_meet_en_beoordeel,
                        args=(webshop_url, email, klant_token, base_url),
                        daemon=True,
                    ).start()
    except Exception as e:
        print(f"Verwerken van betaling {payment_id} mislukt: {e}")


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
    if meetdag(webshop_url) == vandaag.weekday():
        return True

    vorige = db.get_previous_score(webshop_url)
    laatste = (vorige or {}).get("aangemaakt_op")
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
        customers = payments.list_active_monitoring_customers()
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

                emailing.send_weekly_update_email(
                    c["email"], c["webshop_url"], scan_result, monitoring_url, vorige_score
                )

                # Fase 5 stap 3: dezelfde ronde meteen gebruiken om de
                # koopvragen aan de AI-modellen te stellen. Gebeurt na de mail,
                # zodat een storing bij een AI-aanbieder nooit de wekelijkse
                # update van de klant tegenhoudt. Zijn er geen koopvragen of
                # geen sleutels, dan doet dit niets.
                try:
                    _meet_en_beoordeel(c["webshop_url"], c["email"], klant_token, base_url)
                except Exception as e:
                    print(f"Meting mislukt voor {c['webshop_url']}: {e}")
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
    if not cron_key or request.args.get("key") != cron_key:
        return "", 404

    alles = request.args.get("alles") == "ja"
    base_url = get_base_url()
    threading.Thread(target=_draai_wekelijkse_scans, args=(base_url, alles), daemon=True).start()
    return "ok", 200


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

    return render_template(
        "monitoring_details.html" if details else "monitoring.html",
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        bronnen=gegevens["bronnen"],
        actieplan=gegevens["actieplan"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"]),
        webshop_url=klant["webshop_url"],
        klant_token=klant_token,
        laatste=laatste,
        verschil=verschil,
        verloop=verloop,
        nieuwe_problemen=nieuwe_problemen,
        checks_by_categorie=checks_by_categorie,
        uitvoering=_laatste_uitvoering(klant["webshop_url"]),
        wijzigingen=db.get_wijzigingen(klant["webshop_url"]),
        status_labels={"ok": "goed", "deels": "kan beter", "probleem": "verbeterpunt"},
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
        status_labels={"ok": "goed", "deels": "kan beter", "probleem": "verbeterpunt"},
    )


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
                                     resultaat["vragen"], vervang=vervang)
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
        extra = koopvragen.vul_vragen_aan(
            webshop_url, omschrijving, tekort, [v["vraag"] for v in alles]
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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
        return

    # Is de ronde halverwege gestopt, dan is dat geen normale ronde. De klant
    # mag geen "genoemd bij 1 van de 3 vragen" te zien krijgen alsof dat een
    # volledige week is.
    if samenvatting.get("gestopt_door_rem"):
        print(f"LET OP: de meetronde voor {webshop_url} is halverwege gestopt: "
              f"{samenvatting.get('reden')}")

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
            emailing.send_vermeldingen_update(email, webshop_url, tekst, monitoring_url)
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
        uitkomst = ai_content.genereer_taakoplossing(
            webshop_url, taak_id, actie["titel"], actie["hoe"],
            platform=platform) or {}
        if uitkomst.get("gelukt"):
            db.bewaar_taakoplossing(webshop_url, taak_id, uitkomst["titel"],
                                    uitkomst["oplossing"], uitkomst["waar"])
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
    """De naam zoals de winkel zichzelf noemt, uit het winkelprofiel."""
    profiel = db.get_winkelprofiel(webshop_url)
    omschrijving = (profiel or {}).get("omschrijving") or ""
    return omschrijving.split(" is ")[0].strip() if " is " in omschrijving else None


def _klantgegevens(webshop_url):
    """Alles wat zowel de klantpagina als de voorbeeldweergave nodig heeft.

    Op een plek, zodat een abonnee en de voorbeeldweergave nooit iets anders
    kunnen laten zien."""
    # De klant ziet de nieuwste ronde. Voor stijgen of dalen zijn er twee
    # nodig, en die haalt get_beoordelingen niet op.
    beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url)]
    twee_rondes = [dict(b) for b in db.get_beoordelingen_rondes(webshop_url, rondes=2)]
    vermeldingen = beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None
    controles = [dict(c) for c in db.get_uitspraakcontroles(webshop_url)]
    winkelnaam = _winkelnaam(webshop_url)
    # De vindplaatsen van precies de ronde die hierboven getoond wordt. Zonder
    # dat zou je de bronnen van vorige week naast de cijfers van deze week
    # kunnen zetten, en dan klopt het verhaal niet meer. Liever niets tonen dan
    # iets dat bij een andere meting hoort.
    ronde = db.laatste_beoordeelde_meting_id(webshop_url)
    vindplaatsen = ([dict(v) for v in db.get_bronvindplaatsen(webshop_url, ronde)]
                    if ronde else [])
    controle_samenvatting = controle.vat_samen(controles) if controles else None
    bronnen_samenvatting = bronnen.vat_samen(vindplaatsen, winkelnaam) if vindplaatsen else None

    # Fase 5 punt 15. Leunt op alles hierboven en op de verklaring uit de
    # scan, dus die halen we er hier bij. Bewust op deze ene plek berekend,
    # zodat de klantpagina en de voorbeeldweergave nooit een ander plan kunnen
    # tonen dan elkaar.
    checks = (db.get_rapporten_voor_webshop(webshop_url) or [{}])[0].get("checks") or []
    plan = actieplan.maak_actieplan(
        verklaring=verklaring.maak_verklaring(checks, vermeldingen),
        klantbeeld=vermeldingen,
        bronnen=bronnen_samenvatting,
        controle=controle_samenvatting,
        winkelnaam=winkelnaam,
    )

    # De bewaarde oplossingen aan de taken hangen. Alleen lezen, nooit
    # schrijven: dat gebeurt in de wekelijkse keten.
    if plan and plan.get("acties"):
        opgeslagen = db.get_taakoplossingen(webshop_url)
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
            url, benchmark_stand = _demo_wachtrij.pop(0)
        _demo_draaien(url, benchmark_stand)


def _demo_inplannen(urls, benchmark_stand=False, opnieuw=False):
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
                         if (w.get("vragen") or 0) > 0}
        except Exception as e:
            print(f"Kon niet nakijken welke demo's al gedaan zijn: {e}")

    toegevoegd = 0
    overgeslagen = 0
    with _demo_slot:
        for url in urls:
            huidig = _demo_status.get(url, "")
            bezig = huidig and huidig != "klaar" and not huidig.startswith("mislukt")
            if url in al_gedaan:
                overgeslagen += 1
                _demo_status.setdefault(url, "klaar")
                continue
            if any(w[0] == url for w in _demo_wachtrij) or bezig:
                continue
            _demo_wachtrij.append((url, benchmark_stand))
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


def _demo_draaien(webshop_url, benchmark_stand=False):
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
        db.save_report("demo", resultaat["url"], None, resultaat.get("score", 0),
                       resultaat.get("checks", []))
        db.zet_platform(resultaat["url"], resultaat.get("platform"))

        _meet_en_beoordeel(
            resultaat["url"],
            stap=lambda t: _demo_status.__setitem__(webshop_url, t),
            max_vragen=BENCHMARK_VRAGEN if benchmark_stand else None,
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
    sleutel = request.form.get("key") if request.method == "POST" else request.args.get("key")
    if not admin_key or sleutel != admin_key:
        return "", 404

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
    if not admin_key or request.args.get("key") != admin_key:
        return "Niet gevonden.", 404

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
                token = db.get_benchmark_token(webshop_url)
                if not token:
                    melding = "Er kon geen link gemaakt worden. Probeer het nog eens."
                else:
                    gegevens = _klantgegevens(webshop_url)
                    v = gegevens.get("vermeldingen") or {}
                    c = benchmark.tel_op(db.benchmark_regels())
                    verstuurd = emailing.send_onderzoeksmail(
                        email, webshop_url, f"{get_base_url()}/uitkomst/{token}",
                        genoemd=v.get("genoemd"), telbaar=v.get("telbaar"),
                        nooit_genoemd=c.get("nooit_genoemd"), gemeten=c.get("gemeten"))
                    if verstuurd:
                        db.markeer_onderzoeksmail(webshop_url)
                        melding = f"Verstuurd naar {email}."
                    else:
                        # BEWUST niet als verstuurd markeren. Anders sla je hem
                        # over bij de volgende ronde terwijl hij niets gehad
                        # heeft.
                        melding = ("De mail is NIET verstuurd. Kijk in de logs van "
                                   "Render waarom, en probeer het opnieuw.")

    regels = []
    for r in db.benchmark_regels():
        url = r.get("webshop_url")
        profiel = db.get_winkelprofiel(url) or {}
        regels.append({
            "webshop_url": url,
            "genoemd": r.get("genoemd"),
            "vragen": r.get("vragen"),
            "score": r.get("score"),
            "email": profiel.get("contact_email"),
            "gemaild_op": profiel.get("onderzoeksmail_op"),
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

    gegevens = _klantgegevens(webshop_url)
    laatste = (db.get_rapporten_voor_webshop(webshop_url) or [None])[0]
    cijfers = benchmark.tel_op(db.benchmark_regels())

    return render_template(
        "uitkomst.html",
        webshop_url=webshop_url,
        winkelnaam=_winkelnaam(webshop_url),
        vermeldingen=gegevens["vermeldingen"],
        actieplan=gegevens["actieplan"],
        laatste=laatste,
        c=cijfers,
        token=token,
    )


@app.route("/admin/benchmark")
def admin_benchmark():
    """Telt op wat er over alle gemeten winkels uitkwam.

    Dit is de pagina waar je je publiceerbare zinnen vandaan haalt. De losse
    winkels staan eronder zodat je kan controleren of een uitschieter klopt,
    maar wat je naar buiten brengt zijn alleen de aantallen."""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

    regels = db.benchmark_regels()
    cijfers = benchmark.tel_op(regels)
    platforms = benchmark.per_platform(regels)
    return render_template(
        "admin_benchmark.html",
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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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

    return render_template(
        "monitoring_details.html" if request.args.get("details") == "ja" else "monitoring.html",
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
            laatste["checks"] if laatste else [], gegevens["vermeldingen"]),
        laatste=laatste,
        verschil=verschil,
        verloop=list(reversed(rapporten))[-8:],
        nieuwe_problemen=[],
        checks_by_categorie=checks_by_categorie,
        uitvoering=_laatste_uitvoering(webshop_url),
        wijzigingen=db.get_wijzigingen(webshop_url),
        status_labels={"ok": "goed", "deels": "kan beter", "probleem": "verbeterpunt"},
    )


@app.route("/admin/beoordelingen")
def admin_beoordelingen():
    """Fase 5 stap 4. Laat zien wat er uit de antwoorden gehaald is: welke
    winkels genoemd worden, of onze winkel erbij staat, en of dat een
    vermelding of een echte aanbeveling was."""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
        winkelnaam = omschrijving.split(" is ")[0].strip() if " is " in omschrijving else None
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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

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
    if not admin_key or request.args.get("key") != admin_key:
        return "", 404

    dagen = int(request.args.get("dagen", 30))
    overzicht = db.kostenoverzicht(dagen)
    return render_template(
        "admin_kosten.html",
        dagen=dagen,
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
    if not admin_key or request.args.get("key") != admin_key:
        return "Niet gevonden.", 404

    orders = payments.list_recent_orders()
    return render_template("admin_bestellingen.html", orders=orders)


@app.route("/admin/uitvoeringen", methods=["GET", "POST"])
def admin_uitvoeringen():
    """De werklijst voor "wij voeren het uit".

    Zolang dit handwerk is, is dit de belangrijkste pagina van het hele systeem:
    hier staat wie betaald heeft en nog zit te wachten. Een klant die betaalt en
    daarna niets hoort is erger dan een klant die nooit betaalt."""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key or request.args.get("key") != admin_key:
        return "Niet gevonden.", 404

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
        stand=_shopify_status.get(winkel),
    )


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
    if rij and rij.get("toegangssleutel"):
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
                             naam=gegevens.get("naam"))
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

    link = shopify_app.installatielink(winkel, get_base_url())
    if not link:
        return render_template(
            "fout.html", titel="Installeren lukt nu niet",
            bericht="Probeer het zo nog eens, of mail hallo@krillo.nl."), 503
    return redirect(link)


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

    bezig = _shopify_status.get(winkel)
    if bezig and not bezig.get("klaar"):
        # Al bezig. Twee metingen tegelijk kosten dubbel en leveren niets
        # extra's op, dus we melden gewoon waar de lopende meting is.
        return jsonify({"stand": bezig})

    _shopify_status[winkel] = {"tekst": "we beginnen", "klaar": False, "mislukt": False}
    threading.Thread(target=_shopify_meten,
                     args=(winkel, webshop_url, rij.get("email")), daemon=True).start()
    return jsonify({"stand": _shopify_status[winkel]})


@app.route("/shopify/api/stand")
def shopify_api_stand():
    """Waar de meting is. Het scherm vraagt dit elke paar seconden."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Niet toegestaan."}), 401
    return jsonify({"stand": _shopify_status.get(winkel)})


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
        email=gegevens.get("email"), naam=gegevens.get("naam"))
    if not bewaard:
        # Zonder opslaan hebben we straks geen sleutel meer en kunnen we niets.
        # Dan liever nu een eerlijke fout dan een app die stil niets doet.
        print(f"LET OP: Shopify-winkel {winkel} is NIET opgeslagen.")
        return render_template(
            "fout.html", titel="Installeren is half gelukt",
            bericht="Verwijder de app en installeer hem opnieuw, of mail hallo@krillo.nl."), 500

    # De verplichte webhooks. Op de achtergrond, want de winkelier hoeft daar
    # niet op te wachten, maar wel meteen: zonder deze webhooks komt de app de
    # beoordeling niet door.
    threading.Thread(
        target=shopify_app.meld_webhooks_aan,
        args=(winkel, sleutel, get_base_url()), daemon=True).start()

    # Terug naar het beheerscherm van de winkel. In de volgende stap komt hier
    # het scherm van de app zelf.
    return redirect(f"https://{winkel}/admin/apps")


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
    if not admin_key or request.args.get("key") != admin_key:
        return "Niet gevonden.", 404
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
    if not admin_key or request.args.get("key") != admin_key:
        return "Niet gevonden.", 404

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
    if webshop_url:
        plan = _klantgegevens(webshop_url)["actieplan"]
        uitvoering = _laatste_uitvoering(webshop_url)
        wijzigingen = db.get_wijzigingen(webshop_url)

    return render_template(
        "admin_werkbriefje.html",
        webshop_url=webshop_url,
        plan=plan,
        uitvoering=uitvoering,
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
    if not admin_key or request.args.get("key") != admin_key:
        return "Niet gevonden.", 404

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
    if checkout_type == "monitoring":
        return render_template(
            "bedankt.html",
            title="Je betaling is verwerkt door Mollie",
            message=("Is de betaling gelukt, dan is je eerste meting nu onderweg en krijg je "
                     "binnen ongeveer een kwartier een mail met de link naar je eigen pagina. "
                     "Daar staat wat je als eerste kan doen."),
            note=("Is er niets afgeschreven en krijg je geen mail, dan is de betaling niet "
                  "afgerond. Je kan het gewoon opnieuw proberen, of mail hallo@krillo.nl."))
    if checkout_type == "uitvoering":
        return render_template(
            "bedankt.html",
            title="Je betaling is verwerkt door Mollie",
            message=("Is de betaling gelukt, dan staat er binnen enkele minuten een mail voor "
                     "je klaar. Daarin staat precies één ding: hoe je ons toegang geeft tot je "
                     "webshop. Zonder die stap kunnen we niet beginnen, dus doe hem even. Het "
                     "kost twee minuten."),
            note=("Niets ontvangen? Kijk eerst in je spamfolder. Is er ook niets afgeschreven, "
                  "dan is de betaling niet afgerond en kan je het opnieuw proberen. Mail "
                  "anders hallo@krillo.nl."))
    return render_template(
        "bedankt.html",
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
