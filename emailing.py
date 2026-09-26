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
- SMTP_FROM_EMAIL: het afzenderadres (standaard: hello@krilloai.com)
"""

from urllib.parse import quote
import html as _html
import os
import requests
from datetime import datetime

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_api_key():
    return os.environ.get("BREVO_API_KEY")


def send_email(to_email, subject, html_body, koppen=None):
    """Verstuurt een e-mail via de Brevo API. Geeft True/False terug, faalt
    nooit hard (een mislukte e-mail mag de rest van de afhandeling niet
    blokkeren).

    Met 'koppen' kan je extra mailkoppen meegeven, bijvoorbeeld de afmeldkop
    waar Gmail en Outlook hun eigen knop 'Afmelden' van maken."""
    api_key = _get_api_key()
    if not api_key:
        print("E-mail niet verstuurd: BREVO_API_KEY ontbreekt nog.")
        return False

    from_email = os.environ.get("SMTP_FROM_EMAIL", "hello@krilloai.com")

    # Waar een antwoord heen gaat. Onder elke mail staat "mail gewoon terug naar
    # dit adres", en dat moet waar zijn. Brevo verstuurt wel maar ontvangt niet:
    # zonder MX-records op krillo.nl komt een antwoord op hello@krilloai.com
    # nergens aan, en dan is een klantvraag stilletjes weg.
    #
    # Zet SMTP_REPLY_TO in Render op een adres dat je echt leest, bijvoorbeeld
    # je eigen Gmail, zolang de mailbox op het domein nog niet werkt. Staat hij
    # niet ingevuld, dan gaat een antwoord gewoon naar het afzenderadres, net
    # als voorheen.
    reply_to = (os.environ.get("SMTP_REPLY_TO") or "").strip()

    inhoud = {
        "sender": {"name": "Krillo", "email": from_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }
    if reply_to:
        inhoud["replyTo"] = {"name": "Krillo", "email": reply_to}
    if koppen:
        inhoud["headers"] = {str(k): str(v) for k, v in koppen.items() if v}

    try:
        response = requests.post(
            BREVO_API_URL,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            json=inhoud,
            timeout=15,
        )
        if response.status_code >= 300:
            print(f"E-mail versturen mislukt: {response.status_code} {response.text}")
            return False
        return True
    except Exception as e:
        print(f"E-mail versturen mislukt: {e}")
        return False


# ALLES ENGELS, SINDS 21 SEPTEMBER (stap 51).
#
# De taalregel van 18 september: een adres, een taal, en krilloai.com is
# Engels. Tot 21 september koos elke mail zijn taal op het domein van de winkel
# (.nl werd Nederlands). Dan kreeg iemand die op een Engelse site betaalde een
# Nederlandse factuur, een Nederlandse welkomstmail en een Nederlandse uitslag
# van de gratis test, met daaronder beloftes van het oude model. De mail is een
# deel van de site; hij spreekt dezelfde taal.
#
# Wat WEL in de taal van de markt blijft: de koopvragen zelf. Dat is de meting,
# en een Nederlandse koper stelt zijn vraag in het Nederlands. Een Engelse mail
# met een Nederlandse vraag erin is dus juist goed.
#
# De parameter taal blijft bestaan in de functies, zodat oude aanroepen niet
# omvallen. Hij verandert niets meer.

# De huisstijl van de site, in kleuren die ook in een mailprogramma werken.
# Zelfde namen als in _stijl.html, zodat je ze terugvindt.
INKT = "#0A0A0B"
INKT_ZACHT = "#4A4A55"
LIJN = "#E8E8EC"
VLAK = "#F4F5F8"
BLAUW = "#1B3FE0"
BLAUW_TEKST = "#142FA8"
GOED = "#0B7C5E"
MIS = "#B42318"

VOETTEKST = ("Questions? Just reply to this email, a person reads it.<br>"
             "Krillo &middot; Gerard Doustraat 22-3V, 1072 VW Amsterdam &middot; "
             "Chamber of Commerce 78439620")


def _base_html(title, intro, body_html, taal="en"):
    """Het kader om elke mail: het woordmerk, een kop, een inleiding, en de
    voettekst. Zelfde woordmerk als op de site (KRILLO met INDEX erachter), niet
    meer de rode stip van het ontwerp van voor 18 september."""
    return f"""
    <div style="background:#FFFFFF; padding:8px 0;">
    <div style="font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; max-width:560px;
                margin:0 auto; color:{INKT}; padding:0 16px;">
      <div style="padding:24px 0 8px;">
        <span style="font-weight:700; font-size:19px; letter-spacing:-0.04em; color:{INKT};">KRILLO</span>
        <span style="font-family:'Courier New', monospace; font-size:10.5px; color:#6E7079;
                     letter-spacing:0.1em; margin-left:6px;">INDEX</span>
      </div>
      <h1 style="font-size:22px; line-height:1.3; margin:22px 0 8px; letter-spacing:-0.01em;">{title}</h1>
      <p style="color:{INKT_ZACHT}; font-size:14.5px; line-height:1.6; margin:0 0 18px;">{intro}</p>
      {body_html}
      <p style="color:{INKT_ZACHT}; font-size:12.5px; line-height:1.6; margin-top:36px;
                padding-top:16px; border-top:1px solid {LIJN};">
        {VOETTEKST}
      </p>
    </div>
    </div>
    """


def _p(tekst, zacht=False):
    """Een gewone alinea. Op een plek, zodat elke mail dezelfde maat en
    regelafstand heeft."""
    kleur = INKT_ZACHT if zacht else INKT
    maat = "13.5px" if zacht else "14.5px"
    return f'<p style="font-size:{maat}; line-height:1.6; color:{kleur}; margin:0 0 14px;">{tekst}</p>'


BEDRIJFSGEGEVENS = {
    "naam": "Krillo",
    "adres": "Gerard Doustraat 22-3V",
    "plaats": "1072 VW Amsterdam",
    "kvk": "78439620",
    "btw": "NL855820627B01",
    "email": "hello@krilloai.com",
}


def send_factuur_email(to_email, factuurnummer, omschrijving, bedrag, bedrijfsnaam=None, datum=None):
    """Stuurt een betaalbevestiging met factuur. Of er btw op staat hangt af van
    de instelling BTW_REGELING in Render: 'kor' betekent geen btw berekenen
    (kleineondernemersregeling), 'btw' betekent wel. Zet die op 'btw' zodra je
    boven de KOR-grens komt, dan verandert de factuur vanzelf mee.

    In het Engels sinds 21 september. Een Engelse factuur van een Nederlandse
    onderneming is gewoon geldig; wat erop moet staan (nummer, datum, KVK,
    bedragen en de reden dat er geen btw op staat) staat er."""
    regeling = os.environ.get("BTW_REGELING", "kor").lower()
    datum = datum or datetime.now().strftime("%d-%m-%Y")
    factuurnr = f"KR-{datetime.now().year}-{factuurnummer:04d}"

    if regeling == "btw":
        excl = round(bedrag / 1.21, 2)
        btw_bedrag = round(bedrag - excl, 2)
        bedragen_html = f"""
        <tr><td style="padding:6px 0; color:{INKT_ZACHT};">Amount excluding VAT</td>
            <td style="padding:6px 0; text-align:right;">&euro; {excl:.2f}</td></tr>
        <tr><td style="padding:6px 0; color:{INKT_ZACHT};">VAT 21%</td>
            <td style="padding:6px 0; text-align:right;">&euro; {btw_bedrag:.2f}</td></tr>
        <tr><td style="padding:10px 0 0; border-top:1px solid {LIJN};"><strong>Total paid</strong></td>
            <td style="padding:10px 0 0; border-top:1px solid {LIJN}; text-align:right;"><strong>&euro; {bedrag:.2f}</strong></td></tr>
        """
        btw_regel = f"<p style='font-size:12px; color:{INKT_ZACHT};'>VAT number: {BEDRIJFSGEGEVENS['btw']}</p>"
    else:
        bedragen_html = f"""
        <tr><td style="padding:10px 0 0;"><strong>Total paid</strong></td>
            <td style="padding:10px 0 0; text-align:right;"><strong>&euro; {bedrag:.2f}</strong></td></tr>
        """
        btw_regel = (f"<p style='font-size:12px; color:{INKT_ZACHT};'>No VAT charged under the "
                     f"Dutch small business scheme (kleineondernemersregeling).</p>")

    klantregel = (f"<div style='font-size:13px; color:{INKT_ZACHT};'>{veilig(bedrijfsnaam)}</div>"
                  if bedrijfsnaam else "")

    body = _p("Your payment went through. Your invoice is below; keep it for your records.") + f"""
    <div style="border:1px solid {LIJN}; border-radius:12px; padding:22px; margin:18px 0;">
      <table style="width:100%; font-size:13px; margin-bottom:18px;">
        <tr>
          <td style="vertical-align:top;">
            <strong style="font-size:14px;">{BEDRIJFSGEGEVENS['naam']}</strong><br>
            <span style="color:{INKT_ZACHT};">{BEDRIJFSGEGEVENS['adres']}<br>
            {BEDRIJFSGEGEVENS['plaats']}, the Netherlands<br>
            Chamber of Commerce {BEDRIJFSGEGEVENS['kvk']}</span>
          </td>
          <td style="vertical-align:top; text-align:right;">
            <span style="color:{INKT_ZACHT};">Invoice number</span><br>
            <strong>{factuurnr}</strong><br>
            <span style="color:{INKT_ZACHT};">Date</span><br>
            {datum}
          </td>
        </tr>
      </table>

      <div style="font-size:12px; color:{INKT_ZACHT}; margin-bottom:4px;">To</div>
      {klantregel}
      <div style="font-size:13px; color:{INKT_ZACHT}; margin-bottom:18px;">{veilig(to_email)}</div>

      <table style="width:100%; font-size:13.5px; border-top:1px solid {LIJN}; padding-top:10px;">
        <tr><td style="padding:10px 0 6px;">{veilig(omschrijving)}</td>
            <td style="padding:10px 0 6px; text-align:right;">&euro; {bedrag:.2f}</td></tr>
        {bedragen_html}
      </table>

      <div style="margin-top:16px;">{btw_regel}</div>
      <p style="font-size:12px; color:{INKT_ZACHT}; margin:0;">This amount has already been paid. You do not need to do anything.</p>
    </div>
    """
    html = _base_html("Your payment went through", "Thank you for choosing Krillo.", body)
    return send_email(to_email, f"Your Krillo invoice ({factuurnr})", html)


def send_herroeping_bevestiging(to_email, nummer, webshop_url=None):
    """Bevestiging aan de klant dat zijn herroeping is ontvangen. Wettelijk
    verplicht om te bevestigen, en het geeft de klant iets in handen.

    In het Engels sinds 21 september, net als het formulier op /herroepen.
    Een Engels formulier met een Nederlandse bevestiging erachter is precies
    het soort breuk waardoor iemand gaat twijfelen of het wel aangekomen is."""
    kenmerk = f"HR-{datetime.now().year}-{nummer:04d}" if nummer else "unknown"
    shop = f"<p style='font-size:13.5px; color:{INKT_ZACHT};'>Concerning: {veilig(webshop_url)}</p>" if webshop_url else ""
    body = f"""
    <p style="font-size:14.5px;">We received your withdrawal on {datetime.now().strftime('%d-%m-%Y')}.</p>
    <div style="background:{VLAK}; border-radius:10px; padding:16px 18px; margin:16px 0;">
      <div style="font-family:'Courier New',monospace; font-size:11px; color:{INKT_ZACHT}; text-transform:uppercase;">Reference</div>
      <strong style="font-size:15px;">{kenmerk}</strong>
      {shop}
    </div>
    <p style="font-size:14.5px;">We handle this within fourteen days. If you already paid and are entitled to a refund, we pay it back through the same payment method you used. You do not have to do anything else.</p>
    <p style="font-size:13.5px; color:{INKT_ZACHT};">Something not right? Just reply to this email.</p>
    """
    html = _base_html("We received your withdrawal", "Thank you for your message.", body)
    return send_email(to_email, f"Confirmation of your withdrawal ({kenmerk})", html)


def veilig(tekst):
    """Maakt tekst van buiten onschadelijk voordat hij in een mail komt.

    Waarom dit nodig is: bij een herroeping mag iemand een vrije toelichting
    typen, en die kwam ongefilterd in de HTML van de mail aan de beheerder
    terecht. Iemand kon daar dus een link in zetten die eruitziet alsof hij van
    Krillo zelf komt, of een plaatje dat meldt wanneer de mail gelezen wordt.
    Dat is phishing in je eigen postvak, en het is met een regel te voorkomen."""
    return _html.escape(str(tekst)) if tekst is not None else ""


def send_herroeping_melding(beheerder_email, klant_email, webshop_url, toelichting, nummer):
    """Melding aan Nino, zodat een herroeping niet ongemerkt blijft liggen."""
    body = f"""
    <p style="font-size:14.5px;"><strong>Er is een herroeping binnengekomen.</strong></p>
    <p style="font-size:14px;">Kenmerk: HR-{datetime.now().year}-{nummer:04d}<br>
    Klant: {veilig(klant_email)}<br>
    Webshop: {veilig(webshop_url) or 'niet opgegeven'}</p>
    <p style="font-size:14px;">Toelichting: {veilig(toelichting) or 'geen'}</p>
    <p style="font-size:13.5px; color:#3B3D57;">Wettelijke termijn: binnen veertien dagen afhandelen en eventueel terugbetalen via dezelfde betaalmethode.</p>
    """
    html = _base_html("Herroeping ontvangen", "Actie nodig.", body)
    return send_email(beheerder_email, "Herroeping bij Krillo, actie nodig", html)


def send_opzegging_bevestiging(to_email, webshop_url):
    """De bevestiging van een opzegging. Kort, en zonder poging om iemand
    over te halen: wie opzegt en dan een verkoopmail krijgt, komt niet terug."""
    winkel = _kaal_adres(webshop_url)
    body = (
        _p(f"Your subscription for <strong>{veilig(winkel)}</strong> has been cancelled.")
        + _p("Nothing more is charged from now on, and you will not get your monthly "
             "position email anymore. Your dashboard link keeps working, with your last "
             "measurement on it.")
        + _p("Want to start again later? You can, at krilloai.com.", zacht=True)
    )
    html = _base_html("Your subscription is cancelled", "Thank you for using Krillo.", body)
    return send_email(to_email, "Confirmation: your Krillo subscription is cancelled", html)


def _score_button(report_url, label="Open your dashboard"):
    """De knop. Blauw, zoals op de site, en een gewone link eronder voor wie
    in een mailprogramma zit dat knoppen niet goed toont."""
    if not report_url:
        return ""
    return f"""
    <p style="margin:22px 0 6px;">
      <a href="{report_url}" style="display:inline-block; background:{BLAUW}; color:#FFFFFF;
         text-decoration:none; padding:12px 22px; border-radius:8px; font-weight:600;
         font-size:14px;">{label} &rarr;</a>
    </p>
    """


def send_audit_email(to_email, webshop_url, scan_result, fix_previews, report_url=None, taal="nl"):
    score = scan_result.get("score", 0)
    problemen = [c for c in scan_result.get("checks", []) if c["status"] != "ok"]
    score_color = "#1FB6A4" if score >= 80 else ("#C77D00" if score >= 40 else MIS)
    engels = True  # sinds 21 september: alle mails Engels

    if engels:
        kopje = "AI readability"
        intro_line = (
            f"We found {len(problemen)} points to improve and put {len(fix_previews)} ready made "
            f"fixes together for you."
            if problemen else
            "Strong result: there was hardly anything to improve."
        )
        tweede = ("All findings and the ready made fixes are set out on your own report page.")
        knop = "See the full report"
        titel = "Your Krillo audit is ready"
        intro = f"Here is the audit for {webshop_url}."
        onderwerp = "Your Krillo audit is ready"
    else:
        kopje = "AI-leesbaarheid"
        intro_line = (
            f"We hebben {len(problemen)} verbeterpunten gevonden en {len(fix_previews)} concrete oplossingen voor je klaargezet."
            if problemen else
            "Sterk resultaat: er waren nauwelijks verbeterpunten te vinden."
        )
        tweede = "Alle bevindingen en de kant-en-klare oplossingen staan overzichtelijk op je eigen rapportpagina."
        knop = "Bekijk het volledige rapport"
        titel = "Je Krillo-audit is klaar"
        intro = f"Hierbij de audit voor {webshop_url}."
        onderwerp = "Je Krillo-audit is klaar"

    body = f"""
    <div style="background:#12142B; border-radius:12px; padding:24px; margin-bottom:20px; text-align:center;">
      <div style="font-family:'Courier New',monospace; font-size:11px; color:#8B8DA8; text-transform:uppercase; margin-bottom:8px;">{kopje}</div>
      <div style="font-size:40px; font-weight:700; color:{score_color};">{score}<span style="font-size:18px; color:#8B8DA8;">/100</span></div>
      <div style="font-size:13px; color:#B9BBD4; margin-top:4px;">{webshop_url}</div>
    </div>
    <p style="font-size:14.5px;">{intro_line}</p>
    <p style="font-size:14.5px;">{tweede}</p>
    {_score_button(report_url, knop)}
    """
    html = _base_html(titel, intro, body, taal=taal)
    return send_email(to_email, onderwerp, html)


# Hoe iemand ons toegang geeft, per platform. Dit is de belangrijkste tekst van
# het hele product: hier haakt een klant af die net betaald heeft. Daarom overal
# de echte menunamen en nooit "ga naar de instellingen".
TOEGANG_UITLEG = {
    # De menunamen in het Engels, met de Nederlandse naam erachter waar het
    # beheerscherm van een Nederlandse winkel meestal in het Nederlands staat.
    # Een klant zoekt op wat hij op zijn scherm ziet, niet op wat wij schrijven.
    "Shopify": """
      <li>We send you a collaborator request. That is the standard way agencies
          work in a Shopify store.</li>
      <li>Shopify emails you about it. Click approve.</li>
      <li>If your admin shows a four digit collaborator code under Settings, Users
          (Instellingen, Gebruikers), we need that code. Just reply with it.</li>
      <li>You decide which parts we can see, and you can remove our access in one
          click. It does not count towards your staff accounts and costs you nothing.</li>""",
    "WooCommerce": """
      <li>In WordPress, go to Users, Add New User (Gebruikers, Nieuwe gebruiker).</li>
      <li>Create a user for access@krilloai.com with the role Administrator (Beheerder).</li>
      <li>Tick the box that sends the new user an email.</li>
      <li>When we are done, you can simply delete that user.</li>""",
    "WordPress": """
      <li>In WordPress, go to Users, Add New User (Gebruikers, Nieuwe gebruiker).</li>
      <li>Create a user for access@krilloai.com with the role Administrator (Beheerder).</li>
      <li>Tick the box that sends the new user an email.</li>
      <li>When we are done, you can simply delete that user.</li>""",
    "Lightspeed": """
      <li>In your Lightspeed admin, go to Settings, Users (Instellingen, Gebruikers).</li>
      <li>Add a new user and fill in access@krilloai.com.</li>
      <li>Give that user rights to products, pages and settings. We do not need
          rights to orders or customers, so please do not give them.</li>
      <li>When we are done, you can delete the user.</li>""",
    "Shopware": """
      <li>In your Shopware admin, go to Settings, System, Users &amp; permissions.</li>
      <li>Create a user for access@krilloai.com.</li>
      <li>Give that user rights to products and content. Orders and customers are
          not needed.</li>
      <li>When we are done, you can delete the user.</li>""",
    "CCV Shop": """
      <li>In your CCV Shop admin, go to Settings, Users (Instellingen, Gebruikers).</li>
      <li>Create a user for access@krilloai.com.</li>
      <li>Give that user rights to products and pages. Orders and customers are
          not needed.</li>
      <li>When we are done, you can delete the user.</li>""",
    "PrestaShop": """
      <li>In your PrestaShop admin, go to Advanced Parameters, Team
          (Geavanceerde instellingen, Team).</li>
      <li>Create an employee for access@krilloai.com.</li>
      <li>Give that employee rights to catalog and design. Orders and customers
          are not needed.</li>
      <li>When we are done, you can delete the employee.</li>""",
}

TOEGANG_ALGEMEEN = """
      <li>Give us an account in the admin of your store, with enough rights to
          change texts and pages. Our address is access@krilloai.com.</li>
      <li>Not sure how? Reply with the name of your store software and we send
          you the steps for your system.</li>
      <li>Does a developer manage your site? Forward this email to them. We
          sort out the rest with them.</li>"""


def send_uitvoering_welkom(to_email, webshop_url, platform=None, monitoring_url=None):
    """De mail waarin we om toegang vragen. Gaat alleen naar Fix (en naar de
    oude eenmalige uitvoering); Watch doet het werk zelf en krijgt hem niet.

    Deze mail heeft een taak: zorgen dat we toegang krijgen. Zonder toegang
    staat de opdracht stil terwijl de klant wel betaalt. Daarom staat er een
    vraag in en verder niets."""
    winkel = _kaal_adres(webshop_url)
    stappen = TOEGANG_UITLEG.get(platform or "", TOEGANG_ALGEMEEN)
    platform_zin = (
        f"Your store runs on {platform}, so this is how it works for you:"
        if platform in TOEGANG_UITLEG else
        "This is how you give us access:"
    )
    body = (
        _p(f"Your payment came through. We start on <strong>{veilig(winkel)}</strong> as "
           f"soon as we can get into your store.")
        + _p(f"<strong>{platform_zin}</strong>")
        + f'<ul style="font-size:14px; color:{INKT_ZACHT}; line-height:1.7; padding-left:20px; margin:0 0 16px;">{stappen}</ul>'
        + _p("Once we are in, you will not hear from us until it is done. That usually "
             "takes two to five working days. Then you get an overview of exactly what "
             "changed and what the old text was, so you can put anything back.")
        + _p("We never touch your prices, stock, orders or design. Only the texts and "
             "settings that help AI read your store.", zacht=True)
        + (_score_button(monitoring_url, "Open your dashboard") if monitoring_url else "")
    )
    html = _base_html("One thing we need from you",
                      f"Thank you for your order for {veilig(winkel)}.", body)
    return send_email(to_email, "Krillo: we need access to your store", html)


def _veilig(tekst, maxlengte=1200):
    """Zet tekst veilig in een HTML-mail.

    Wat hier binnenkomt is door een mens ingetypt en komt deels uit de webshop
    van de klant, dus er kunnen gewoon punthaken in staan. Zonder dit zou een
    stukje HTML uit een productomschrijving de opmaak van de mail slopen."""
    if not tekst:
        return ""
    kort = str(tekst).strip()
    afgekapt = len(kort) > maxlengte
    kort = kort[:maxlengte]
    veilig = (kort.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
              .replace('"', "&quot;").replace("\n", "<br>"))
    return veilig + ("<br>[ingekort]" if afgekapt else "")


def send_oplevering(to_email, webshop_url, wijzigingen, monitoring_url=None):
    """Het overzicht van wat wij in de webshop veranderd hebben.

    Per wijziging staat erbij wat er nu staat en wat er stond. Dat laatste is
    geen extraatje: we hebben beloofd dat de klant alles kan terugzetten, en
    zonder de oude tekst kan hij dat niet."""
    if not wijzigingen:
        print("Oplevering niet verstuurd: er is niets vastgelegd.")
        return False
    winkel = _kaal_adres(webshop_url)

    blokken = []
    for i, w in enumerate(wijzigingen, start=1):
        oud = _veilig(w.get("oude_waarde"))
        nieuw = _veilig(w.get("nieuwe_waarde"))
        blokken.append(f"""
        <div style="border:1px solid {LIJN}; border-radius:10px; padding:16px 18px; margin-bottom:14px;">
          <div style="font-weight:600; font-size:15px; margin-bottom:4px;">{i}. {_veilig(w.get('wat'), 200)}</div>
          {f'<div style="font-size:13px; color:{INKT_ZACHT}; margin-bottom:10px;">Where: {_veilig(w.get("waar"), 300)}</div>' if w.get('waar') else ''}
          {f'<div style="font-size:13px; margin-bottom:8px;"><strong>What is there now:</strong><br>{nieuw}</div>' if nieuw else ''}
          <div style="font-size:13px; color:{INKT_ZACHT};"><strong>What was there:</strong><br>
            {oud if oud else '<em>Nothing was here yet, this is new.</em>'}</div>
        </div>""")

    body = (
        _p(f"We are done with <strong>{veilig(winkel)}</strong>. Below is exactly what we "
           f"changed, and what was there before we started.")
        + "".join(blokken)
        + _p("Want something back the way it was? The old text is above. You can put it "
             "back yourself, or reply to this email and we do it.")
        + _p("We did not change your prices, stock, orders or design. It takes a few weeks "
             "before AI models pick up new texts, so do not expect a different answer "
             "tomorrow. At the next monthly measurement of your category we show you the "
             "difference.", zacht=True)
        + (_score_button(monitoring_url, "Open your dashboard") if monitoring_url else "")
    )
    html = _base_html("Your store is done",
                      f"The overview of what we did for {veilig(winkel)}.", body)
    return send_email(to_email, f"Done: what we changed on {winkel}", html)


def _kaal_adres(webshop_url):
    """voorbeeldwinkel.nl in plaats van https://www.voorbeeldwinkel.nl/

    Klein, maar dit is precies het soort detail waaraan iemand ziet dat een
    mail uit een machine komt. Een mens typt geen https:// in een zin."""
    adres = (webshop_url or "").strip()
    for weg in ("https://", "http://"):
        if adres.startswith(weg):
            adres = adres[len(weg):]
    if adres.startswith("www."):
        adres = adres[4:]
    return adres.rstrip("/")


