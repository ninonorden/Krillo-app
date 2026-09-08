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

    from_email = os.environ.get("SMTP_FROM_EMAIL", "hallo@krillo.nl")

    # Waar een antwoord heen gaat. Onder elke mail staat "mail gewoon terug naar
    # dit adres", en dat moet waar zijn. Brevo verstuurt wel maar ontvangt niet:
    # zonder MX-records op krillo.nl komt een antwoord op hallo@krillo.nl
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


# TWEETALIG, op dezelfde manier als in actieplan.py en verklaring.py. Alleen de
# mails die een KLANT na een meting krijgt zijn tweetalig: de wekelijkse
# update, de welkomstmail van de monitoring, het bericht over de vermeldingen
# en de audit. De onderzoeksmail en de factuurmail blijven met opzet Nederlands.
# De factuur omdat hij een Nederlandse factuur is, de onderzoeksmail omdat het
# onderzoek over Nederlandse en Belgische webshops gaat.
#
# Alles wat niet "en" is wordt Nederlands. Voor een bestaande klant verandert er
# daardoor niets, ook niet als er ooit een taal langskomt die we niet kennen.

# De voettekst onder elke mail. Staat hier apart omdat hij anders in het Engels
# Nederlands zou blijven, en dat is precies het soort halve vertaling waaraan
# een klant ziet dat hij niet de bedoeling was.
VOETTEKST = {
    "nl": "Vragen? Mail gewoon terug naar dit adres.<br>Krillo, KVK 78439620",
    "en": "Questions? Just reply to this email.<br>Krillo, Dutch chamber of commerce 78439620",
}


def _base_html(title, intro, body_html, taal="nl"):
    voet = VOETTEKST.get("en" if taal == "en" else "nl", VOETTEKST["nl"])
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
        {voet}
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

    klantregel = (f"<div style='font-size:13px; color:#3B3D57;'>{veilig(bedrijfsnaam)}</div>"
                  if bedrijfsnaam else "")

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


def send_audit_email(to_email, webshop_url, scan_result, fix_previews, report_url=None, taal="nl"):
    score = scan_result.get("score", 0)
    problemen = [c for c in scan_result.get("checks", []) if c["status"] != "ok"]
    score_color = "#1FB6A4" if score >= 80 else ("#C77D00" if score >= 40 else "#FF4B3E")
    engels = taal == "en"

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
    "Shopify": """
      <li>Wij sturen je een verzoek voor een samenwerkersaccount. Dat is de
          standaardmanier waarop bureaus in een Shopify-winkel werken.</li>
      <li>Je krijgt er een mail over van Shopify. Klik op goedkeuren.</li>
      <li>Staat er in je beheerscherm een viercijferige code onder
          Instellingen, Gebruikers, dan hebben we die van je nodig. Mail hem terug.</li>
      <li>Je bepaalt zelf welke onderdelen we mogen zien, en je kunt de toegang
          met een klik weer intrekken. Het telt niet mee voor je aantal
          medewerkers en het kost je niets.</li>""",
    "WooCommerce": """
      <li>Ga in WordPress naar Gebruikers, Nieuwe gebruiker.</li>
      <li>Maak een gebruiker aan op toegang@krillo.nl met de rol Beheerder.</li>
      <li>Vink aan dat WordPress de gebruiker een mail stuurt.</li>
      <li>Als we klaar zijn kun je die gebruiker gewoon verwijderen.</li>""",
    "WordPress": """
      <li>Ga in WordPress naar Gebruikers, Nieuwe gebruiker.</li>
      <li>Maak een gebruiker aan op toegang@krillo.nl met de rol Beheerder.</li>
      <li>Vink aan dat WordPress de gebruiker een mail stuurt.</li>
      <li>Als we klaar zijn kun je die gebruiker gewoon verwijderen.</li>""",
    "Lightspeed": """
      <li>Ga in je Lightspeed-beheerscherm naar Instellingen en dan Gebruikers.</li>
      <li>Klik op een nieuwe gebruiker toevoegen en vul toegang@krillo.nl in.</li>
      <li>Geef die gebruiker rechten op producten, pagina's en instellingen. Rechten op
          bestellingen en klanten heb je ons niet te geven, die hebben we niet nodig.</li>
      <li>Als we klaar zijn kun je de gebruiker verwijderen.</li>""",
    "Shopware": """
      <li>Ga in je Shopware-beheerscherm naar Instellingen, Systeem, Gebruikers en rechten.</li>
      <li>Maak een gebruiker aan op toegang@krillo.nl.</li>
      <li>Geef die gebruiker rechten op producten en inhoud. Bestellingen en klanten
          hoeven niet.</li>
      <li>Als we klaar zijn kun je de gebruiker verwijderen.</li>""",
    "CCV Shop": """
      <li>Ga in je CCV Shop-beheerscherm naar Instellingen en dan Gebruikers.</li>
      <li>Maak een gebruiker aan op toegang@krillo.nl.</li>
      <li>Geef die gebruiker rechten op producten en pagina's. Bestellingen en klanten
          hoeven niet.</li>
      <li>Als we klaar zijn kun je de gebruiker verwijderen.</li>""",
    "PrestaShop": """
      <li>Ga in je PrestaShop-beheerscherm naar Geavanceerde instellingen, Team.</li>
      <li>Maak een medewerker aan op toegang@krillo.nl.</li>
      <li>Geef die medewerker rechten op catalogus en ontwerp. Bestellingen en klanten
          hoeven niet.</li>
      <li>Als we klaar zijn kun je de medewerker verwijderen.</li>""",
}

