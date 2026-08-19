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
from flask import Flask, request, jsonify, render_template, redirect
from scan_engine import run_scan
import payments
import emailing
import ai_content

app = Flask(__name__)


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


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Vul een website-URL in."}), 400

    result = run_scan(url)
    if "error" in result:
        return jsonify(result), 400
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


@app.route("/webhooks/mollie", methods=["POST"])
def mollie_webhook():
    """Mollie roept dit aan zodra de status van een betaling verandert."""
    payment_id = request.form.get("id")
    if not payment_id:
        return "", 400

    status = payments.get_payment_status(payment_id)
    if status and status["is_paid"]:
        metadata = status.get("metadata") or {}
        payment_type = metadata.get("type")
        webshop_url = metadata.get("webshop_url")
        email = metadata.get("email")

        if payment_type == "audit" and webshop_url and email:
            scan_result = run_scan(webshop_url)
            if "error" not in scan_result:
                ai_fixes = ai_content.generate_ai_fixes(webshop_url, scan_result.get("checks", []))
                fixes = ai_fixes if ai_fixes is not None else scan_result.get("voorbeeldfixes", [])
                emailing.send_audit_email(email, webshop_url, scan_result, fixes)

        elif payment_type == "monitoring_first_payment":
            customer_id = metadata.get("customer_id")
            if customer_id:
                payments.create_subscription(customer_id)
            if webshop_url and email:
                scan_result = run_scan(webshop_url)
                if "error" not in scan_result:
                    emailing.send_monitoring_welcome_email(email, webshop_url, scan_result)

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
            emailing.send_weekly_update_email(c["email"], c["webshop_url"], scan_result)
            sent += 1
    return jsonify({"klanten_gevonden": len(customers), "emails_verstuurd": sent})


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