# DE TWEE VERSIES VAN DE KOUDE MAIL (stap 56, 24 september).
# Nino wilde "survival of the fittest": versies laten strijden en de zwakke
# laten afvallen. Bij vijf mails per dag is dat eerlijk gezegd nog geen
# evolutie maar een simpele vergelijking van twee onderwerpregels. Zodra er per
# versie genoeg verstuurd is, zet het beheerscherm erbij welke wint, en dan
# zet je in Render MAIL_VARIANTEN op alleen de winnaar (en later een nieuwe
# uitdager ernaast). Het verschil zit bewust alleen in de onderwerpregel en de
# eerste zin: verander je alles tegelijk, dan weet je niet wat werkte.
#   a: de positie voorop    "shop.nl: #6 of 54 in the Krillo index"
#   b: de vraag voorop      "Who AI recommends for Toys in the Netherlands"
MAILVARIANTEN = ("a", "b")


def kies_variant(webshop_url):
    """Welke versie een winkel krijgt. Vast per winkel (zelfde adres, zelfde
    versie), zodat een tweede mail aan dezelfde winkel nooit de telling
    vervuilt. Welke versies meedoen staat in MAIL_VARIANTEN (Render),
    standaard allebei."""
    import hashlib
    actief = [v.strip() for v in (os.environ.get("MAIL_VARIANTEN") or "a,b").split(",")
              if v.strip() in MAILVARIANTEN] or ["a"]
    getal = int(hashlib.sha256((webshop_url or "").encode()).hexdigest(), 16)
    return actief[getal % len(actief)]