TOEGANG_ALGEMEEN = """
      <li>Geef ons een account in het beheerscherm van je webshop, met genoeg
          rechten om teksten en pagina's aan te passen. Ons adres is
          toegang@krillo.nl.</li>
      <li>Weet je niet hoe dat moet, mail dan terug met de naam van je
          webshopsysteem, dan sturen we de stappen voor jouw systeem.</li>
      <li>Laat je site door een bouwer beheren, stuur deze mail dan aan hem
          door. Wij regelen het verder met hem.</li>"""


def send_uitvoering_welkom(to_email, webshop_url, platform=None, monitoring_url=None):
    """De mail direct na de betaling van "wij voeren het uit".

    Deze mail heeft één taak: zorgen dat we toegang krijgen. Alles wat daarna
    komt kunnen wij zelf, maar zonder toegang staat de opdracht stil en heeft de
    klant wel betaald. Daarom staat er precies één vraag in en verder niets."""
    stappen = TOEGANG_UITLEG.get(platform or "", TOEGANG_ALGEMEEN)
    platform_zin = (
        f"Je webshop draait op {platform}, dus zo werkt het bij jou:"
        if platform in TOEGANG_UITLEG else
        "Zo geef je ons toegang:"
    )
    body = f"""
    <p style="font-size:14.5px;">Je betaling is binnen. We gaan aan de slag met
      {webshop_url} zodra we in je webshop kunnen.</p>
    <p style="font-size:14.5px;"><strong>{platform_zin}</strong></p>
    <ul style="font-size:14px; color:#3B3D57; line-height:1.7;">{stappen}</ul>
    <p style="font-size:14.5px;">Zodra we binnen zijn hoor je niets meer van ons
      tot het klaar is. Dat duurt meestal twee tot vijf werkdagen. Daarna krijg
      je een overzicht van precies wat er veranderd is, en wat de oude tekst
      was, zodat je alles kunt terugdraaien.</p>
    <p style="font-size:13.5px; color:#3B3D57;">We veranderen niets aan je
      prijzen, je voorraad, je bestellingen of je vormgeving. Alleen de teksten
      en instellingen waardoor AI je winkel beter kan lezen.</p>
    {_score_button(monitoring_url, "Bekijk je pagina") if monitoring_url else ""}
    """
    html = _base_html("We hebben nog één ding van je nodig",
                      f"Bedankt voor je opdracht voor {webshop_url}.", body)
    return send_email(to_email, "Krillo: we hebben toegang tot je webshop nodig", html)


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

    blokken = []
    for i, w in enumerate(wijzigingen, start=1):
        oud = _veilig(w.get("oude_waarde"))
        nieuw = _veilig(w.get("nieuwe_waarde"))
        blokken.append(f"""
        <div style="border:1px solid #E4E2DA; border-radius:10px; padding:16px 18px; margin-bottom:14px;">
          <div style="font-weight:600; font-size:15px; margin-bottom:4px;">{i}. {_veilig(w.get('wat'), 200)}</div>
          {f'<div style="font-size:13px; color:#3B3D57; margin-bottom:10px;">Waar: {_veilig(w.get("waar"), 300)}</div>' if w.get('waar') else ''}
          {f'<div style="font-size:13px; margin-bottom:8px;"><strong>Wat er nu staat:</strong><br>{nieuw}</div>' if nieuw else ''}
          <div style="font-size:13px; color:#3B3D57;"><strong>Wat er stond:</strong><br>
            {oud if oud else '<em>Hier stond nog niets, dit is nieuw toegevoegd.</em>'}</div>
        </div>""")

    body = f"""
    <p style="font-size:14.5px;">We zijn klaar met {webshop_url}. Hieronder staat
      precies wat we veranderd hebben, en wat er stond voordat we begonnen.</p>
    {''.join(blokken)}
    <p style="font-size:14.5px;">Wil je iets terug hebben zoals het was, dan staat
      de oude tekst hierboven. Je kunt hem zelf terugzetten, of mail ons en dan
      doen wij het.</p>
    <p style="font-size:13.5px; color:#3B3D57;">We hebben niets aangepast aan je
      prijzen, voorraad, bestellingen of vormgeving. Het duurt een paar weken
      voordat AI-modellen je nieuwe teksten hebben opgepikt, dus verwacht niet
      morgen al een ander antwoord.</p>
    {_score_button(monitoring_url, "Bekijk je pagina") if monitoring_url else ""}
    """
    html = _base_html("Je webshop is klaar",
                      f"Hierbij het overzicht van wat we voor {webshop_url} gedaan hebben.",
                      body)
    return send_email(to_email, f"Klaar: wat we aangepast hebben aan {webshop_url}", html)


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
                        afmeld_url=None, land=None):
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
    afzender = os.environ.get("SMTP_FROM_EMAIL", "hallo@krillo.nl")

    # Het cijfer in een eigen kader. Dat is het enige opvallende element in deze
    # mail, en dat is met opzet: wat opvalt moet zijn eigen uitkomst zijn, niet
    # onze knop. Een mail die eruitziet als een rapport wordt anders gelezen dan
    # een mail die eruitziet als een aanbieding.
    if genoemd is not None and telbaar:
        kader = f"""
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="border:1px solid #E4E2DA; border-radius:10px; margin:22px 0;">
        <tr><td style="padding:20px 22px;">
          <div style="font-size:12px; color:#3B3D57; letter-spacing:.04em;
                      text-transform:uppercase; margin-bottom:6px;">Jouw uitkomst</div>
          <div style="font-size:26px; font-weight:700; color:#12142B; line-height:1.25;">
            Genoemd bij {genoemd} van de {telbaar} vragen</div>
          <div style="font-size:13.5px; color:#3B3D57; margin-top:6px;">
            {winkel}{vergelijking_regel}</div>
        </td></tr>
      </table>"""
    else:
        kader = f"""
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="border:1px solid #E4E2DA; border-radius:10px; margin:22px 0;">
        <tr><td style="padding:20px 22px; font-size:15px; color:#12142B;">
          We hebben {winkel} meegenomen in de meting.</td></tr>
      </table>"""

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
            Op je eigen pagina staat bij welke vragen dat was, welke winkels er bij
            diezelfde vragen wel uitkwamen, en wat daarvan aan jouw kant de oorzaak is.
            Je hoeft nergens voor in te loggen en er wordt niets gevraagd.</p>

          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 8px;">
            <tr><td style="background:#12142B; border-radius:8px;">
              <a href="{uitkomst_url}" style="display:inline-block; padding:13px 26px;
                 color:#FFFFFF; text-decoration:none; font-size:14.5px; font-weight:600;">
                Bekijk je uitkomst</a>
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


