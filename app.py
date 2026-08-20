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
from scan_engine import run_scan
import payments
import emailing
import ai_content
import db
import artikelen

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
    paginas = ["/", "/artikelen", "/veelgestelde-vragen", "/over-ons", "/voorwaarden", "/privacybeleid", "/herroepen"]
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


def _draai_wekelijkse_scans(base_url):
    """Doet de wekelijkse scans op de achtergrond. Draait los van het verzoek,
    zodat de aanroeper niet hoeft te wachten en er niets vastloopt, ook niet
    als er straks honderd abonnees zijn."""
    try:
        customers = payments.list_active_monitoring_customers()
        print(f"Wekelijkse scan gestart voor {len(customers)} klant(en).")
        for c in customers:
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
            except Exception as e:
                print(f"Wekelijkse scan mislukt voor {c.get('webshop_url')}: {e}")
        print("Wekelijkse scan afgerond.")
    except Exception as e:
        print(f"Wekelijkse scan volledig mislukt: {e}")


@app.route("/api/cron/weekly-scans", methods=["GET", "POST"])
def weekly_scans():
    """Wordt eenmaal per week aangeroepen om alle actieve monitoring-klanten
    opnieuw te scannen. Antwoordt meteen, het werk gebeurt op de achtergrond."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or request.args.get("key") != cron_key:
        return "", 404

    base_url = get_base_url()
    threading.Thread(target=_draai_wekelijkse_scans, args=(base_url,), daemon=True).start()
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

    return render_template(
        "monitoring.html",
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
