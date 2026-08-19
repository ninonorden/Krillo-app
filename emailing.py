"""
Krillo - automatische e-mails.

Verstuurt de audit-resultaten en monitoring-updates automatisch per e-mail,
zodra een betaling is bevestigd. Gebruikt Brevo's eigen API (via gewoon
webverkeer/HTTPS) in plaats van klassieke SMTP, omdat veel hostingdiensten
(waaronder Render) uitgaand SMTP-verkeer blokkeren.

Vereist deze omgevingsvariabele in Render:
- BREVO_API_KEY: te vinden in Brevo onder 'SMTP & API' > tabblad 'API keys'
  (dit is een andere sleutel dan de SMTP-sleutel die we eerst gebruikten)

Optioneel:
- SMTP_FROM_EMAIL: het afzenderadres (standaard: hallo@krillo.nl)
"""

import os
import requests

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_api_key():
    return os.environ.get("BREVO_API_KEY")


def send_email(to_email, subject, html_body):
    """Verstuurt een e-mail via de Brevo API. Geeft True/False terug, faalt
    nooit hard (een mislukte e-mail mag de rest van de afhandeling niet
    blokkeren)."""
    api_key = _get_api_key()
    if not api_key:
        print("E-mail niet verstuurd: BREVO_API_KEY ontbreekt nog.")
        return False

    from_email = os.environ.get("SMTP_FROM_EMAIL", "hallo@krillo.nl")

    try:
        response = requests.post(
            BREVO_API_URL,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            json={
                "sender": {"name": "Krillo", "email": from_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_body,
            },
            timeout=15,
        )
        if response.status_code >= 300:
            print(f"E-mail versturen mislukt: {response.status_code} {response.text}")
            return False
        return True
    except Exception as e:
        print(f"E-mail versturen mislukt: {e}")
        return False


def _base_html(title, intro, body_html):
    return f"""
    <div style="font-family: -apple-system, Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #12142B;">
      <div style="padding: 24px 0 8px;">
        <span style="display:inline-block; width:9px; height:9px; background:#FF4B3E; border-radius:50%; margin-right:8px;"></span>
        <strong style="font-size:18px;">Krillo</strong>
      </div>
      <h2 style="font-size: 22px; margin: 20px 0 8px;">{title}</h2>
      <p style="color:#3B3D57; font-size:14.5px; line-height:1.6;">{intro}</p>
      {body_html}
      <p style="color:#3B3D57; font-size:13px; margin-top:32px;">
        Vragen? Mail gewoon terug naar dit adres.<br>
        Krillo, KVK 78439620
      </p>
    </div>
    """


def _score_button(report_url, label="Bekijk het volledige rapport"):
    if not report_url:
        return ""
    return f"""
    <a href="{report_url}" style="display:inline-block; background:#FF4B3E; color:#fff; text-decoration:none;
       padding:12px 24px; border-radius:8px; font-weight:600; font-size:14px; margin-top:16px;">{label} &rarr;</a>
    """


def send_audit_email(to_email, webshop_url, scan_result, fix_previews, report_url=None):
    score = scan_result.get("score", 0)
    problemen = [c for c in scan_result.get("checks", []) if c["status"] != "ok"]
    score_color = "#1FB6A4" if score >= 80 else ("#C77D00" if score >= 40 else "#FF4B3E")

    intro_line = (
        f"We hebben {len(problemen)} verbeterpunten gevonden en {len(fix_previews)} concrete oplossingen voor je klaargezet."
        if problemen else
        "Sterk resultaat: er waren nauwelijks verbeterpunten te vinden."
    )

    body = f"""
    <div style="background:#12142B; border-radius:12px; padding:24px; margin-bottom:20px; text-align:center;">
      <div style="font-family:'Courier New',monospace; font-size:11px; color:#8B8DA8; text-transform:uppercase; margin-bottom:8px;">AI-zichtbaarheidsscore</div>
      <div style="font-size:40px; font-weight:700; color:{score_color};">{score}<span style="font-size:18px; color:#8B8DA8;">/100</span></div>
      <div style="font-size:13px; color:#B9BBD4; margin-top:4px;">{webshop_url}</div>
    </div>
    <p style="font-size:14.5px;">{intro_line}</p>
    <p style="font-size:14.5px;">Alle bevindingen en de kant-en-klare oplossingen staan overzichtelijk op je eigen rapportpagina.</p>
    {_score_button(report_url)}
    """
    html = _base_html("Je Krillo-audit is klaar", f"Hierbij de audit voor {webshop_url}.", body)
    return send_email(to_email, "Je Krillo-audit is klaar", html)


def send_monitoring_welcome_email(to_email, webshop_url, scan_result, report_url=None):
    score = scan_result.get("score", 0)
    body = f"""
    <p style="font-size:14.5px;"><strong>Startscore: {score}/100</strong> voor {webshop_url}</p>
    <p style="font-size:13.5px; color:#3B3D57;">
      Dit is je nulmeting. Elke week scannen we opnieuw, en laten we weten wat er
      is veranderd, of wanneer een concurrent je voorbijstreeft.
    </p>
    {_score_button(report_url, "Bekijk je startrapport")}
    """
    html = _base_html(
        "Welkom bij Krillo monitoring",
        f"Je monitoring voor {webshop_url} is gestart.",
        body,
    )
    return send_email(to_email, "Welkom bij Krillo monitoring", html)


def send_weekly_update_email(to_email, webshop_url, scan_result, report_url=None):
    score = scan_result.get("score", 0)
    body = f"""
    <p style="font-size:14.5px;"><strong>Huidige score: {score}/100</strong> voor {webshop_url}</p>
    {_score_button(report_url, "Bekijk het volledige rapport")}
    """
    html = _base_html("Je wekelijkse Krillo-update", f"Hier is de nieuwste scan voor {webshop_url}.", body)
    return send_email(to_email, f"Je wekelijkse Krillo-update ({score}/100)", html)