# In welke taal wij de koopvragen stelden, voor het labeltje boven de vraag.
# Een Nederlandse vraag in een Engelse mail zonder uitleg leest als een fout.
_TAALNAAM = {"nl": "Dutch", "de": "German", "fr": "French", "en": "English",
             "es": "Spanish", "it": "Italian"}


def send_onderzoeksmail(to_email, webshop_url, link_url, beeld=None,
                        categorienaam=None, landnaam=None, afmeld_url=None,
                        onderwerp_voor="", variant="a"):
    """De koude mail aan een winkel die in de Krillo index staat.

    OMGEBOUWD 23 SEPTEMBER (stap 36). Dit was de laatste mail uit het oude
    model: Nederlands, met een eigen meting van de winkel ("genoemd bij 0 van
    de 5 vragen") en een link naar een eigen uitkomstpagina. Nu:
    - Engels, zoals alle mail (een adres, een taal);
    - de POSITIE van de winkel in zijn categorie en land, uit dezelfde
      maandmeting als de openbare ranglijst. Nooit een tweede cijfer;
    - een echte vraag waar hij ontbrak, met wie er wel genoemd werd. Alleen
      winkels, geen platforms: "bol.com werd genoemd in plaats van jou" klopt
      niet, bol.com is geen concurrent;
    - de link gaat naar de openbare ranglijst (via /uitkomst/<kenmerk>, zodat
      wij tellen dat hij geopend is).
    Zonder positie gaat er GEEN mail uit. Een koude mail zonder uitkomst is
    reclame, en daar hebben wij geen recht op.

    Wat hetzelfde bleef, en waarom:
    Iemand die niet om post vroeg beslist in twee seconden of het oplichterij
    is. Dus kaal: geen logo, geen kleuren, een gewone knop met eronder waar hij
    heen gaat (hetzelfde domein als de afzender). Een naam onderaan
    (AFZENDER_NAAM in Render) maakt een mail beantwoordbaar. En de afmeldlink
    is niet optioneel: een afmelding kost een adres, een spamklacht het domein."""
    if not to_email or not link_url or not beeld or not beeld.get("positie"):
        print("Onderzoeksmail niet verstuurd: adres, link of positie ontbreekt.")
        return False

    e = _html.escape
    winkel = e(_kaal_adres(webshop_url))
    cat = e(categorienaam or beeld.get("categorie") or "your category")
    land = e(landnaam or (beeld.get("land") or "").upper())
    positie, van = beeld["positie"], beeld.get("van") or 0
    genoemd, telbaar = beeld.get("genoemd") or 0, beeld.get("telbaar") or 0

    naam = (os.environ.get("AFZENDER_NAAM") or "").strip()
    ondertekening = (f'<p style="font-size:14.5px; color:#12142B; margin:22px 0 0;">'
                     f'Kind regards,<br>{e(naam)}</p>') if naam else ""

    if afmeld_url:
        afmelden = (f'Rather not hear about this? Use '
                    f'<a href="{afmeld_url}" style="color:#6B6D85;">this link</a>: one click, '
                    f'no questions. You get no more email from us, and we take your store '
                    f'out of the public index.')
    else:
        afmelden = ("Rather not hear about this? Reply to this email and we remove you "
                    "the same day.")

    g = BEDRIJFSGEGEVENS
    afzender = os.environ.get("SMTP_FROM_EMAIL", "hello@krilloai.com")

    # De regel onder het cijfer: per vraag geteld, niet in procenten (bij
    # dertig vragen suggereert een procent een precisie die er niet is).
    if genoemd == 0:
        onder = f"AI named {winkel} in none of the {telbaar} buying questions."
    else:
        onder = f"AI named {winkel} in {genoemd} of {telbaar} buying questions."
    boven = (beeld.get("boven_mij") or [])[-1:]
    if boven:
        r = boven[0]
        bnaam = r.get("naam") if (r.get("naam") and not str(r.get("naam")).startswith("http")) \
            else _kaal_adres(r.get("webshop_url") or "")
        onder += f" Just ahead of you: {e(bnaam)} (#{r.get('positie')})."

    # Een echte vraag uit de meting. Uitleggen wat een koopvraag is kost de
    # twee seconden die deze mail krijgt; er een laten zien niet.
    voorbeeld = ""
    for v in beeld.get("gemiste_vragen") or []:
        namen = [n for n in (v.get("concurrenten") or []) if n][:2]
        if v.get("vraag") and namen:
            regels = "".join(
                f'<tr><td style="padding:4px 0; font-size:14.5px; color:#12142B;">'
                f'<span style="color:#1FB6A4; font-weight:700;">&#10003;</span>'
                f'&nbsp;&nbsp;{e(n)}</td></tr>' for n in namen)
            # Hoofdletter voorop: de vragen staan zoals een koper ze typt
            # ("beste speelgoedwinkel online"), maar in een mail leest een
            # kleine letter aan het begin als slordig.
            vraag = v["vraag"].strip()
            vraag = vraag[:1].upper() + vraag[1:]
            try:
                import sitetaal
                taalnaam = _TAALNAAM.get(sitetaal.taal_van_land(beeld.get("land")), "")
            except Exception:
                taalnaam = ""
            taaldeel = f", in {taalnaam}" if taalnaam and taalnaam != "English" else ""
            # Nummer 1 (24 september, na de proefmail over mediamarkt.nl): "#1 of
            # 42" met daaronder een rood kruis leest als een tegenspraak. Wel
            # eerlijk laten zien, want ook nummer 1 mist vragen, maar met een kop
            # die zegt waarom je het ziet.
            if positie == 1:
                label = f"Even at #1: a question where you were missing{taaldeel}"
            else:
                label = f"One of the questions we asked{taaldeel}"
            regels += (f'<tr><td style="padding:4px 0; font-size:14.5px; color:#D42E22; '
                       f'font-weight:600;"><span style="font-weight:700;">&#10005;</span>'
                       f'&nbsp;&nbsp;{winkel} was not named</td></tr>')
            voorbeeld = f"""
          <div style="font-size:11.5px; color:#6B6D85; letter-spacing:.06em;
                      text-transform:uppercase; margin:22px 0 10px;">
            {e(label)}</div>
          <table role="presentation" cellpadding="0" cellspacing="0">
            <tr><td style="background:#F6F5F1; border-radius:14px 14px 14px 4px;
                           padding:12px 16px; font-size:15.5px; font-weight:600;
                           color:#12142B; line-height:1.4;">{e(vraag)}</td></tr>
          </table>
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                 style="margin-top:12px;">{regels}</table>"""
            break

    zichtbaar = e(_kaal_adres(link_url).split("/")[0])

    # Nummer 1 heeft niets te repareren maar wel iets te verliezen. Een zin
    # erbij, zoals de balk op de ranglijst dat ook zegt.
    bij_een = ("Staying #1 is the hard part: the ranking is measured again every month, "
               "and the stores below you are moving too. ") if positie == 1 else ""

    # De eerste zin verschilt per versie, de rest niet (zie MAILVARIANTEN).
    p = '<p style="font-size:15px; color:#12142B; line-height:1.65; margin:0 0 14px;">'
    if variant == "b":
        opening = (f"{p}When shoppers in {land} ask ChatGPT or Gemini where to buy "
                   f"in the {cat} category, a few stores get named and the rest do not. We ask those "
                   f"questions every month and rank the stores. {winkel} is in that "
                   f"ranking.</p>")
    else:
        opening = (f"{p}Every month we ask ChatGPT and Gemini the questions shoppers in {land} "
                   f"ask in the {cat} category, and we rank the stores they name. "
                   f"{winkel} is in that ranking.</p>")

    html = f"""
    <div style="background:#F6F5F1; padding:28px 16px; font-family:-apple-system,
                'Segoe UI', Arial, sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="max-width:560px; margin:0 auto;">
        <tr><td style="background:#FFFFFF; border:1px solid #E4E2DA; border-radius:14px;
                       padding:32px 30px;">

          <div style="font-size:14px; font-weight:700; color:#12142B; letter-spacing:.08em;">
            KRILLO <span style="font-weight:400; color:#6B6D85; font-size:11px;
            letter-spacing:.12em;">INDEX</span></div>
          <div style="font-size:12px; color:#6B6D85; margin-top:2px;">
            The Krillo index: which stores AI recommends</div>

          <div style="height:1px; background:#E4E2DA; margin:20px 0 22px;"></div>

          {opening}

          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                 style="border:1px solid #E4E2DA; border-radius:10px; margin:22px 0;">
            <tr><td style="padding:20px 22px;">
              <div style="font-size:12px; color:#3B3D57; letter-spacing:.04em;
                          text-transform:uppercase; margin-bottom:8px;">
                Your place in {cat}, {land}</div>
              <div style="font-size:30px; font-weight:700; color:#12142B; line-height:1.2;">
                #{positie} of {van}</div>
              <div style="font-size:13.5px; color:#3B3D57; margin-top:8px; line-height:1.55;">
                {onder}</div>
              {voorbeeld}
            </td></tr>
          </table>

          <p style="font-size:15px; color:#12142B; line-height:1.65; margin:0 0 6px;">
            {bij_een}The full ranking, and how we measured it, is on a public page. No login, and
            nothing to fill in.</p>

          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 8px;">
            <tr><td style="background:#1B3FE0; border-radius:8px;">
              <a href="{link_url}" style="display:inline-block; padding:13px 26px;
                 color:#FFFFFF; text-decoration:none; font-size:14.5px; font-weight:600;">
                See the full ranking</a>
            </td></tr>
          </table>
          <p style="font-size:12.5px; color:#6B6D85; margin:0 0 4px;">
            The link goes to {zichtbaar}</p>
          {ondertekening}

          <div style="height:1px; background:#E4E2DA; margin:26px 0 16px;"></div>

          <p style="font-size:12.5px; color:#6B6D85; line-height:1.7; margin:0;">
            You get this email because your store is in the Krillo index. We only used
            public information and the answers AI gave; we changed nothing on your website.
            {afmelden}<br><br>
            {g['naam']} &middot; {g['adres']}, {g['plaats']} &middot; KVK {g['kvk']}<br>
            Replies reach us at {afzender}.</p>

        </td></tr>
      </table>
    </div>
    """
    koppen = {"List-Unsubscribe": f"<{afmeld_url}>",
              "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"} if afmeld_url else None
    if variant == "b":
        # De categorienaam blijft in de taal van het land (zo staat hij ook op
        # de ranglijst), dus als naam achter een dubbele punt, niet in een zin.
        onderwerp = f"{onderwerp_voor}Who AI recommends: {categorienaam or beeld.get('categorie') or 'your category'}" \
                    + (f" in {landnaam}" if landnaam else "")
    else:
        onderwerp = f"{onderwerp_voor}{_kaal_adres(webshop_url)}: #{positie} of {van} in the Krillo index"
    return send_email(to_email, onderwerp, html, koppen=koppen)


