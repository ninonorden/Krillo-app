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


def send_onderzoeksmail(to_email, webshop_url, uitkomst_url, genoemd=None,
                        telbaar=None, nooit_genoemd=None, gemeten=None,
                        afmeld_url=None, land=None, voorbeeld=None):
    """De mail aan een webshop die we in het onderzoek gemeten hebben.

    Dit is geen verkoopmail en zo hoort hij ook niet te lezen. Er staat een
    uitkomst in die over hem gaat, waar hij hem kan bekijken, en hoe hij eraf
    komt. Het aanbod staat op de pagina, niet in de mail.

    Waarom deze mail er zo kaal uitziet, en dat is met opzet:

    Iemand die niet om post gevraagd heeft beslist in twee seconden of het
    oplichterij is. Alles wat op reclame lijkt telt daarin mee. Een grote
    gekleurde knop, een logo, opmaak in drie kleuren: dat doet een bedrijf dat
    iets wil verkopen, niet iemand die je iets laat weten. Daarom staat hier
    een gewone tekstlink en geen knop, en is er geen opmaak die je bij een
    mailtje van een mens ook niet zou zien.

    De afzender is het tweede punt. Een naam onderaan scheelt meer dan alle
    opmaak bij elkaar: een mail van een persoon is te beantwoorden, een mail
    van "wij" niet. Zet AFZENDER_NAAM in Render om die naam eronder te krijgen.
    Staat hij er niet, dan gaat de mail gewoon uit zonder, maar hij leest dan
    afstandelijker.

    De afmeldlink is niet optioneel. Hij moet in elke mail staan die naar
    iemand gaat die er niet om vroeg, hij moet werken in een klik, en hij is
    het verschil tussen een afmelding en een spamklacht. Een spamklacht kost je
    je domein, een afmelding kost je een adres."""
    if not to_email or not uitkomst_url:
        print("Onderzoeksmail niet verstuurd: adres of link ontbreekt.")
        return False

    winkel = _kaal_adres(webshop_url)

    # Een Belgische winkel is geen Nederlandse webshop. Dat klinkt klein, maar
    # het is de eerste zin en het valt meteen op als het niet klopt.
    if (land or "").strip().lower() in ("be", "belgie", "belgi\u00eb", "belgium"):
        streek = "Belgische en Nederlandse webshops"
    else:
        streek = "Nederlandse en Belgische webshops"

    vergelijking_regel = ""
    if nooit_genoemd is not None and gemeten:
        vergelijking_regel = (f" &middot; van de {gemeten} gemeten winkels werden er "
                              f"{nooit_genoemd} bij geen enkele vraag genoemd")

    naam = (os.environ.get("AFZENDER_NAAM") or "").strip()
    ondertekening = (f'<p style="font-size:14.5px; color:#12142B; margin:22px 0 0;">'
                     f'Met vriendelijke groet,<br>{naam}</p>') if naam else ""

    if afmeld_url:
        afmelden = (f'Wil je hier niets meer over horen, dan kan dat met '
                    f'<a href="{afmeld_url}" style="color:#6B6D85;">deze link</a>. '
                    f'We halen je uitkomst dan weg en je krijgt geen post meer.')
    else:
        afmelden = ("Wil je hier niets meer over horen, antwoord dan op deze mail "
                    "en het is dezelfde dag weg.")

    g = BEDRIJFSGEGEVENS
    afzender = os.environ.get("SMTP_FROM_EMAIL", "hello@krilloai.com")

    # WAT ER IN HET KADER STAAT, EN WAAROM DAT OP 12 SEPTEMBER VERANDERD IS.
    #
    # Brevo laat zien dat 45 procent van de ontvangers deze mail OPENT. Dat is
    # voor koude zakelijke post uitstekend, en er zijn nul spamklachten. Maar van
    # die 45 procent klikt maar 8 procent door naar zijn uitkomst.
    #
    # De mail komt dus aan, wordt gelezen, en dan gebeurt er niets. Dat wijst
    # niet op de aflevering en niet op de onderwerpregel, maar op de inhoud. En
    # de oorzaak lag voor de hand zodra je hem opschreef: er stond "genoemd bij
    # 0 van de 5 vragen", en daarmee was het verhaal uit. Wie het antwoord al
    # heeft, klikt niet meer.
    #
    # Wat er nu staat is hetzelfde feit, van de andere kant bekeken: niet dat
    # jij ontbrak, maar dat er WEL iemand anders uitkwam. Dat is precies even
    # waar, het is scherper, en het roept de vraag op die alleen de pagina
    # beantwoordt: wie dan.
    gemist = None
    if genoemd is not None and telbaar:
        gemist = max(0, telbaar - genoemd)

    if gemist:
        if genoemd == 0:
            kop = (f"Bij alle {telbaar} vragen kwam er een andere winkel uit, "
                   f"en {winkel} niet")
        else:
            kop = (f"Bij {gemist} van de {telbaar} vragen kwam er een andere "
                   f"winkel uit, en {winkel} niet")
        onder = f"Genoemd bij {genoemd} van de {telbaar} vragen{vergelijking_regel}"
    elif genoemd is not None and telbaar:
        kop = f"{winkel} werd bij alle {telbaar} vragen genoemd"
        onder = ("Genoemd worden is niet hetzelfde als aanbevolen worden. Dat "
                 "verschil staat op je pagina.")
    else:
        kop = f"We hebben {winkel} meegenomen in de meting"
        onder = ""

    # HET WOORD "KOOPVRAAG" IS HIER WEG, EN DAT IS DE HELE WIJZIGING.
    #
    # Dat was ons woord en niet dat van de ontvanger. Een winkelier die het leest
    # moet eerst raden wat wij gemeten hebben, en raden kost precies de twee
    # seconden die een ongevraagde mail krijgt.
    #
    # De oplossing is niet uitleggen wat een koopvraag is, maar er een laten
    # zien. Staat de echte vraag erin, met de winkels die eruit kwamen en een
    # kruisje bij de winkel van de lezer, dan is er geen woord uitleg meer nodig:
    # iedereen die ooit iets aan ChatGPT gevraagd heeft snapt dat beeld meteen.
    #
    # Twee namen en niet de hele lijst. Genoeg om het te geloven, te weinig om
    # het af te doen. De rest is precies waarvoor je op de knop drukt.
    #
    # Lukt het niet om een bruikbare vraag te vinden (zie beoordeling.
    # voorbeeldvraag), dan valt de mail terug op het kader zonder voorbeeld. Dat
    # is geen fout, dat is een winkel waarbij er weinig te laten zien valt.
    vraag = (voorbeeld or {}).get("vraag")
    namen = (voorbeeld or {}).get("winkels") or []

    if vraag and len(namen) >= 2:
        aantal = voorbeeld.get("aantal") or len(namen)
        model = voorbeeld.get("model") or "ChatGPT"
        regels = []
        for naam in namen[:2]:
            regels.append(
                f'<tr><td style="padding:4px 0; font-size:14.5px; color:#12142B;">'
                f'<span style="color:#1FB6A4; font-weight:700;">&#10003;</span>'
                f'&nbsp;&nbsp;{naam}</td></tr>')
        if aantal > 2:
            rest = aantal - 2
            woord = "winkel" if rest == 1 else "winkels"
            regels.append(
                f'<tr><td style="padding:4px 0; font-size:14.5px; color:#3B3D57;">'
                f'<span style="color:#1FB6A4; font-weight:700;">&#10003;</span>'
                f'&nbsp;&nbsp;nog {rest} andere {woord}</td></tr>')
        regels.append(
            f'<tr><td style="padding:4px 0; font-size:14.5px; color:#D42E22; '
            f'font-weight:600;">'
            f'<span style="font-weight:700;">&#10005;</span>'
            f'&nbsp;&nbsp;{winkel} stond er niet bij</td></tr>')

        # De vergelijking met de rest van het onderzoek hangt hieronder en niet
        # bovenaan. Hij doet er wel toe, want hij maakt van een losse uitkomst
        # een bevinding uit een onderzoek, maar hij is niet de reden om te
        # klikken. Die staat erboven.
        if gemist and genoemd == 0:
            slotregel = (f"Dat gebeurde bij alle {telbaar} vragen die we "
                         f"stelden{vergelijking_regel}")
        elif gemist:
            slotregel = (f"Dat gebeurde bij {gemist} van de {telbaar} "
                         f"vragen{vergelijking_regel}")
        else:
            slotregel = ""

        kader = f"""
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="border:1px solid #E4E2DA; border-radius:10px; margin:22px 0;">
        <tr><td style="padding:20px 22px;">
          <div style="font-size:11.5px; color:#6B6D85; letter-spacing:.06em;
                      text-transform:uppercase; margin-bottom:12px;">
            Een van de vragen die we stelden</div>

          <table role="presentation" cellpadding="0" cellspacing="0">
            <tr><td style="background:#F6F5F1; border-radius:14px 14px 14px 4px;
                           padding:12px 16px; font-size:15.5px; font-weight:600;
                           color:#12142B; line-height:1.4;">{vraag}</td></tr>
          </table>

          <div style="font-size:13.5px; color:#3B3D57; margin:16px 0 4px;">
            {model} antwoordde met {aantal} {"winkel" if aantal == 1 else "winkels"}:</div>
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
            {''.join(regels)}
          </table>
          {f'<div style="font-size:12.5px; color:#6B6D85; margin-top:14px;">{slotregel}</div>' if slotregel else ''}
        </td></tr>
      </table>"""
    else:
        kader = f"""
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="border:1px solid #E4E2DA; border-radius:10px; margin:22px 0;">
        <tr><td style="padding:20px 22px;">
          <div style="font-size:12px; color:#3B3D57; letter-spacing:.04em;
                      text-transform:uppercase; margin-bottom:8px;">Jouw uitkomst</div>
          <div style="font-size:21px; font-weight:700; color:#12142B; line-height:1.35;">
            {kop}</div>
          {f'<div style="font-size:13.5px; color:#3B3D57; margin-top:8px;">{onder}</div>' if onder else ''}
        </td></tr>
      </table>"""

    # DE ZIN OVER DE VERVOLGMETING, EN WAAROM DIE NU UIT ECHTE GETALLEN KOMT.
    #
    # Hier stond: "dan meten we meteen door met vijftien vragen aan twee
    # modellen". Allebei die getallen stonden vast in de tekst terwijl ze in
    # Render ingesteld worden, en het eerste klopte bovendien niet helemaal: het
    # zijn geen vijftien vragen ERBIJ, het is een meting van vijftien vragen
    # waarvan de eerste zes al gesteld waren.
    #
    # Nu komen beide getallen mee van de aanroeper: het aantal vragen uit
    # MEET_VRAGEN_NA_KLIK en het aantal modellen uit de sleutels die echt in
    # Render staan. Zet jij daar morgen een derde model bij, dan zegt de mail
    # vanzelf drie. Weten we ze niet, dan blijft de zin weg. Liever niets
    # beloven dan een getal noemen dat niemand nakijkt behalve de ontvanger.
    na_vragen = (voorbeeld or {}).get("na_klik_vragen")
    na_modellen = (voorbeeld or {}).get("na_klik_modellen")
    belofte = ""
    if na_vragen and telbaar and na_vragen > telbaar:
        if na_modellen and na_modellen > 1:
            belofte = (f" Open je hem, dan gaat er meteen een grotere meting "
                       f"overheen: {na_vragen} vragen in plaats van {telbaar}, "
                       f"en bij {na_modellen} modellen in plaats van een.")
        else:
            belofte = (f" Open je hem, dan gaat er meteen een grotere meting "
                       f"overheen, met {na_vragen} vragen in plaats van {telbaar}.")

    if vraag and len(namen) >= 2:
        vervolg = ("Bij welke vragen dat nog meer gebeurde, en welke winkels er dan "
                   "uitkwamen, staat op je eigen pagina." + belofte +
                   " Je hoeft nergens voor in te loggen en er wordt niets gevraagd.")
        knoptekst = "Bekijk de andere vragen"
    else:
        vervolg = ("Welke winkels dat waren en bij welke vragen, staat op je eigen "
                   "pagina." + belofte +
                   " Je hoeft nergens voor in te loggen en er wordt niets gevraagd.")
        knoptekst = "Bekijk welke winkels er wel uitkwamen"

    # De knop is donkergrijs en niet felrood, en er staat onder waar hij heen
    # gaat. Dat laatste is het hele punt: bij een ongevraagde mail wil je zien
    # dat de link naar hetzelfde domein gaat als de afzender voordat je klikt.
    zichtbaar = _kaal_adres(uitkomst_url)

    html = f"""
    <div style="background:#F6F5F1; padding:28px 16px; font-family:-apple-system,
                'Segoe UI', Arial, sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="max-width:560px; margin:0 auto;">
        <tr><td style="background:#FFFFFF; border:1px solid #E4E2DA; border-radius:14px;
                       padding:32px 30px;">

          <div style="font-size:15px; font-weight:700; color:#12142B; letter-spacing:.01em;">
            Krillo</div>
          <div style="font-size:12px; color:#6B6D85; margin-top:2px;">
            Onderzoek naar AI-antwoorden over webshops</div>

          <div style="height:1px; background:#E4E2DA; margin:20px 0 22px;"></div>

          <p style="font-size:15px; color:#12142B; line-height:1.65; margin:0 0 14px;">
            We onderzoeken welke {streek} door ChatGPT en Gemini genoemd worden
            wanneer iemand vraagt waar hij iets kan kopen. {winkel} zat in die meting.</p>

          {kader}

          <p style="font-size:15px; color:#12142B; line-height:1.65; margin:0 0 6px;">
            {vervolg}</p>

          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 8px;">
            <tr><td style="background:#12142B; border-radius:8px;">
              <a href="{uitkomst_url}" style="display:inline-block; padding:13px 26px;
                 color:#FFFFFF; text-decoration:none; font-size:14.5px; font-weight:600;">
                {knoptekst}</a>
            </td></tr>
          </table>
          <p style="font-size:12.5px; color:#6B6D85; margin:0 0 4px;">
            De link gaat naar {zichtbaar}</p>
          {ondertekening}

          <div style="height:1px; background:#E4E2DA; margin:26px 0 16px;"></div>

          <p style="font-size:12.5px; color:#6B6D85; line-height:1.7; margin:0;">
            Je krijgt deze mail omdat je winkel in ons onderzoek zit. We hebben alleen
            openbare informatie van je website gebruikt en niets aan je site veranderd.
            {afmelden}<br><br>
            {g['naam']} &middot; {g['adres']}, {g['plaats']} &middot; KVK {g['kvk']}<br>
            Antwoorden op deze mail komen bij ons aan op {afzender}.</p>

        </td></tr>
      </table>
    </div>
    """
    koppen = {"List-Unsubscribe": f"<{afmeld_url}>",
              "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"} if afmeld_url else None
    return send_email(to_email, f"{winkel} in ons onderzoek naar AI-antwoorden",
                      html, koppen=koppen)


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
             "thirteen technical checks every week; it scores "
             f"{score} of 100 on them today.")
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
    heen = f"{basis}/?winkel={quote(webshop_url or '')}#prijzen"
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

    anderen = [c for c in (resultaat.get("concurrenten") or []) if not c.get("wij")][:5]
    concurrenten = ""
    if anderen:
        namen = "".join(
            f'<li style="margin-bottom:3px;">{veilig(c["naam"])} <span style="color:{INKT_ZACHT};">'
            f'({c["genoemd"]}x)</span></li>' for c in anderen
        )
        concurrenten = (
            f'<h3 style="font-size:15px; margin:24px 0 8px;">Who was named instead</h3>'
            f'<ul style="font-size:14px; line-height:1.6; padding-left:18px; margin:0;">{namen}</ul>'
        )

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
        heen = f"{site_url.rstrip('/')}/?winkel={quote(webshop_url or '')}#prijzen"
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


