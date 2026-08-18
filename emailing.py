"""
Krillo - automatische e-mails.

Verstuurt de audit-resultaten en monitoring-updates automatisch per e-mail,
zodra een betaling is bevestigd. Gebruikt een gewoon e-mailaccount (SMTP),
geen aparte e-maildienst nodig.

Vereist deze omgevingsvariabelen in Render:
- SMTP_LOGIN: je Brevo-accountmail (waarmee je inlogt bij Brevo)
- SMTP_PASSWORD: de SMTP-sleutel uit Brevo
- SMTP_SERVER: smtp-relay.brevo.com
- SMTP_FROM_EMAIL: optioneel, het afzenderadres (standaard: hallo@krillo.nl)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _get_smtp_settings():
    login = os.environ.get("SMTP_LOGIN")
    password = os.environ.get("SMTP_PASSWORD")
    server = os.environ.get("SMTP_SERVER")
    from_email = os.environ.get("SMTP_FROM_EMAIL", "hallo@krillo.nl")
    if not (login and password and server):
        return None
    return {"login": login, "password": password, "server": server, "from_email": from_email}


def send_email(to_email, subject, html_body):
    """Verstuurt een e-mail. Geeft True/False terug, faalt nooit hard
    (een mislukte e-mail mag de rest van de afhandeling niet blokkeren)."""
    settings = _get_smtp_settings()
    if settings is None:
        print("E-mail niet verstuurd: SMTP-instellingen ontbreken nog.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Krillo <{settings['from_email']}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings["server"], 587, timeout=15) as server:
            server.starttls()
            server.login(settings["login"], settings["password"])
            server.sendmail(settings["from_email"], to_email, msg.as_string())
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


def send_audit_email(to_email, webshop_url, scan_result, fix_previews):
    checks_html = ""
    for check in scan_result.get("checks", []):
        icon = "&#10003;" if check["status"] == "ok" else "&#8226;"
        checks_html += f"""
        <div style="padding:10px 0; border-top:1px solid #E4E2DA;">
          <strong style="font-size:13.5px;">{icon} {check['titel']}</strong><br>
          <span style="font-size:13px; color:#3B3D57;">{check['uitleg']}</span>
        </div>
        """

    fixes_html = ""
    for fix in fix_previews:
        fixes_html += f"""
        <div style="background:#F6F5F1; border-radius:8px; padding:14px; margin-bottom:10px;">
          <strong style="font-size:13.5px;">{fix['titel']}</strong><br>
          <span style="font-size:12.5px; color:#3B3D57;">Nu: {fix['voor']}</span><br>
          <span style="font-size:12.5px; color:#085041;">Na: {fix['na']}</span>
        </div>
        """

    body = f"""
    <p style="font-size:14.5px;"><strong>Score: {scan_result.get('score')}/100</strong> voor {webshop_url}</p>
    {checks_html}
    <h3 style="font-size:16px; margin-top:24px;">De aanpassingen</h3>
    {fixes_html}
    """
    html = _base_html(
        "Je Krillo-audit is klaar",
        f"Hierbij de volledige audit voor {webshop_url}, met alle verbeterpunten en de aanpassingen om ze op te lossen.",
        body,
    )
    return send_email(to_email, "Je Krillo-audit is klaar", html)


def send_monitoring_welcome_email(to_email, webshop_url, scan_result):
    checks_html = ""
    for check in scan_result.get("checks", []):
        icon = "&#10003;" if check["status"] == "ok" else "&#8226;"
        checks_html += f"""
        <div style="padding:10px 0; border-top:1px solid #E4E2DA;">
          <strong style="font-size:13.5px;">{icon} {check['titel']}</strong><br>
          <span style="font-size:13px; color:#3B3D57;">{check['uitleg']}</span>
        </div>
        """
    body = f"""
    <p style="font-size:14.5px;"><strong>Startscore: {scan_result.get('score')}/100</strong> voor {webshop_url}</p>
    {checks_html}
    <p style="font-size:13.5px; color:#3B3D57; margin-top:20px;">
      Dit is je nulmeting. Elke week scannen we opnieuw, en laten we weten
      wat er is veranderd, of wanneer een concurrent je voorbijstreeft.
    </p>
    """
    html = _base_html(
        "Welkom bij Krillo monitoring",
        f"Je monitoring voor {webshop_url} is gestart. Hier is je eerste scan, meteen na aanmelding.",
        body,
    )
    return send_email(to_email, "Welkom bij Krillo monitoring, hier is je eerste scan", html)


def send_weekly_update_email(to_email, webshop_url, scan_result):
    checks_html = ""
    for check in scan_result.get("checks", []):
        icon = "&#10003;" if check["status"] == "ok" else "&#8226;"
        checks_html += f"""
        <div style="padding:10px 0; border-top:1px solid #E4E2DA;">
          <strong style="font-size:13.5px;">{icon} {check['titel']}</strong><br>
          <span style="font-size:13px; color:#3B3D57;">{check['uitleg']}</span>
        </div>
        """
    body = f"""
    <p style="font-size:14.5px;"><strong>Huidige score: {scan_result.get('score')}/100</strong> voor {webshop_url}</p>
    {checks_html}
    """
    html = _base_html(
        "Je wekelijkse Krillo-update",
        f"Hier is de nieuwste scan voor {webshop_url}.",
        body,
    )
    return send_email(to_email, f"Je wekelijkse Krillo-update ({scan_result.get('score')}/100)", html)