def send_monitoring_welcome_email(to_email, webshop_url, scan_result, report_url=None,
                                  taal="en", pakket="fix"):
    """De welkomstmail na de eerste betaling van Watch of Fix.

    HERSCHREVEN 21 SEPTEMBER. Hiervoor heette dit "Welcome to Krillo monitoring"
    en beloofde hij het model van voor de index: elke week meten, elke week
    hoogstens drie dingen uitvoeren, en voor iedereen een aanvraag om toegang.
    Nu:
    - de naam van het pakket dat iemand echt kocht;
    - de maandmeting van zijn categorie, want daar komt zijn positie vandaan;
    - de wekelijkse scan van de dertien punten, want die draait wel wekelijks;
    - bij Fix dat er een aparte mail over toegang komt, bij Watch dat de
      oplossingen klaarstaan om zelf te doen. Watch krijgt geen toegangsmail.

    De eerste eigen meting bij de start (dertig koopvragen, ongeveer een
    kwartier) is gebleven: een nieuwe klant moet meteen iets zien."""
    winkel = _kaal_adres(webshop_url)
    score = (scan_result or {}).get("score", 0)
    is_watch = (pakket or "").lower() == "watch"
    # Het pakket voor merken en bureaus doet het werk, net als Fix, maar heet
    # anders. Hier stond eerst "Fix" voor alles wat geen Watch was.
    naam = {"watch": "Watch", "merken": "for brands and agencies"}.get(
        (pakket or "").lower(), "Fix")

    if is_watch:
        werk = _p("<strong>Your fixes.</strong> From your first measurement your dashboard "
                  "shows at most three fixes that gain you the most, written out for your "
                  "store: the text ready to copy, and where it goes in your own admin.")
    else:
        werk = (
            _p("<strong>Your fixes, installed.</strong> From your first measurement we pick at "
               "most three fixes that gain you the most, and we install them in your store. "
               "Every change keeps the old text, so it can always be put back.")
            + _p("For that we need access to your store. You get a separate email with the "
                 "steps for your platform. Would you rather do it yourself? That is fine too: "
                 "your dashboard shows every fix ready to copy.", zacht=True)
        )

    # Wat het dashboard na een kwartier laat zien is het werk (de oplossingen).
    # De cijfers en de winkels boven je komen uit de maandmeting van je
    # categorie. Hier stond eerst dat die er na een kwartier al zouden staan
    # (gevonden bij de controle van 21 september).
    dashboard = ("Your dashboard is at the button below. There is no password: the link is "
                 "your key, so keep this email." if report_url else
                 "We email you the link to your dashboard separately.")
    body = (
        _p(f"Welcome. Your {naam} plan for <strong>{veilig(winkel)}</strong> has started. "
           f"{dashboard}")
        + _p("<strong>Right now.</strong> We are running your first measurement: thirty "
             "buying questions that shoppers in your category really ask, put to ChatGPT and "
             "Gemini. That takes about fifteen minutes, and then your first fixes are on your "
             "dashboard. Your rank, how often you are named and which stores come out ahead "
             "of you appear once your category has been measured; for a category we do not "
             "measure yet, that can take a few days.")
        + _p("<strong>Every month.</strong> We measure your whole category again, and that is "
             "where your rank in the index comes from. You get a message with your position, "
             "and a message when you drop three places or more. Your store also gets the "
             "thirteen technical checks every week"
             # Alleen een cijfer als de scan gelukt is (23 september). Mislukt
             # hij bij de start, dan gaat de klant toch door en stond hier
             # anders "0 of 100", terwijl er niets gemeten was.
             + (f"; it scores {score} of 100 on them today." if (scan_result or {}).get("checks")
                else "; the first one follows within a week."))
        + werk
        + _score_button(report_url, "Open your dashboard")
    )
    html = _base_html(f"Welcome to Krillo {naam}", "Thank you for choosing Krillo.", body)
    return send_email(to_email, f"Welcome to Krillo {naam}", html)