def send_monitoring_welcome_email(to_email, webshop_url, scan_result, report_url=None, taal="nl"):
    score = scan_result.get("score", 0)
    if taal == "en":
        body_en = f"""
    <p style="font-size:14.5px;"><strong>Starting score: {score}/100</strong> for {webshop_url}</p>
    <p style="font-size:13.5px; color:#3B3D57;">
      This is your baseline. Every week we scan again and you get a message with the new
      standing, and a clear warning if your score has dropped. Your own page shows every week
      what to do first, with the text ready to use, and it stays at the same address. Keep the
      link below.
    </p>
    <p style="font-size:13.5px; color:#3B3D57;">
      We are also busy with your first measurement at ChatGPT and Gemini. We come up with thirty
      buying questions that shoppers in your category really ask, and check whether your store is
      in the answer. That takes about fifteen minutes. Have another look at your page after that:
      you will see in how many questions you are mentioned, in how many you are really
      recommended, and which stores come out above you on the same questions.
    </p>
    {_score_button(report_url, "Open your monitoring page")}
    """
        html_en = _base_html(
            "Welcome to Krillo monitoring",
            f"Your monitoring for {webshop_url} has started.",
            body_en,
            taal="en",
        )
        return send_email(to_email, "Welcome to Krillo monitoring", html_en)

    body = f"""
    <p style="font-size:14.5px;"><strong>Startscore: {score}/100</strong> voor {webshop_url}</p>
    <p style="font-size:13.5px; color:#3B3D57;">
      Dit is je nulmeting. Elke week scannen we opnieuw en krijg je bericht met de
      nieuwe stand, en een duidelijke waarschuwing als je score gedaald is. Op je eigen pagina staat elke week wat je als eerste kan doen, met de tekst er kant en klaar bij,
      die op hetzelfde adres blijft staan. Bewaar de link hieronder.
    </p>
    <p style="font-size:13.5px; color:#3B3D57;">
      We zijn nu ook bezig met je eerste meting bij ChatGPT en Gemini. We bedenken dertig
      koopvragen die kopers in jouw categorie echt stellen, en kijken of jouw webshop in het
      antwoord staat. Dat duurt ongeveer een kwartier. Kijk daarna nog eens op je pagina: je ziet
      dan bij hoeveel vragen je genoemd wordt, bij hoeveel je ook echt aanbevolen wordt, en welke
      winkels er bij dezelfde vragen boven je staan.
    </p>
    {_score_button(report_url, "Open je monitoringpagina")}
    """
    html = _base_html(
        "Welkom bij Krillo monitoring",
        f"Je monitoring voor {webshop_url} is gestart.",
        body,
    )
    return send_email(to_email, "Welkom bij Krillo monitoring", html)


