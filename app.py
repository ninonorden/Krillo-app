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

import os
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
import beoordeling
import controle
import verklaring
import waarschuwing

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
    webshop_url = (data.get("url") or "").strip()
    toelichting = (data.get("toelichting") or "").strip()
    if not email:
        return jsonify({"error": "Vul het e-mailadres in waarmee je hebt besteld."}), 400

    nummer = db.leg_herroeping_vast(email, webshop_url, toelichting)
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
    inhoud = """User-agent: *
Allow: /

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
    paginas = ["/", "/artikelen", "/zo-meten-we", "/veelgestelde-vragen", "/over-ons", "/voorwaarden", "/privacybeleid", "/herroepen"]
    paginas += [f"/artikelen/{a['slug']}" for a in artikelen.ARTIKELEN]
    urls = "".join(
        f"<url><loc>https://www.krillo.nl{p}</loc><changefreq>weekly</changefreq></url>"
        for p in paginas
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
structuur en inhoud. De gratis scan toont de score en alle bevindingen. De betaalde
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
- Homepage en gratis scan: https://www.krillo.nl/
- Artikelen over AI-zichtbaarheid: https://www.krillo.nl/artikelen
- Hoe we meten: https://www.krillo.nl/zo-meten-we
- Veelgestelde vragen: https://www.krillo.nl/veelgestelde-vragen
- Over Krillo en contact: https://www.krillo.nl/over-ons

## Contact
hallo@krillo.nl
"""
    return Response(inhoud, mimetype="text/plain")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Vul een website-URL in."}), 400

    result = run_scan(url)
    if "error" in result:
        return jsonify(result), 400

    previous = db.get_previous_score(result["url"])
    if previous:
        result["vorige_score"] = previous["score"]
        result["verschil"] = result["score"] - previous["score"]

    return jsonify(result)


@app.route("/api/checkout/audit", methods=["POST"])
def checkout_audit():
    data = request.get_json(silent=True) or {}
    webshop_url = (data.get("url") or "").strip()
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

    result = payments.create_audit_payment(get_base_url(), webshop_url, email, bedrijfsnaam)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "audit", voorwaarden, direct)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/checkout/monitoring", methods=["POST"])
def checkout_monitoring():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    webshop_url = (data.get("url") or "").strip()
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    if not email or not webshop_url:
        return jsonify({"error": "Vul een e-mailadres en webshop-URL in."}), 400
    if not voorwaarden:
        return jsonify({"error": "Ga akkoord met de voorwaarden en het privacybeleid."}), 400

    result = payments.create_monitoring_signup(get_base_url(), email, webshop_url, bedrijfsnaam)
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
        # Tweede blokkade: is er voor deze betaling al een rapport gemaakt?
        if db.report_bestaat_al(payment_id):
            print(f"Er bestaat al een rapport voor betaling {payment_id}, niets verstuurd.")
            return

        status = payments.get_payment_status(payment_id)
        if not (status and status["is_paid"]):
            return

        # Negeer late herhalingen van oude betalingen. Mollie blijft ongeveer een
        # etmaal opnieuw melden, en zonder deze controle zou een betaling van
        # uren geleden alsnog een nieuwe mail opleveren.
        aangemaakt = status.get("created_at")
        if aangemaakt:
            try:
                gemaakt_op = datetime.fromisoformat(aangemaakt.replace("Z", "+00:00"))
                leeftijd = datetime.now(timezone.utc) - gemaakt_op
                if leeftijd > timedelta(hours=3):
                    print(f"Betaling {payment_id} is {leeftijd} oud, late herhaling genegeerd.")
                    return
            except Exception as e:
                print(f"Kon de leeftijd van betaling {payment_id} niet bepalen: {e}")

        metadata = status.get("metadata") or {}
        payment_type = metadata.get("type")
        webshop_url = metadata.get("webshop_url")
        email = metadata.get("email")
        bedrijfsnaam = metadata.get("bedrijfsnaam")

        # Eerst de betaalbevestiging met factuur, die hoort er meteen te zijn.
        # De audit zelf duurt langer omdat er gescand en geschreven moet worden.
        if email:
            if payment_type == "audit":
                omschrijving = f"Krillo volledige audit voor {webshop_url}"
            else:
                omschrijving = f"Krillo monitoring, eerste maand, voor {webshop_url}"
            bedrag = status.get("bedrag")
            if bedrag is not None:
                factuurnummer = db.maak_factuur(payment_id, email, bedrijfsnaam, omschrijving, bedrag)
                if factuurnummer:
                    emailing.send_factuur_email(email, factuurnummer, omschrijving, bedrag, bedrijfsnaam)

        if payment_type == "audit" and webshop_url and email:
            scan_result = run_scan(webshop_url)
            if "error" not in scan_result:
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

    # Zorg dat dezelfde betaling nooit twee keer verwerkt wordt.
    if not db.claim_payment(payment_id):
        print(f"Betaling {payment_id} was al verwerkt, overgeslagen.")
        return "", 200

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
def monitoring_pagina(klant_token):
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
        "monitoring.html",
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"]),
        webshop_url=klant["webshop_url"],
        klant_token=klant_token,
        laatste=laatste,
        verschil=verschil,
        verloop=verloop,
        nieuwe_problemen=nieuwe_problemen,
        checks_by_categorie=checks_by_categorie,
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