def send_opvolging_gratis_test(to_email, webshop_url, site_url=None, taal="en"):
    """Een tweede bericht aan iemand die zelf de gratis test aanvroeg EN het
    vinkje zette dat we later nog iets mochten sturen (sinds 21 september, zie
    db.leads_om_op_te_volgen).

    Bewust kort en zonder verkooppraat. Deze mensen weten al wat Krillo doet en
    hebben hun eigen cijfer gezien. Wat ze niet weten is dat AI-antwoorden
    veranderen en dat er iets aan te doen is. Dat is de hele boodschap.

    Geen tweede opvolging. Wie na een herinnering niets doet, wil het niet, en
    doorgaan levert alleen spamklachten op."""
    basis = (site_url or "https://krilloai.com").rstrip("/")
    winkel = _kaal_adres(webshop_url)
    heen = f"{basis}/?winkel={quote(webshop_url or '')}#pricing"
    body = (
        _p(f"A little while ago you had us check whether AI assistants mention "
           f"<strong>{veilig(winkel)}</strong>. You saw the result.")
        + _p("What that test does not show: those answers change. A store that gets named "
             "today can be gone next month, without anything changing on your own site. It "
             "depends on what AI reads about you elsewhere.")
        + _p("If you want, we measure your category every month and show you where you rank. "
             "With Fix we also install the fixes in your store ourselves. You see exactly what "
             "changed and you can put anything back.")
        + _score_button(heen, "See the plans")
        + _p("Not interested? Then just ignore this. You will not hear from us again about "
             "this. Want no email from us at all? Reply to this email and we remove your "
             "address.", zacht=True)
    )
    html = _base_html("One thing worth knowing", f"About {veilig(winkel)}.", body)
    return send_email(to_email, f"Your Krillo result for {winkel}", html)