def _weekly_en(to_email, webshop_url, score, report_url, vorige_score):
    """De Engelse tegenhanger van send_weekly_update_email.

    Dezelfde drie gevallen in dezelfde volgorde: gedaald, gestegen, gelijk.
    Het cijfer, de kleuren en de knop staan op dezelfde plek, alleen de woorden
    zijn anders."""
    if vorige_score is None:
        onderwerp = f"Your weekly Krillo update ({score}/100)"
        kop = "Your weekly update"
        melding = (f"<p style='font-size:14.5px;'><strong>Current score: {score}/100</strong> "
                   f"for {webshop_url}</p>")
    else:
        verschil = score - vorige_score
        if verschil < 0:
            onderwerp = f"Heads up: your Krillo score dropped to {score}/100"
            kop = "Your score has dropped"
            melding = f"""
            <div style="background:#FFE3E0; border-radius:10px; padding:16px 18px; margin-bottom:16px;">
              <strong style="font-size:15px; color:#993C1D;">Down from {vorige_score} to {score}</strong>
              <p style="font-size:13.5px; color:#993C1D; margin:6px 0 0;">
                Something changed on your website that makes it harder for AI to read your shop.
                Your monitoring page shows exactly what is new.
              </p>
            </div>
            """
        elif verschil > 0:
            onderwerp = f"Good news: your Krillo score is now {score}/100"
            kop = "Your score has gone up"
            melding = f"""
            <div style="background:#DFF5F1; border-radius:10px; padding:16px 18px; margin-bottom:16px;">
              <strong style="font-size:15px; color:#085041;">Up from {vorige_score} to {score}</strong>
              <p style="font-size:13.5px; color:#085041; margin:6px 0 0;">
                Your page shows which points stand better than last week.
              </p>
            </div>
            """
        else:
            onderwerp = f"Your weekly Krillo update ({score}/100)"
            kop = "Your weekly update"
            melding = f"""
            <p style="font-size:14.5px;"><strong>Your score is still {score}/100</strong> for {webshop_url}.
            Nothing changed this week.</p>
            """

    body = melding + _score_button(report_url, "See your monitoring page")
    html = _base_html(kop, f"The latest scan for {webshop_url}.", body, taal="en")
    return send_email(to_email, onderwerp, html)


