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
from datetime import datetime

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


BEDRIJFSGEGEVENS = {
    "naam": "Krillo",
    "adres": "Gerard Doustraat 22-3V",
    "plaats": "1072 VW Amsterdam",
    "kvk": "78439620",
    "btw": "NL855820627B01",
    "email": "hallo@krillo.nl",
}


def send_factuur_email(to_email, factuurnummer, omschrijving, bedrag, bedrijfsnaam=None, datum=None):
    """Stuurt een betaalbevestiging met factuur. Of er BTW op staat hangt af van
    de instelling BTW_REGELING in Render: 'kor' betekent geen BTW berekenen
    (kleineondernemersregeling), 'btw' betekent wel. Zet die op 'btw' zodra je
    boven de KOR-grens komt, dan verandert de factuur vanzelf mee."""
    regeling = os.environ.get("BTW_REGELING", "kor").lower()
    datum = datum or datetime.now().strftime("%d-%m-%Y")
    factuurnr = f"KR-{datetime.now().year}-{factuurnummer:04d}"

    if regeling == "btw":
        excl = round(bedrag / 1.21, 2)
        btw_bedrag = round(bedrag - excl, 2)
        bedragen_html = f"""
        <tr><td style="padding:6px 0; color:#3B3D57;">Bedrag exclusief btw</td>
            <td style="padding:6px 0; text-align:right;">&euro; {excl:.2f}</td></tr>
        <tr><td style="padding:6px 0; color:#3B3D57;">Btw 21%</td>
            <td style="padding:6px 0; text-align:right;">&euro; {btw_bedrag:.2f}</td></tr>
        <tr><td style="padding:10px 0 0; border-top:1px solid #E4E2DA;"><strong>Totaal betaald</strong></td>
            <td style="padding:10px 0 0; border-top:1px solid #E4E2DA; text-align:right;"><strong>&euro; {bedrag:.2f}</strong></td></tr>
        """
        btw_regel = f"<p style='font-size:12px; color:#3B3D57;'>Btw-identificatienummer: {BEDRIJFSGEGEVENS['btw']}</p>"
    else:
        bedragen_html = f"""
        <tr><td style="padding:10px 0 0;"><strong>Totaal betaald</strong></td>
            <td style="padding:10px 0 0; text-align:right;"><strong>&euro; {bedrag:.2f}</strong></td></tr>
        """
        btw_regel = ("<p style='font-size:12px; color:#3B3D57;'>Geen btw in rekening gebracht op grond van "
                      "de kleineondernemersregeling.</p>")

    klantregel = f"<div style='font-size:13px; color:#3B3D57;'>{bedrijfsnaam}</div>" if bedrijfsnaam else ""

    body = f"""
    <p style="font-size:14.5px;">Je betaling is gelukt. Hieronder vind je de factuur, bewaar deze voor je administratie.</p>

    <div style="background:#FFFFFF; border:1px solid #E4E2DA; border-radius:12px; padding:24px; margin:20px 0;">
      <table style="width:100%; font-size:13px; margin-bottom:18px;">
        <tr>
          <td style="vertical-align:top;">
            <strong style="font-size:14px;">{BEDRIJFSGEGEVENS['naam']}</strong><br>
            <span style="color:#3B3D57;">{BEDRIJFSGEGEVENS['adres']}<br>
            {BEDRIJFSGEGEVENS['plaats']}<br>
            KVK {BEDRIJFSGEGEVENS['kvk']}</span>
          </td>
          <td style="vertical-align:top; text-align:right;">
            <span style="color:#3B3D57;">Factuurnummer</span><br>
            <strong>{factuurnr}</strong><br>
            <span style="color:#3B3D57;">Datum</span><br>
            {datum}
          </td>
        </tr>
      </table>

      <div style="font-size:12px; color:#3B3D57; margin-bottom:4px;">Aan</div>
      {klantregel}
      <div style="font-size:13px; color:#3B3D57; margin-bottom:18px;">{to_email}</div>

      <table style="width:100%; font-size:13.5px; border-top:1px solid #E4E2DA; padding-top:10px;">
        <tr><td style="padding:10px 0 6px;">{omschrijving}</td>
            <td style="padding:10px 0 6px; text-align:right;">&euro; {bedrag:.2f}</td></tr>
        {bedragen_html}
      </table>

      <div style="margin-top:16px;">{btw_regel}</div>
      <p style="font-size:12px; color:#3B3D57; margin:0;">Dit bedrag is al voldaan, je hoeft niets meer te doen.</p>
    </div>
    """
    html = _base_html("Je betaling is gelukt", "Bedankt voor je aankoop bij Krillo.", body)
    return send_email(to_email, f"Je factuur van Krillo ({factuurnr})", html)