def send_vermeldingen_update(to_email, webshop_url, tekst, monitoring_url=None, taal="en",
                             onderwerp=None, kop=None):
    """Een bericht over je positie of je vermeldingen bij AI.

    Wordt gebruikt voor het maandbericht (meldingen.py, met zijn eigen
    onderwerp en kop), voor een melding na de eerste meting, en om iemand zijn
    link opnieuw te sturen. De tekst komt van de aanroeper; hier komt alleen
    de opmaak omheen.

    Geeft de aanroeper geen onderwerp mee, dan leiden we de richting af uit de
    eerste zin: omhoog, omlaag of gelijk."""
    if not tekst:
        return False
    winkel = _kaal_adres(webshop_url)

    eerste = tekst.split("\n\n")[0].lower()
    if "dropped" in eerste or "gone down" in eerste:
        standaard_onderwerp = f"AI mentions {winkel} less often"
        standaard_kop = "Your position has dropped"
    elif "moved up" in eerste or "gone up" in eerste:
        standaard_onderwerp = f"AI mentions {winkel} more often"
        standaard_kop = "Your position has gone up"
    else:
        standaard_onderwerp = f"An update on {winkel}"
        standaard_kop = "An update on your store"

    alineas = "".join(_p(veilig(stuk)) for stuk in tekst.split("\n\n") if stuk.strip())
    # De knop wijst naar het dashboard, met het werk erin. Iemand die dit
    # opent wil weten wat hij eraan doet, niet nog een tabel zien.
    body = alineas + _score_button(monitoring_url, "Open your dashboard")
    html = _base_html(kop or standaard_kop, f"The latest on {veilig(winkel)}.", body)
    return send_email(to_email, onderwerp or standaard_onderwerp, html)