def send_weekly_update_email(to_email, webshop_url, scan_result, report_url=None,
                             vorige_score=None, taal="nl"):
    score = scan_result.get("score", 0)

    if taal == "en":
        return _weekly_en(to_email, webshop_url, score, report_url, vorige_score)

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
                Op je pagina zie je welke punten er beter staan dan vorige week.
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


def send_vermeldingen_update(to_email, webshop_url, tekst, monitoring_url=None, taal="nl"):
    """Fase 5 stap 10. Een bericht over de vermeldingen bij AI, en alleen als er
    iets veranderd is dat de moeite waard is.

    Bewust los van de wekelijkse scanmail. Die gaat over je site, deze gaat over
    wat AI over je zegt. Twee verschillende dingen door elkaar in een mail leest
    niemand meer.

    De tekst komt uit waarschuwing.bericht(), inclusief de duiding of het aan de
    klant lag of aan de markt. Hier zetten we er alleen opmaak omheen."""
    if not tekst:
        return False

    # De richting uit de eerste zin halen. Die zin komt uit waarschuwing.bericht
    # en staat daar in dezelfde taal, dus we kijken naar de woorden van die taal.
    eerste = tekst.split("\n\n")[0].lower()
    engels = taal == "en"

    if engels:
        if "gone down" in eerste:
            onderwerp = f"AI mentions you less often ({webshop_url})"
            kop = "Your mentions have gone down"
        elif "gone up" in eerste:
            onderwerp = f"AI mentions you more often ({webshop_url})"
            kop = "Your mentions have gone up"
        else:
            onderwerp = f"Update on your AI mentions ({webshop_url})"
            kop = "Update on your mentions"
        knop = "See what you can do about it"
        intro = f"What AI said about {webshop_url} this week, and what you do about it."
    else:
        if "gedaald" in eerste:
            onderwerp = f"Je wordt minder genoemd door AI ({webshop_url})"
            kop = "Je vermeldingen zijn gedaald"
        elif "gestegen" in eerste:
            onderwerp = f"Je wordt vaker genoemd door AI ({webshop_url})"
            kop = "Je vermeldingen zijn gestegen"
        else:
            onderwerp = f"Update over je AI-vermeldingen ({webshop_url})"
            kop = "Update over je vermeldingen"
        knop = "Bekijk wat je hieraan kan doen"
        intro = f"Wat AI deze week over {webshop_url} zei, en wat je eraan doet."

    alineas = "".join(
        f'<p style="font-size:14.5px; line-height:1.6;">{stuk}</p>'
        for stuk in tekst.split("\n\n") if stuk.strip()
    )
    # De knop wijst naar de takenlijst en niet naar de cijfers. Iemand die deze
    # mail opent wil weten wat hij eraan doet, niet nog een tabel zien.
    body = alineas + _score_button(monitoring_url, knop)
    html = _base_html(kop, intro, body, taal=taal)
    return send_email(to_email, onderwerp, html)


