"""
Vezora - lokale ontwikkelserver.

Dit koppelt de landingspagina aan de echte scan-logica, zodat de
"Scan gratis"-knop een werkelijk resultaat teruggeeft in plaats van
alleen de simulatie te tonen.

Starten:
    pip install flask requests beautifulsoup4
    python3 app.py

Ga daarna naar http://127.0.0.1:5000 in je browser.
"""

from flask import Flask, request, jsonify, render_template
from scan_engine import run_scan

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


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


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