def send_zichtbaarheidstest(to_email, webshop_url, resultaat, zin, site_url=None):
    """De uitslag van de gratis zichtbaarheidstest.

    Deze mail is gevraagd: iemand vulde zijn adres in om hem te krijgen. Dat is
    de reden dat er geen afmeldlink onderin hoeft voor deze ene mail.

    HERSCHREVEN 21 SEPTEMBER, na de testmail van Nino. Wat er mis was:
    - Nederlands op een Engelse site;
    - "dit zijn vijf vragen" terwijl er drie in de mail stonden. Er worden er
      vijf gesteld, maar alleen vragen waarbij AI winkels noemt tellen mee. Nu
      staat er hoeveel er gesteld zijn en hoeveel er meetelden;
    - "wat er verandert zie je pas als je elke week meet" en "dertig vragen per
      week": het model van voor de index. Nu: elke maand je hele categorie;
    - de knop ging naar de homepage zonder te zeggen waarheen;
    - rood, uit het oude ontwerp.

    De toon is bewust vlak. De cijfers zijn hard genoeg."""
    if not resultaat:
        return False

    winkel = _kaal_adres(webshop_url)
    telbaar = resultaat.get("telbaar") or 0
    gesteld = resultaat.get("gesteld") or telbaar
    genoemd = resultaat.get("genoemd") or 0
    aanbevolen = resultaat.get("aanbevolen") or 0

    def vak(getal, onder):
        return (f'<td style="padding:14px 8px; background:{VLAK}; border-radius:8px; '
                f'text-align:center; width:33%;">'
                f'<div style="font-size:26px; font-weight:700; color:{INKT};">{getal}</div>'
                f'<div style="font-size:11.5px; color:{INKT_ZACHT}; line-height:1.4;">{onder}</div></td>')

    cijfers = (
        '<table role="presentation" style="width:100%; border-collapse:separate; '
        'border-spacing:8px 0; margin:18px 0;"><tr>'
        + vak(genoemd, f"of {telbaar} questions where you were named")
        + vak(aanbevolen, "of those, really recommended")
        + vak(telbaar - genoemd, "questions where you were missing")
        + "</tr></table>"
    )

    regels = ""
    for r in (resultaat.get("regels") or [])[:5]:
        merk = GOED if r.get("genoemd") else MIS
        label = ("recommended" if r.get("aanbevolen")
                 else ("named" if r.get("genoemd") else "not named"))
        regels += (
            f'<div style="border-left:3px solid {merk}; padding:8px 12px; margin-bottom:10px;">'
            f'<div style="font-size:14px; color:{INKT};">{veilig(r.get("vraag", ""))}</div>'
            f'<div style="font-size:11px; color:{INKT_ZACHT}; text-transform:uppercase; '
            f'letter-spacing:0.05em; margin-top:3px;">{label}</div></div>'
        )

    # Samenvoegen voor het tonen: een bewaarde uitslag kan nog van voor de
    # naamsleutel zijn, en dan stond Pararius er twee keer in.
    import beoordeling
    samen = beoordeling.voeg_concurrenten_samen(resultaat.get("concurrenten") or [])
    anderen = [c for c in samen if not c.get("wij")][:5]
    def lijstje(kop, regels, onder=None):
        if not regels:
            return ""
        namen = "".join(
            f'<li style="margin-bottom:3px;">{veilig(c["naam"])} <span style="color:{INKT_ZACHT};">'
            f'({c["genoemd"]}x)</span></li>' for c in regels
        )
        return (f'<h3 style="font-size:15px; margin:24px 0 8px;">{kop}</h3>'
                f'<ul style="font-size:14px; line-height:1.6; padding-left:18px; margin:0;">'
                f'{namen}</ul>' + (_p(onder, zacht=True) if onder else ""))

    # Winkels en platforms apart (stap 73, punt van Nino). Een marktplaats of
    # portaal is geen concurrent: daar hoor je juist goed op te staan. Ze in
    # een lijstje zetten leest als "je verliest van Pararius", en dat klopt
    # niet.
    concurrenten = lijstje("Who was named instead",
                           [c for c in anderen if not c.get("platform")])
    concurrenten += lijstje(
        "Platforms AI points buyers to",
        [c for c in (resultaat.get("platforms") or []) if not c.get("wij")][:5],
        "These are marketplaces and portals, not competitors. AI sends buyers there, "
        "so it pays to be listed properly on them.")

    # De bronanalyse: waar een concurrent wel staat en jij niet. Het enige
    # stuk van deze mail waar iemand morgen zelf iets mee kan. Alleen als er
    # echt pagina's gevonden zijn.
    bronblok = ""
    br = resultaat.get("bronnen") or {}
    bronpaginas = br.get("gemiste_paginas") or []
    if bronpaginas:
        rijen = ""
        for g in bronpaginas:
            namen = ", ".join(g.get("concurrenten") or [])
            rijen += (
                f'<div style="border-left:3px solid {BLAUW}; padding:8px 12px; margin-bottom:10px;">'
                f'<div style="font-size:14px;">{veilig(g.get("titel") or g.get("domein") or "")}</div>'
                f'<div style="font-size:11.5px; color:{INKT_ZACHT}; margin-top:3px;">'
                f'{veilig(g.get("domein") or "")}'
                + (f' &middot; listed here: {veilig(namen)}' if namen else "")
                + '</div></div>'
            )
        over = (br.get("gemist") or 0) - len(bronpaginas)
        rest = (_p(f"And {over} more pages like these. They already exist; you do not have "
                   f"to make them.", zacht=True) if over > 0 else "")
        bronblok = (
            '<h3 style="font-size:15px; margin:26px 0 8px;">Where a competitor is listed '
            'and you are not</h3>'
            + (_p(veilig(br.get("conclusie")), zacht=True) if br.get("conclusie") else "")
            + rijen + rest
        )

    vragen_zin = (f"We asked {gesteld} buying questions. In {telbaar} of them AI named "
                  f"stores, and those are the ones that count."
                  if gesteld != telbaar else
                  f"We asked {gesteld} buying questions.")
    slot = (
        '<h3 style="font-size:15px; margin:26px 0 8px;">What this is, and what it is not</h3>'
        + _p(f"{vragen_zin} This is one moment. AI answers change from day to day, so a "
             f"single test is a snapshot and not a verdict.", zacht=True)
        + _p("With Watch we measure your whole category every month, with thirty questions, "
             "and show you where you rank against the other stores, which questions you "
             "miss, and what to fix. With Fix we also install those fixes in your store.",
             zacht=True)
    )

    body = (cijfers + '<h3 style="font-size:15px; margin:24px 0 10px;">The questions</h3>'
            + regels + concurrenten + bronblok + slot)
    if site_url:
        heen = f"{site_url.rstrip('/')}/?winkel={quote(webshop_url or '')}#pricing"
        body += _score_button(heen, "See the plans")

    html = _base_html("What AI said about your store", veilig(zin), body)
    return send_email(to_email, f"What AI says about {winkel}", html)