def send_zichtbaarheidstest(to_email, webshop_url, resultaat, zin, site_url=None):
    """De uitslag van de gratis zichtbaarheidstest.

    Deze mail is gevraagd: iemand vulde zijn adres in om hem te krijgen. Dat is
    de reden dat er geen afmeldlink onderin hoeft voor deze ene mail. Ga je deze
    mensen later ook iets anders sturen, dan mag dat alleen als ze daar apart
    akkoord voor gaven, en dan hoort er wel een afmeldlink in.

    De toon is bewust vlak. De cijfers zijn hard genoeg."""
    if not resultaat:
        return False

    telbaar = resultaat.get("telbaar") or 0
    genoemd = resultaat.get("genoemd") or 0
    aanbevolen = resultaat.get("aanbevolen") or 0

    cijfers = f"""
    <table style="width:100%; border-collapse:collapse; margin:20px 0;">
      <tr>
        <td style="padding:14px; background:#F6F5F1; border-radius:8px; text-align:center; width:33%;">
          <div style="font-size:26px; font-weight:700;">{genoemd}</div>
          <div style="font-size:11px; color:#3B3D57;">van de {telbaar} vragen genoemd</div>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:14px; background:#F6F5F1; border-radius:8px; text-align:center; width:33%;">
          <div style="font-size:26px; font-weight:700;">{aanbevolen}</div>
          <div style="font-size:11px; color:#3B3D57;">daarvan echt aanbevolen</div>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:14px; background:#F6F5F1; border-radius:8px; text-align:center; width:33%;">
          <div style="font-size:26px; font-weight:700;">{telbaar - genoemd}</div>
          <div style="font-size:11px; color:#3B3D57;">vragen waar je niet bij stond</div>
        </td>
      </tr>
    </table>
    """

    regels = ""
    for r in (resultaat.get("regels") or [])[:5]:
        merk = "#1FB6A4" if r.get("genoemd") else "#FF4B3E"
        label = "aanbevolen" if r.get("aanbevolen") else ("genoemd" if r.get("genoemd") else "niet genoemd")
        regels += (
            f'<div style="border-left:3px solid {merk}; padding:8px 12px; margin-bottom:10px;">'
            f'<div style="font-size:14px;">{r.get("vraag","")}</div>'
            f'<div style="font-size:11.5px; color:#3B3D57; text-transform:uppercase; '
            f'letter-spacing:0.04em; margin-top:3px;">{label}</div></div>'
        )

    anderen = [c for c in (resultaat.get("concurrenten") or []) if not c.get("wij")][:5]
    concurrenten = ""
    if anderen:
        namen = "".join(
            f'<li style="margin-bottom:3px;">{c["naam"]} <span style="color:#3B3D57;">'
            f'({c["genoemd"]}x)</span></li>' for c in anderen
        )
        concurrenten = (
            '<h3 style="font-size:15px; margin:24px 0 8px;">Wie er wel genoemd werd</h3>'
            f'<ul style="font-size:14px; line-height:1.6; padding-left:18px;">{namen}</ul>'
        )

    slot = f"""
    <h3 style="font-size:15px; margin:26px 0 8px;">Wat dit wel en niet is</h3>
    <p style="font-size:14px; line-height:1.6; color:#3B3D57;">
      Dit zijn vijf vragen op een moment. AI-antwoorden wisselen van dag tot dag, dus een
      losse meting is een momentopname en geen oordeel. Wat er verandert zie je pas als je
      elke week meet.
    </p>
    <p style="font-size:14px; line-height:1.6; color:#3B3D57;">
      We hebben je niet verteld waarom het zo is, en ook niet of wat AI over je zegt klopt.
      Dat zit in het betaalde deel, samen met dertig vragen per week in plaats van vijf.
    </p>
    """

    body = cijfers + '<h3 style="font-size:15px; margin:24px 0 10px;">De vragen</h3>' + regels
    body += concurrenten + slot
    if site_url:
        body += _score_button(site_url, "Bekijk wat er nog meer mogelijk is")

    html = _base_html("Dit zei AI over je webshop", zin, body)
    return send_email(to_email, f"Wat AI over {webshop_url} zegt", html)


