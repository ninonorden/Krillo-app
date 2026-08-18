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
    if not webshop_url:
        return jsonify({"error": "Vul eerst een webshop-URL in."}), 400

    result = payments.create_audit_payment(get_base_url(), webshop_url)
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
        if metadata.get("type") == "monitoring_first_payment":
            # Eerste betaling van het abonnement is gelukt: nu het echte,
            # doorlopende abonnement aanmaken.
            customer_id = metadata.get("customer_id")
            if customer_id:
                payments.create_subscription(customer_id)
        # Voor "audit": hier zou de audit-generatie en e-mail naar de klant
        # getriggerd worden zodra dat gebouwd is.

    return "", 200


@app.route("/bedankt")
def bedankt():
    checkout_type = request.args.get("type", "audit")
    if checkout_type == "monitoring":
        message = "Bedankt! Je Krillo-monitoringabonnement is gestart."
    else:
        message = "Bedankt! We gaan aan de slag met je audit."
    return message


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