def send_shopify_bijgewerkt(to_email, webshop_url, wijzigingen, app_url=None, taal="en"):
    """Wat wij uit onszelf in de winkel van een Fix-klant hebben aangevuld.

    Deze mail is niet optioneel en ook geen nieuwsbrief. Wij hebben zonder te
    vragen in zijn winkel geschreven, want dat is wat hij koopt. Dan is het
    minste wat wij kunnen doen: precies opsommen wat er veranderd is, en er de
    weg bij zetten om het terug te draaien.

    Sinds 21 september gaat alles wat uit de winkel komt (productnaam, tekst)
    door veilig(). Een productnaam met punthaken erin kon de mail slopen, of
    een link in de mail zetten die eruitzag alsof hij van ons kwam."""
    if not to_email or not wijzigingen:
        return False

    winkel = _kaal_adres(webshop_url)
    aantal = len(wijzigingen)

    regels = []
    for w in wijzigingen[:25]:
        wat = veilig((w.get("wat") or "").strip())
        waar = veilig((w.get("waar") or "").strip())
        nieuw = (w.get("nieuw") or "").strip()
        if len(nieuw) > 220:
            nieuw = nieuw[:220].rsplit(" ", 1)[0] + "..."
        nieuw = veilig(nieuw)
        regels.append(f"""
        <tr><td style="padding:12px 0; border-bottom:1px solid {LIJN};">
          <div style="font-size:14.5px; font-weight:600; color:{INKT};">{waar}</div>
          <div style="font-size:12.5px; color:{INKT_ZACHT}; margin:2px 0 6px;">{wat}</div>
          <div style="font-size:13.5px; color:{INKT_ZACHT};">{nieuw}</div>
        </td></tr>""")
    meer = (_p(f"And {aantal - 25} more.", zacht=True) if aantal > 25 else "")
    meervoud = "s" if aantal != 1 else ""

    body = (
        _p(f"Your Fix plan covers this: every week we look at {veilig(winkel)} and write the "
           f"text that is missing. Here is exactly what changed. We filled in empty places "
           f"and replaced product descriptions that were very short. The old text is kept "
           f"for every change.")
        + f"""<table role="presentation" cellpadding="0" cellspacing="0" width="100%"
               style="margin:18px 0;">{''.join(regels)}</table>"""
        + meer
        + (_score_button(app_url, "See it in Krillo") if app_url else "")
        + _p("Not happy with one of these? Open Krillo and press Undo next to it, and it goes "
             "back to how it was. You can also switch this off there if you would rather "
             "approve every change yourself.", zacht=True)
    )
    html = _base_html(f"We filled in {aantal} thing{meervoud} for you",
                      f"This week in {veilig(winkel)}.", body)
    return send_email(to_email, f"We filled in {aantal} thing{meervoud} in {winkel}", html)


