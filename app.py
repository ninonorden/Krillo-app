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
from flask import Flask, request, jsonify, render_template, redirect, Response
from scan_engine import run_scan
import payments
import emailing
import ai_content
import db

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
    paginas = ["/", "/veelgestelde-vragen", "/over-ons", "/voorwaarden", "/privacybeleid"]
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
    if not webshop_url or not email:
        return jsonify({"error": "Vul een webshop-URL en e-mailadres in."}), 400

    result = payments.create_audit_payment(get_base_url(), webshop_url, email)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/checkout/monitoring", methods=["POST"])
def checkout_monitoring():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    webshop_url = (data.get("url") or "").strip()
    if not email or not webshop_url:
        return jsonify({"error": "Vul een e-mailadres en webshop-URL in."}), 400

    result = payments.create_monitoring_signup(get_base_url(), email, webshop_url)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


def _verwerk_betaling(payment_id, base_url):
    """Doet het echte werk na een geslaagde betaling: scannen, AI-tekst maken,
    rapport opslaan en e-mail versturen. Draait op de achtergrond zodat Mollie
    niet hoeft te wachten en de melding niet opnieuw stuurt."""
    try:
        status = payments.get_payment_status(payment_id)
        if not (status and status["is_paid"]):
            return

        metadata = status.get("metadata") or {}
        payment_type = metadata.get("type")
        webshop_url = metadata.get("webshop_url")
        email = metadata.get("email")

        if payment_type == "audit" and webshop_url and email:
            scan_result = run_scan(webshop_url)
            if "error" not in scan_result:
                ai_fixes = ai_content.generate_ai_fixes(
                    webshop_url, scan_result.get("checks", []), scan_result.get("gevonden_paginas")
                )
                fixes = ai_fixes if ai_fixes is not None else scan_result.get("voorbeeldfixes", [])
                token = db.save_report("audit", webshop_url, email, scan_result.get("score", 0),
                                        scan_result.get("checks", []), fixes)
                report_url = f"{base_url}/rapport/{token}" if token else None
                emailing.send_audit_email(email, webshop_url, scan_result, fixes, report_url)

        elif payment_type == "monitoring_first_payment":
            customer_id = metadata.get("customer_id")
            if customer_id:
                payments.create_subscription(customer_id)
            if webshop_url and email:
                scan_result = run_scan(webshop_url)
                if "error" not in scan_result:
                    token = db.save_report("monitoring", webshop_url, email, scan_result.get("score", 0),
                                            scan_result.get("checks", []))
                    report_url = f"{base_url}/rapport/{token}" if token else None
                    emailing.send_monitoring_welcome_email(email, webshop_url, scan_result, report_url)
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


@app.route("/api/cron/weekly-scans", methods=["POST"])
def weekly_scans():
    """Wordt eenmaal per week aangeroepen (via een Render Cron Job) om alle
    actieve monitoring-klanten opnieuw te scannen en een update te sturen."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or request.args.get("key") != cron_key:
        return "", 404

    customers = payments.list_active_monitoring_customers()
    sent = 0
    for c in customers:
        scan_result = run_scan(c["webshop_url"])
        if "error" not in scan_result:
            token = db.save_report("monitoring", c["webshop_url"], c["email"], scan_result.get("score", 0),
                                    scan_result.get("checks", []))
            report_url = f"{get_base_url()}/rapport/{token}" if token else None
            emailing.send_weekly_update_email(c["email"], c["webshop_url"], scan_result, report_url)
            sent += 1
    return jsonify({"klanten_gevonden": len(customers), "emails_verstuurd": sent})


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