def send_shopify_bijgewerkt(to_email, webshop_url, wijzigingen, app_url=None, taal="nl"):
    """Wat wij uit onszelf in de winkel van een abonnee hebben aangevuld.

    Deze mail is niet optioneel en ook geen nieuwsbrief. Wij hebben zonder te
    vragen in zijn winkel geschreven, want dat is wat hij koopt. Dan is het
    minste wat wij kunnen doen: precies opsommen wat er veranderd is, en er de
    weg bij zetten om het terug te draaien. Zonder dit bericht zou hij op een
    dag een tekst tegenkomen die hij niet herkent, en dat is het moment waarop
    iemand opzegt.
    """
    if not to_email or not wijzigingen:
        return False

    engels = taal == "en"
    winkel = _kaal_adres(webshop_url)
    aantal = len(wijzigingen)

    regels = []
    for w in wijzigingen[:25]:
        wat = (w.get("wat") or "").strip()
        waar = (w.get("waar") or "").strip()
        nieuw = (w.get("nieuw") or "").strip()
        if len(nieuw) > 220:
            nieuw = nieuw[:220].rsplit(" ", 1)[0] + "..."
        regels.append(f"""
        <tr><td style="padding:12px 0; border-bottom:1px solid #E4E2DA;">
          <div style="font-size:14.5px; font-weight:600; color:#12142B;">{waar}</div>
          <div style="font-size:12.5px; color:#6B6D85; margin:2px 0 6px;">{wat}</div>
          <div style="font-size:13.5px; color:#3B3D57;">{nieuw}</div>
        </td></tr>""")
    meer = ""
    if aantal > 25:
        meer = (f"<p style='font-size:13px; color:#6B6D85;'>"
                f"{'And ' + str(aantal - 25) + ' more.' if engels else 'En nog ' + str(aantal - 25) + '.'}</p>")

    if engels:
        onderwerp = f"We filled in {aantal} thing{'s' if aantal != 1 else ''} in {winkel}"
        kop = f"We filled in {aantal} thing{'s' if aantal != 1 else ''} for you"
        inleiding = (f"Your plan covers this: we look at {winkel} every week and write the "
                     f"text that is missing. Here is exactly what changed this week. We only "
                     f"filled in empty places, we did not touch anything you wrote yourself.")
        slot = ("Not happy with one of these? Open Krillo and press Undo next to it, and it "
                "goes back to how it was. You can also switch this off there if you would "
                "rather approve every change yourself.")
        knop = "See it in Krillo"
    else:
        onderwerp = f"We hebben {aantal} ding{'en' if aantal != 1 else ''} ingevuld in {winkel}"
        kop = f"We hebben {aantal} ding{'en' if aantal != 1 else ''} voor je ingevuld"
        inleiding = (f"Dat hoort bij je abonnement: wij kijken elke week naar {winkel} en "
                     f"schrijven de tekst die ontbreekt. Hieronder staat precies wat er deze "
                     f"week veranderd is. Wij hebben alleen lege plekken ingevuld en niets "
                     f"aangeraakt wat jij zelf geschreven hebt.")
        slot = ("Ben je het ergens niet mee eens? Open Krillo en klik op Terugzetten "
                "ernaast, dan staat het weer zoals het was. Je kunt het daar ook uitzetten "
                "als je liever elke wijziging zelf goedkeurt.")
        knop = "Bekijk het in Krillo"

    knop_html = _score_button(app_url, knop) if app_url else ""

    body = f"""
    <p style="font-size:14.5px;">{inleiding}</p>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
           style="margin:18px 0;">{''.join(regels)}</table>
    {meer}
    {knop_html}
    <p style="font-size:13px; color:#3B3D57; margin-top:22px;">{slot}</p>
    """
    html = _base_html(kop, "", body, taal=taal)
    return send_email(to_email, onderwerp, html)