def _genereer_koopvragen_achtergrond(webshop_url, vervang=False):
    """Draait op de achtergrond, want scannen plus vragen bedenken duurt een
    minuut of meer. De pagina hoeft daar niet op te wachten."""
    try:
        scan_result = run_scan(webshop_url)
        extra = scan_result.get("gevonden_paginas") if "error" not in scan_result else None
        resultaat = koopvragen.genereer_koopvragen(webshop_url, extra)
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

    webshop_url = (request.args.get("url") or "").strip()
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
    dubbelingen = koopvragen.vind_dubbele_vragen(vragen) if zoeken else []
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

    webshop_url = (request.args.get("url") or "").strip()
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


def _meet_en_beoordeel(webshop_url, email=None, klant_token=None, base_url=None):
    """De hele keten van fase 5 achter elkaar: meten, beoordelen, controleren en
    zo nodig waarschuwen.

    Draait wekelijks na de gewone scan. De volgorde ligt vast omdat elke stap op
    de vorige leunt: zonder antwoorden valt er niets te beoordelen, en zonder
    beoordeling zijn er geen uitspraken om te controleren.

    Elke stap in een eigen try, want een storing bij een AI-aanbieder mag nooit
    de rest tegenhouden."""
    # Zonder koopvragen valt er niets te meten. Bij een nieuwe abonnee bestaan
    # die nog niet, dus die maken we hier alsnog aan. Anders zou een klant die
    # net 39 euro betaald heeft een lege pagina zien terwijl op de site staat
    # dat we elke week dertig vragen stellen.
    if not db.get_koopvragen(webshop_url, alleen_actief=True):
        print(f"Nog geen koopvragen voor {webshop_url}, die maken we eerst.")
        _genereer_koopvragen_achtergrond(webshop_url, vervang=False)

    winkelnaam = _winkelnaam(webshop_url)

    samenvatting = metingen.meet_webshop(webshop_url)
    meting_id = (samenvatting or {}).get("meting_id") or db.laatste_meting_id(webshop_url)
    if not meting_id:
        return

    try:
        beoordeling.beoordeel_ronde(webshop_url, meting_id, winkelnaam)
    except Exception as e:
        print(f"Beoordelen mislukt voor {webshop_url}: {e}")

    controle_samenvatting = _controleer_uitspraken(webshop_url, meting_id, winkelnaam)

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
    return {
        "vermeldingen": vermeldingen,
        "controle": controle.vat_samen(controles) if controles else None,
        "beweging": waarschuwing.vergelijk(twee_rondes, _winkelnaam(webshop_url)),
    }


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

    webshop_url = (request.args.get("url") or "").strip()
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

    return render_template(
        "monitoring.html",
        webshop_url=webshop_url,
        klant_token=None,
        voorbeeld=True,
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"]),
        laatste=laatste,
        verschil=verschil,
        verloop=list(reversed(rapporten))[-8:],
        nieuwe_problemen=[],
        checks_by_categorie=checks_by_categorie,
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

    webshop_url = (request.args.get("url") or "").strip()
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
    kern = webshop_url.replace("www.", "").split(".")[0].replace("-", "").lower()
    for c in samenvatting["concurrenten"]:
        c["wij"] = kern and kern in c["naam"].replace(" ", "").replace("&", "").replace("-", "").lower()

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


@app.route("/bedankt")
def bedankt():
    checkout_type = request.args.get("type", "audit")
    if checkout_type == "monitoring":
        title = "Je monitoring is gestart"
        message = "Je eerste scan is onderweg. Check zo je inbox voor de resultaten."
        note = "Elke week ontvang je automatisch een nieuwe update."
    else:
        title = "Bedankt voor je audit"
        message = "We gaan direct aan de slag. Je ontvangt de volledige audit binnen enkele minuten per e-mail."
        note = "Niets ontvangen? Check ook je spamfolder, of mail hallo@krillo.nl."
    return render_template("bedankt.html", title=title, message=message, note=note)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