def send_herroeping_bevestiging(to_email, nummer, webshop_url=None):
    """Bevestiging aan de klant dat zijn herroeping is ontvangen. Wettelijk
    verplicht om te bevestigen, en het geeft de klant iets in handen."""
    kenmerk = f"HR-{datetime.now().year}-{nummer:04d}" if nummer else "onbekend"
    shop = f"<p style='font-size:13.5px; color:#3B3D57;'>Betreft: {webshop_url}</p>" if webshop_url else ""
    body = f"""
    <p style="font-size:14.5px;">We hebben je herroeping ontvangen op {datetime.now().strftime('%d-%m-%Y')}.</p>
    <div style="background:#F6F5F1; border-radius:10px; padding:16px 18px; margin:16px 0;">
      <div style="font-family:'Courier New',monospace; font-size:11px; color:#3B3D57; text-transform:uppercase;">Kenmerk</div>
      <strong style="font-size:15px;">{kenmerk}</strong>
      {shop}
    </div>
    <p style="font-size:14.5px;">We handelen dit binnen veertien dagen af. Heb je al betaald en heb je recht op terugbetaling, dan storten we het bedrag terug via dezelfde betaalmethode als waarmee je hebt betaald. Je hoeft verder niets te doen.</p>
    <p style="font-size:13.5px; color:#3B3D57;">Klopt er iets niet, mail dan gewoon terug naar dit adres.</p>
    """
    html = _base_html("Je herroeping is ontvangen", "Bedankt voor je bericht.", body)
    return send_email(to_email, f"Bevestiging van je herroeping ({kenmerk})", html)


def send_herroeping_melding(beheerder_email, klant_email, webshop_url, toelichting, nummer):
    """Melding aan Nino, zodat een herroeping niet ongemerkt blijft liggen."""
    body = f"""
    <p style="font-size:14.5px;"><strong>Er is een herroeping binnengekomen.</strong></p>
    <p style="font-size:14px;">Kenmerk: HR-{datetime.now().year}-{nummer:04d}<br>
    Klant: {klant_email}<br>
    Webshop: {webshop_url or 'niet opgegeven'}</p>
    <p style="font-size:14px;">Toelichting: {toelichting or 'geen'}</p>
    <p style="font-size:13.5px; color:#3B3D57;">Wettelijke termijn: binnen veertien dagen afhandelen en eventueel terugbetalen via dezelfde betaalmethode.</p>
    """
    html = _base_html("Herroeping ontvangen", "Actie nodig.", body)
    return send_email(beheerder_email, "Herroeping bij Krillo, actie nodig", html)


def send_opzegging_bevestiging(to_email, webshop_url):
    body = f"""
    <p style="font-size:14.5px;">Je monitoring voor {webshop_url} is opgezegd.</p>
    <p style="font-size:14.5px;">Je houdt toegang tot het einde van de periode die je al betaald hebt. Daarna wordt er niets meer afgeschreven en stoppen de wekelijkse scans.</p>
    <p style="font-size:13.5px; color:#3B3D57;">Wil je later weer starten, dan kan dat gewoon via krillo.nl. Je oude rapporten blijven bewaard.</p>
    """
    html = _base_html("Je abonnement is opgezegd", "Bedankt dat je Krillo gebruikt hebt.", body)
    return send_email(to_email, "Bevestiging: je Krillo-abonnement is opgezegd", html)


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
      Dit is je nulmeting. Elke week scannen we opnieuw en krijg je bericht met de
      nieuwe stand, en een duidelijke waarschuwing als je score gedaald is. Je vindt je scoreverloop altijd terug op je eigen pagina,
      die op hetzelfde adres blijft staan. Bewaar de link hieronder.
    </p>
    {_score_button(report_url, "Open je monitoringpagina")}
    """
    html = _base_html(
        "Welkom bij Krillo monitoring",
        f"Je monitoring voor {webshop_url} is gestart.",
        body,
    )
    return send_email(to_email, "Welkom bij Krillo monitoring", html)


def send_weekly_update_email(to_email, webshop_url, scan_result, report_url=None, vorige_score=None):
    score = scan_result.get("score", 0)

    if vorige_score is None:
        onderwerp = f"Je wekelijkse Krillo-update ({score}/100)"
        kop = "Je wekelijkse update"
        melding = f"<p style='font-size:14.5px;'><strong>Huidige score: {score}/100</strong> voor {webshop_url}</p>"
    else:
        verschil = score - vorige_score
        if verschil < 0:
            onderwerp = f"Let op: je Krillo-score is gedaald naar {score}/100"
            kop = "Je score is gedaald"
            melding = f"""
            <div style="background:#FFE3E0; border-radius:10px; padding:16px 18px; margin-bottom:16px;">
              <strong style="font-size:15px; color:#993C1D;">Gedaald van {vorige_score} naar {score}</strong>
              <p style="font-size:13.5px; color:#993C1D; margin:6px 0 0;">
                Er is iets veranderd aan je website waardoor AI je shop minder goed kan lezen.
                Op je monitoringpagina zie je precies wat er nieuw is.
              </p>
            </div>
            """
        elif verschil > 0:
            onderwerp = f"Goed nieuws: je Krillo-score staat nu op {score}/100"
            kop = "Je score is gestegen"
            melding = f"""
            <div style="background:#DFF5F1; border-radius:10px; padding:16px 18px; margin-bottom:16px;">
              <strong style="font-size:15px; color:#085041;">Gestegen van {vorige_score} naar {score}</strong>
              <p style="font-size:13.5px; color:#085041; margin:6px 0 0;">
                Je aanpassingen werken. AI kan je webshop nu beter vinden en begrijpen.
              </p>
            </div>
            """
        else:
            onderwerp = f"Je wekelijkse Krillo-update ({score}/100)"
            kop = "Je wekelijkse update"
            melding = f"""
            <p style="font-size:14.5px;"><strong>Je score staat nog steeds op {score}/100</strong> voor {webshop_url}.
            Er is deze week niets veranderd.</p>
            """

    body = melding + _score_button(report_url, "Bekijk je monitoringpagina")
    html = _base_html(kop, f"De nieuwste scan voor {webshop_url}.", body)
    return send_email(to_email, onderwerp, html)
