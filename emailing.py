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
import re
import requests
from datetime import datetime

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_api_key():
    return os.environ.get("BREVO_API_KEY")


import threading as _threading

# De proefaankoop van de nacht (proefaankoop.py, 1 oktober). Die laat de echte
# betaalafhandeling lopen, maar de mails mogen nergens heen: ze worden op DEZE
# draad opgevangen om na te lezen. Alleen op die draad: een mail die tegelijk
# op een andere draad uitgaat (een bericht na een nachtmeting) gaat gewoon weg.
_opvang = _threading.local()


def platte_tekst(html_body):
    """De HTML van een mail als leesbare platte tekst: alinea's blijven alinea's,
    een link wordt "tekst (adres)"."""
    import re as _re
    t = html_body or ""
    t = _re.sub(r"(?is)<(style|script)\b.*?</\1>", "", t)
    t = _re.sub(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f"{m.group(2)} ({m.group(1)})", t)
    t = _re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = _re.sub(r"(?i)</(p|div|h\d|li|tr|table)>", "\n\n", t)
    t = _re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    t = _re.sub(r"[ \t]+", " ", t)
    t = _re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", t)
    return "\n".join(r.strip() for r in t.strip().split("\n"))


def vang_op(lijst):
    """Vanaf nu op deze draad geen mail versturen maar in lijst zetten; None stopt het."""
    _opvang.lijst = lijst


def send_email(to_email, subject, html_body, koppen=None):
    """Verstuurt een e-mail via de Brevo API. Geeft True/False terug, faalt
    nooit hard (een mislukte e-mail mag de rest van de afhandeling niet
    blokkeren).

    Met 'koppen' kan je extra mailkoppen meegeven, bijvoorbeeld de afmeldkop
    waar Gmail en Outlook hun eigen knop 'Afmelden' van maken."""
    lijst = getattr(_opvang, "lijst", None)
    if lijst is not None:
        lijst.append({"aan": to_email, "onderwerp": subject, "html": html_body})
        return True
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
        # 1 oktober (mail-tester gaf -0.1 voor MIME_HTML_ONLY): ook een versie
        # in platte tekst. Spamfilters vertrouwen een mail met beide meer, en
        # wie mail als tekst leest, ziet geen kale HTML.
        "textContent": platte_tekst(html_body),
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
# Zelfde namen als in _stijl.html, zodat je ze terugvindt. 30 september: ook de
# koude mail en de losse mails in deze kleuren (inkt, grijzen, EEN blauw, groen
# voor goed); geen rood of oranje meer, dat kent de huisstijl niet.
INKT = "#0A0A0B"
INKT_ZACHT = "#4A4A55"
LIJN = "#E7E7E4"
VLAK = "#F7F7F5"
# 8 oktober (versie 10, Nino: "pas alles aan naar de huidige look, ook de mail"):
# de knop is zwart, net als elke hoofdknop op de site; papierwit achter de kaart.
KNOP = "#0A0A0B"
PAPIER = "#F7F7F5"
BLAUW = "#1B3FE0"
BLAUW_TEKST = "#142FA8"
GOED = "#0B7C5E"
MIS = "#4A4A55"

VOETTEKST = ("Questions? Just reply to this email, a person reads it.<br>"
             "Krillo &middot; Gerard Doustraat 22-3V, 1072 VW Amsterdam &middot; "
             "Chamber of Commerce 78439620")


def _base_html(title, intro, body_html, taal="en"):
    """Het kader om ELKE mail (herschreven 8 oktober).

    Nino: "alle mails moeten dezelfde stijl hebben en niet zo standaard eruit
    zien, het is gewoon AI-generated". Gekeken naar hoe Stripe, Linear, Peec
    en Shopify hun mails opbouwen. Wat ze gemeen hebben, en wat hier nu ook zo is:
    - een rustige grijze achtergrond met een witte kaart in het midden, zodat
      de mail er in elk mailprogramma uitziet als een product en niet als tekst;
    - bovenaan alleen het woordmerk, dan een korte kop en een zin eronder;
    - een duidelijke knop (als tabel gebouwd, dan werkt hij ook in Outlook);
    - feiten in een rustig vak (_feiten), niet verstopt in lopende tekst;
    - de voettekst klein en grijs onder de kaart, met adres en KVK;
    - een verborgen voorvertoning: de zin die Gmail naast het onderwerp toont.
    Alle mails gebruiken dit kader, dus ze veranderen in een keer mee.
    Tabellen en inline stijlen: Gmail en Outlook negeren <style> en flex."""
    voorvertoning = (re.sub(r"<[^>]+>", "", intro or title) if (intro or title) else "")
    intro_html = (f'<p style="color:{INKT_ZACHT}; font-size:15px; line-height:1.6; margin:0 0 22px;">{intro}</p>'
                  if intro else '<div style="height:10px; line-height:10px;">&nbsp;</div>')
    return f"""
    <div style="background:{PAPIER}; padding:32px 12px; margin:0;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">{voorvertoning}&#8199;&#65279;&#847; &#8199;&#65279;&#847; &#8199;&#65279;&#847;</div>
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px; margin:0 auto;">
      <tr><td style="padding:0 4px 16px; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">
        <span style="font-family:'Space Grotesk', -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; font-weight:700; font-size:18px; letter-spacing:-0.04em; color:{INKT};">KRILLO</span>
        <span style="font-family:'Courier New', monospace; font-size:10px; color:#6E7079; letter-spacing:0.12em; margin-left:6px;">INDEX</span>
      </td></tr>
      <tr><td style="background:#FFFFFF; border:1px solid {LIJN}; border-radius:18px; padding:34px 34px 30px;
                     font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; color:{INKT};">
        <h1 style="font-size:24px; line-height:1.25; margin:0 0 8px; letter-spacing:-0.02em; font-weight:600; color:{INKT};">{title}</h1>
        {intro_html}
        {body_html}
      </td></tr>
      <tr><td style="padding:18px 6px 0; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
                     color:#8A8C96; font-size:12px; line-height:1.6;">
        {VOETTEKST}
      </td></tr>
    </table>
    </div>
    """


def _feiten(rijen):
    """Een rustig vak met feiten, een per regel: [("Store", "x.nl"), ...].
    Zoals Stripe een betaling samenvat: links het label, rechts het feit."""
    regels = "".join(
        f'<tr><td style="padding:9px 0; font-size:13.5px; color:#6E7079; border-top:{"0" if n == 0 else "1px solid " + LIJN};">{label}</td>'
        f'<td align="right" style="padding:9px 0; font-size:13.5px; color:{INKT}; font-weight:600; border-top:{"0" if n == 0 else "1px solid " + LIJN};">{waarde}</td></tr>'
        for n, (label, waarde) in enumerate(rijen))
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="background:{VLAK}; border-radius:10px; padding:6px 16px; margin:4px 0 22px;">{regels}</table>')


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

    In het Engels sinds 21 september, net als het formulier op /withdrawal.
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
    <p style="font-size:13.5px; color:#4A4A55;">Wettelijke termijn: binnen veertien dagen afhandelen en eventueel terugbetalen via dezelfde betaalmethode.</p>
    """
    html = _base_html("Herroeping ontvangen", "Actie nodig.", body)
    return send_email(beheerder_email, "Herroeping bij Krillo, actie nodig", html)


def send_opzegging_bevestiging(to_email, webshop_url, tot=None, terug=False, proef_tot=None,
                               dashboard_url=None):
    """De bevestiging van een opzegging. Kort, en zonder poging om iemand
    over te halen: wie opzegt en dan een verkoopmail krijgt, komt niet terug.

    Sinds 28 september met de datum tot wanneer hij toegang houdt (tot), of
    dat hij zijn geld terugkrijgt (terug, binnen de veertien dagen).
    8 oktober (Nino stopte zijn proef): bij een gratis proef stond er "the end
    of the period you already paid for", terwijl er niets betaald is. Nu een
    eigen tekst voor de proef (proef_tot), en de feiten in een vak."""
    winkel = veilig(_kaal_adres(webshop_url))
    if proef_tot:
        titel = "Your free trial is stopped"
        intro = "You pay nothing. No payment will be taken."
        feiten = [("Store", winkel), ("Plan", "Watch, free trial"), ("Charged", "Nothing"),
                  ("Access until", f"{proef_tot.day} {proef_tot.strftime('%B %Y')}")]
        slot = ("Until then your dashboard works as usual. After that it keeps your last "
                "measurement, and we stop emailing you.")
    elif terug:
        titel = "Your subscription is cancelled"
        intro = "Your first payment comes back in full."
        feiten = [("Store", winkel), ("Refund", "Your first payment, in full"),
                  ("Back on your account", "Within a few working days"), ("From now on", "Nothing is charged")]
        slot = "You will not get your monthly position email anymore."
    elif tot:
        titel = "Your subscription is cancelled"
        intro = "Nothing more is charged from now on."
        feiten = [("Store", winkel), ("Charged from now on", "Nothing"),
                  ("Access until", f"{tot.day} {tot.strftime('%B %Y')}")]
        slot = ("Until then everything keeps running, including your monthly position email. "
                "After that it simply stops.")
    else:
        titel = "Your subscription is cancelled"
        intro = "Nothing more is charged from now on."
        feiten = [("Store", winkel), ("Charged from now on", "Nothing")]
        slot = "You will not get your monthly position email anymore."
    body = (_feiten(feiten) + _p(slot)
            + _p("Changed your mind? You can start again any time from your dashboard or at krilloai.com.",
                 zacht=True)
            + _score_button(dashboard_url, "Open your dashboard"))
    html = _base_html(titel, intro, body)
    onderwerp = ("Confirmation: your Krillo trial is stopped, you pay nothing" if proef_tot
                 else "Confirmation: your Krillo subscription is cancelled")
    return send_email(to_email, onderwerp, html)


def _score_button(report_url, label="Open your dashboard"):
    """De knop. Zwart, zoals elke hoofdknop op de site sinds versie 10 (8
    oktober). Als tabel, dan houdt Outlook het vlak en de afronding."""
    if not report_url:
        return ""
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 4px;"><tr>
      <td style="background:{KNOP}; border-radius:10px;">
        <a href="{report_url}" style="display:inline-block; padding:14px 24px; color:#FFFFFF;
           text-decoration:none; font-weight:600; font-size:15px;">{label} &rarr;</a></td></tr></table>
    """


def send_audit_email(to_email, webshop_url, scan_result, fix_previews, report_url=None, taal="nl"):
    score = scan_result.get("score", 0)
    problemen = [c for c in scan_result.get("checks", []) if c["status"] != "ok"]
    score_color = "#0B7C5E" if score >= 80 else ("#4A4A55" if score >= 40 else MIS)
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
    <div style="background:#0A0A0B; border-radius:12px; padding:24px; margin-bottom:20px; text-align:center;">
      <div style="font-family:'Courier New',monospace; font-size:11px; color:#A9AAB2; text-transform:uppercase; margin-bottom:8px;">{kopje}</div>
      <div style="font-size:40px; font-weight:700; color:{score_color};">{score}<span style="font-size:18px; color:#A9AAB2;">/100</span></div>
      <div style="font-size:13px; color:#D6D6DC; margin-top:4px;">{webshop_url}</div>
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
    # 30 september: WordPress en WooCommerce koppelen nu zelf, met een
    # applicatiewachtwoord op de eigen koppelpagina. Geen beheerdersaccount
    # voor ons meer: veiliger voor de klant, en wij schrijven dan zelf in de
    # winkel in plaats van met de hand (wordpress_werk.py).
    if platform in ("WooCommerce", "WordPress") and monitoring_url and "/mijn/" in monitoring_url:
        koppel = monitoring_url.rstrip("/").split("/mijn/")[0] + "/mijn/" + \
            monitoring_url.rstrip("/").split("/mijn/")[1].split("/")[0] + "/wordpress"
        stappen = f"""
      <li>In WordPress, go to Users, Profile (Gebruikers, Profiel) and scroll down to
          Application Passwords (Applicatiewachtwoorden).</li>
      <li>Type <strong>Krillo</strong> as the name and click Add New Application Password.
          Copy the password WordPress shows. It is not your login password: it only works
          for this connection.</li>
      <li>Open <a href="{veilig(koppel)}">your connection page</a> and paste your store
          address, your WordPress username and that password.</li>
      <li>You can revoke it any time, in the same place in WordPress or on that page.</li>"""
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
    return veilig + ("<br>[shortened]" if afgekapt else "")


def _zonder_html(tekst):
    """HTML uit een producttekst: koppen en alinea's worden regels, de rest valt weg."""
    import html as _h
    import re as _re
    if not tekst:
        return tekst
    t = _re.sub(r"(?i)<\s*(br|/p|/h\d|/li)\s*/?>", "\n", str(tekst))
    t = _re.sub(r"<[^>]+>", "", t)
    t = _h.unescape(t)
    return _re.sub(r"\n{3,}", "\n\n", t).strip()


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
        # 1 oktober: productteksten staan als HTML in de winkel ("<p>...</p>"), en
        # die tags stonden letterlijk in de mail. De klant wil de tekst lezen.
        oud = _veilig(_zonder_html(w.get("oude_waarde")))
        nieuw = _veilig(_zonder_html(w.get("nieuwe_waarde")))
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
# Versie c (30 september, Nino's idee): de vraag die de homepage ook stelt,
# "Is jouw winkel een van de drie die AI noemt?". Een vraag in plaats van een
# cijfer; de telling per versie laat zien of dat vaker geopend wordt.
# Versie d (1 oktober, stap 225): "AI kent je, maar raadt je niet aan". Alleen
# voor winkels die vaak genoemd en zelden aangeraden worden (d_geschikt), met
# een letterlijk citaat uit de meting. Dat is concreter dan een plek, en het zegt
# meteen wat Fix doet. De telling vergelijkt d met de rest; let op dat d alleen
# naar winkels gaat die al genoemd worden (die klikken van zichzelf al vaker).
MAILVARIANTEN = ("a", "b", "c", "d")


def d_geschikt(beeld):
    """Vaak genoemd (3 keer of meer), en in hoogstens een derde daarvan aangeraden."""
    if not beeld:
        return False
    genoemd, aanbevolen = int(beeld.get("genoemd") or 0), int(beeld.get("aanbevolen") or 0)
    return genoemd >= 3 and aanbevolen * 3 <= genoemd


def kies_variant(webshop_url, d_mag=False):
    """Welke versie een winkel krijgt. Vast per winkel (zelfde adres, zelfde
    versie), zodat een tweede mail aan dezelfde winkel nooit de telling
    vervuilt. Welke versies meedoen staat in MAIL_VARIANTEN (Render),
    standaard alle vier. Versie d alleen als d_mag (zie d_geschikt)."""
    import hashlib
    actief = [v.strip() for v in (os.environ.get("MAIL_VARIANTEN") or "a,b,c,d").split(",")
              if v.strip() in MAILVARIANTEN and (d_mag or v.strip() != "d")] or ["a"]
    getal = int(hashlib.sha256((webshop_url or "").encode()).hexdigest(), 16)
    return actief[getal % len(actief)]


# In welke taal wij de koopvragen stelden, voor het labeltje boven de vraag.
# Een Nederlandse vraag in een Engelse mail zonder uitleg leest als een fout.
_TAALNAAM = {"nl": "Dutch", "de": "German", "fr": "French", "en": "English",
             "es": "Spanish", "it": "Italian"}


def send_onderzoeksmail(to_email, webshop_url, link_url, beeld=None,
                        categorienaam=None, landnaam=None, afmeld_url=None,
                        onderwerp_voor="", variant="a", platform=None, concurrent_is_klant=False,
                        leverancier=None, citaat=None):
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
    # 8 oktober: nul keer genoemd is geen plek op alfabet (db.gelijk_bij_nul).
    groot_plek = ("Not named by AI yet" if beeld.get("nul") else f"#{positie} of {van}")
    genoemd, telbaar = beeld.get("genoemd") or 0, beeld.get("telbaar") or 0

    # Sinds 28 september dezelfde handtekening als elke persoonlijke mail.
    ondertekening = handtekening_html()

    if afmeld_url:
        afmelden = (f'Rather not hear about this? Use '
                    f'<a href="{afmeld_url}" style="color:#6E7079;">this link</a>: one click, '
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
                f'<tr><td style="padding:4px 0; font-size:14.5px; color:#0A0A0B;">'
                f'<span style="color:#0B7C5E; font-weight:700;">&#10003;</span>'
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
            regels += (f'<tr><td style="padding:4px 0; font-size:14.5px; color:#0A0A0B; '
                       f'font-weight:600;"><span style="font-weight:700;">&#10005;</span>'
                       f'&nbsp;&nbsp;{winkel} was not named</td></tr>')
            voorbeeld = f"""
          <div style="font-size:11.5px; color:#6E7079; letter-spacing:.06em;
                      text-transform:uppercase; margin:22px 0 10px;">
            {e(label)}</div>
          <table role="presentation" cellpadding="0" cellspacing="0">
            <tr><td style="background:#F7F7F9; border-radius:14px 14px 14px 4px;
                           padding:12px 16px; font-size:15.5px; font-weight:600;
                           color:#0A0A0B; line-height:1.4;">{e(vraag)}</td></tr>
          </table>
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                 style="margin-top:12px;">{regels}</table>"""
            break

    zichtbaar = e(_kaal_adres(link_url).split("/")[0])

    # Nummer 1 heeft niets te repareren maar wel iets te verliezen. Een zin
    # erbij, zoals de balk op de ranglijst dat ook zegt.
    bij_een = ("Staying #1 is the hard part: the ranking is measured again every month, "
               "and the stores below you are moving too. ") if positie == 1 else ""

    # Stap 156 (28 september): een kleine Shopify-winkel wil weten dat het werk
    # niet op hem neerkomt. Alleen als de adresvinder of scan Shopify zag; nooit
    # gegokt.
    # 30 september: hier stond dat de app "on the Shopify App Store" het werk
    # doet, terwijl de app nog bij Shopify ter beoordeling ligt. Dat was niet
    # waar. Nu staat er wat vandaag klopt: met Fix doen wij het in de winkel,
    # en alles kan terug. Voor WooCommerce net zo (koppeling sinds 30 sep).
    shopify_regel = ""
    systeem = {"shopify": "Shopify", "woocommerce": "WooCommerce", "wordpress": "WordPress"}.get(
        (platform or "").lower())
    if systeem:
        shopify_regel = ('<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:10px 0 6px;">'
                         f'Your store runs on {systeem}, so this takes you almost no time: with Fix we '
                         'write the missing product texts and put them in your store for you, and '
                         'you can undo every change.</p>')

    # Stap 217 in de koude mail (30 september): bij een Shopify-winkel een
    # zin uit zijn eigen productteksten letterlijk opgezocht. Alleen als er
    # echt iets gevonden is; anders zeggen we niets.
    if leverancier and leverancier.get("gekopieerd"):
        voorbeeld = next((t["andere"][0] for t in leverancier.get("teksten", []) if t.get("andere")), None)
        shopify_regel += ('<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:10px 0 6px;">'
                          f'We also searched one sentence from {leverancier["van"]} of your product texts: '
                          f'<strong>{leverancier["gekopieerd"]} appear word for word on other sites</strong>'
                          + (f' (for example {e(voorbeeld)})' if voorbeeld else '') +
                          '. When a dozen stores use the same text, AI has no reason to name yours.</p>')

    # Idee Nino, 28 september: zodra een ANDERE winkel in dezelfde categorie
    # echt klant is, zeggen we dat. Zonder naam: dat is van de klant. Het is
    # alleen waar als het waar is; de aanroeper kijkt het na in de database.
    klant_regel = ""
    if concurrent_is_klant:
        klant_regel = ('<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:10px 0 6px;">'
                       f'One store in {cat} already works with Krillo to get named more often.</p>')

    # De eerste zin verschilt per versie, de rest niet (zie MAILVARIANTEN).
    p = '<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
    aanbevolen = beeld.get("aanbevolen") or 0
    if variant == "d":
        # Stap 225: genoemd is niet aangeraden. Met het echte citaat, als we het hebben.
        opening = (f"{p}Every month we ask ChatGPT and Gemini the questions shoppers in {land} "
                   f"ask in the {cat} category. AI knows {winkel}: it named you in {genoemd} of "
                   f"{telbaar} buying questions. "
                   + (f"But it did not recommend you outright once. " if not aanbevolen else
                      f"But it recommended you outright in only {aanbevolen}. ")
                   + f"When a shopper asks where to buy, "
                   f"the tip goes to someone else.</p>")
        if citaat and citaat.get("zin"):
            opening += (f'<div style="border-left:3px solid #1B3FE0; padding:4px 0 4px 14px; margin:0 0 14px;">'
                        f'<div style="font-size:15px; color:#0A0A0B; line-height:1.6;">&ldquo;{"&hellip;" if citaat["zin"][:1].islower() else ""}{e(citaat["zin"])}'
                        f'&rdquo;</div><div style="font-size:12.5px; color:#6E7079; margin-top:4px;">'
                        f'{e(citaat.get("assistent") or "AI")}, word for word from our measurement</div></div>')
    elif variant == "b":
        opening = (f"{p}When shoppers in {land} ask ChatGPT or Gemini where to buy "
                   f"in the {cat} category, a few stores get named and the rest do not. We ask those "
                   f"questions every month and rank the stores. {winkel} is in that "
                   f"ranking.</p>")
    else:
        opening = (f"{p}Every month we ask ChatGPT and Gemini the questions shoppers in {land} "
                   f"ask in the {cat} category, and we rank the stores they name. "
                   f"{winkel} is in that ranking.</p>")

    html = f"""
    <div style="background:#F7F7F9; padding:28px 16px; font-family:-apple-system,
                'Segoe UI', Arial, sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="max-width:560px; margin:0 auto;">
        <tr><td style="background:#FFFFFF; border:1px solid #E8E8EC; border-radius:14px;
                       padding:32px 30px;">

          <div style="font-size:14px; font-weight:700; color:#0A0A0B; letter-spacing:.08em;">
            KRILLO <span style="font-weight:400; color:#6E7079; font-size:11px;
            letter-spacing:.12em;">INDEX</span></div>
          <div style="font-size:12px; color:#6E7079; margin-top:2px;">
            The Krillo Index: which stores AI recommends</div>

          <div style="height:1px; background:#E8E8EC; margin:20px 0 22px;"></div>

          {opening}

          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                 style="border:1px solid #E8E8EC; border-radius:10px; margin:22px 0;">
            <tr><td style="padding:20px 22px;">
              <div style="font-size:12px; color:#4A4A55; letter-spacing:.04em;
                          text-transform:uppercase; margin-bottom:8px;">
                Your place in {cat}, {land}</div>
              <div style="font-size:30px; font-weight:700; color:#0A0A0B; line-height:1.2;">
                {groot_plek}</div>
              <div style="font-size:13.5px; color:#4A4A55; margin-top:8px; line-height:1.55;">
                {onder}</div>
              {voorbeeld}
            </td></tr>
          </table>

          <p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 6px;">
            {bij_een}Your own Krillo page shows where you stand, the buying questions you lose
            with the real AI answer, and what would move you up. No login, and nothing to
            fill in. Want your rank every month and the fixes to win those questions? Watch is
            free for the first 14 days.</p>
          {shopify_regel}
          {klant_regel}

          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 8px;">
            <tr><td style="background:#0A0A0B; border-radius:10px;">
              <a href="{link_url}" style="display:inline-block; padding:13px 26px;
                 color:#FFFFFF; text-decoration:none; font-size:14.5px; font-weight:600;">
                See my Krillo page</a>
            </td></tr>
          </table>
          <p style="font-size:12.5px; color:#6E7079; margin:0 0 4px;">
            The link goes to {zichtbaar}</p>
          {ondertekening}

          <div style="height:1px; background:#E8E8EC; margin:26px 0 16px;"></div>

          <p style="font-size:12.5px; color:#6E7079; line-height:1.7; margin:0;">
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
    elif variant == "c":
        onderwerp = f"{onderwerp_voor}Is {_kaal_adres(webshop_url)} one of the three stores AI names?"
    elif variant == "d":
        onderwerp = f"{onderwerp_voor}{_kaal_adres(webshop_url)}: AI names you, but rarely recommends you"
    else:
        onderwerp = (f"{onderwerp_voor}{_kaal_adres(webshop_url)}: AI names {beeld.get('genoemde_winkels')} stores in your category, not you"
                     if beeld.get("nul") else
                     f"{onderwerp_voor}{_kaal_adres(webshop_url)}: #{positie} of {van} in the Krillo index")
    return send_email(to_email, onderwerp, html, koppen=koppen)


def welkom_v2_html(webshop_url, report_url, pakket="watch", score=None, gratis_tot=None,
                   plek=None, wachtwoord=False):
    """ONTWERP voor een nieuwe welkomstmail (8 oktober), NOG NIET IN GEBRUIK.

    Nino: "de welkomstmail is nog te standaard, het is alleen tekst". De huidige
    mail is zeven alinea's lopende tekst; de knop staat helemaal onderaan. Hoe
    Peec, Semrush, Stripe en Linear het doen: een korte kop, meteen de knop,
    dan een lijstje van drie stappen met nummers (wat wij nu doen, wat jij doet,
    wat er elke maand komt), de proefperiode in een eigen kader, en klaar.
    Dit is die opbouw, met dezelfde feiten als de oude mail en niets erbij.
    Pas na akkoord van Nino gaat send_monitoring_welcome_email dit gebruiken.

    Gebouwd met tabellen en inline stijlen: Gmail en Outlook negeren <style>
    en flex, en dan valt een mail uit elkaar."""
    winkel = veilig(_kaal_adres(webshop_url))
    is_fix = (pakket or "").lower() not in ("watch", "")
    naam = "Fix" if is_fix else "Watch"
    groen, groen_bg, blauw_bg = "#0B7C5E", "#E7F6EF", "#EEF1FD"

    def stap(nr, kop, tekst, kleur=BLAUW, bg=blauw_bg, knop=None):
        knop_html = (f'<div style="margin-top:8px;"><a href="{knop[1]}" style="color:{BLAUW}; '
                     f'font-weight:600; font-size:13.5px; text-decoration:none;">{knop[0]} &rarr;</a></div>'
                     if knop else "")
        return f"""
        <tr><td style="padding:14px 0; border-top:1px solid {LIJN};">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
            <td valign="top" width="40" style="padding-right:12px;">
              <div style="width:28px; height:28px; line-height:28px; border-radius:14px; background:{bg};
                          color:{kleur}; font-weight:700; font-size:13px; text-align:center;">{nr}</div>
            </td>
            <td valign="top" style="font-size:14.5px; line-height:1.55; color:{INKT_ZACHT};">
              <div style="font-weight:700; color:{INKT}; margin-bottom:2px;">{kop}</div>
              {tekst}{knop_html}
            </td>
          </tr></table>
        </td></tr>"""

    if wachtwoord:
        eerste = stap("!", "First: open your store",
                      "Your store is behind a password, so AI cannot read it and neither can we. "
                      "In Shopify: Online Store, Preferences, remove the password. We pick it up by ourselves.",
                      kleur="#B4471A", bg="#FFF1E8")
    elif plek and plek.get("positie") and plek.get("nul"):
        eerste = stap("&#10003;", "Your starting point: AI does not name you yet",
                      f"{plek.get('genoemde_winkels')} of {plek['van']} stores in your category are named. "
                      "Your dashboard shows who, for which question, and what to change first.",
                      kleur=groen, bg=groen_bg)
    elif plek and plek.get("positie"):
        eerste = stap("&#10003;", f"You are #{plek['positie']} of {plek['van']} in your category",
                      "From this month's measurement. Your dashboard shows each buying question "
                      "where AI names another store, and which one.", kleur=groen, bg=groen_bg)
    else:
        eerste = stap("1", "Now: we place you in your category",
                      "We are adding your store to this month's ranking, from the answers ChatGPT and "
                      "Gemini already gave, and writing your first fixes. Usually within the hour; "
                      "we email you when your rank is in.")
    if is_fix:
        tweede = stap("2", "We place your sales pixel for you",
                      "Once you give us access to your store, we add the Krillo pixel, so every month "
                      "you see the visits, orders and revenue AI brings you. You get a separate email "
                      "about access.")
    else:
        tweede = stap("2", "You: connect your sales (2 minutes)",
                      "Paste the Krillo pixel into Shopify (Settings, Customer events) or your site. "
                      "Then you see what AI brings you in visits, orders and revenue. "
                      "Rather not? Reply and we place it for you.",
                      knop=("Show me how", f"{report_url}#start-pixel") if report_url else None)
    derde = stap("3", "Every week and every month",
                 "Every week your five most important buying questions are asked again, so you see "
                 "whether a change works. Every month we measure your whole category and send you "
                 "your position. "
                 + ("We pick the fixes that gain you the most and we install them in your store, "
                    "keeping the old text so it can always go back."
                    if is_fix else
                    "Your dashboard shows the three fixes that gain you the most, ready to copy."))

    cijfer = (f'<td width="50%" style="padding:14px 16px; border:1px solid {LIJN}; border-radius:10px;">'
              f'<div style="font-family:Courier New, monospace; font-size:10.5px; letter-spacing:.08em; color:#6E7079;">SITE CHECK TODAY</div>'
              f'<div style="font-size:24px; font-weight:700; color:{INKT}; margin-top:4px;">{score}<span style="font-size:13px; color:#6E7079; font-weight:400;"> / 100</span></div>'
              f'<div style="font-size:12.5px; color:{INKT_ZACHT};">How well AI can read your store</div></td>'
              if score is not None and not wachtwoord else "")
    proef = (f'<td width="50%" style="padding:14px 16px; background:#FAFAFB; border:1px solid {LIJN}; border-radius:10px;">'
             f'<div style="font-family:Courier New, monospace; font-size:10.5px; letter-spacing:.08em; color:#6E7079;">FREE UNTIL</div>'
             f'<div style="font-size:24px; font-weight:700; color:{INKT}; margin-top:4px;">{gratis_tot.strftime("%-d %b")}</div>'
             f'<div style="font-size:12.5px; color:{INKT_ZACHT};">Then EUR 49 a month. Cancel any time on the Plan page.</div></td>'
             if gratis_tot else "")
    if score is None and not wachtwoord:
        # Geen gelukte scan bij de start: geen verzonnen cijfer, wel wanneer hij komt.
        cijfer = (f'<td width="50%" style="padding:14px 16px; border:1px solid {LIJN}; border-radius:10px;">'
                  f'<div style="font-family:Courier New, monospace; font-size:10.5px; letter-spacing:.08em; color:#6E7079;">SITE CHECK</div>'
                  f'<div style="font-size:15px; font-weight:700; color:{INKT}; margin-top:6px;">Coming up</div>'
                  f'<div style="font-size:12.5px; color:{INKT_ZACHT};">The first one follows within a week.</div></td>')
    tegels = ""
    if cijfer or proef:
        tussen = '<td width="12">&nbsp;</td>' if (cijfer and proef) else ""
        tegels = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                  f'style="margin:22px 0 6px;"><tr>{cijfer}{tussen}{proef}</tr></table>')

    knop = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:20px 0 4px;"><tr>'
            f'<td style="background:{KNOP}; border-radius:10px;"><a href="{report_url}" style="display:inline-block; '
            f'padding:13px 24px; color:#FFFFFF; font-weight:600; font-size:15px; text-decoration:none;">'
            f'Open your dashboard &rarr;</a></td></tr></table>'
            f'<p style="font-size:12.5px; color:#6E7079; margin:6px 0 0;">No password: this link is your key, so keep this email.</p>'
            if report_url else "")

    body = (f'<p style="font-size:15px; line-height:1.6; color:{INKT_ZACHT}; margin:0;">'
            f'Your {naam} plan for <strong style="color:{INKT};">{winkel}</strong> is live. '
            f'Here is what happens next.</p>'
            + knop + tegels
            + f'<div style="font-family:Courier New, monospace; font-size:10.5px; letter-spacing:.08em; '
              f'color:#6E7079; margin:26px 0 4px;">WHAT HAPPENS NEXT</div>'
            + f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
              f'{eerste}{tweede}{derde}</table>')
    return _base_html(f"Welcome to Krillo {naam}", "", body).replace(
        f'<p style="color:{INKT_ZACHT}; font-size:14.5px; line-height:1.6; margin:0 0 18px;"></p>', "")


def send_monitoring_welcome_email(to_email, webshop_url, scan_result, report_url=None,
                                  taal="en", pakket="fix", gratis_tot=None, plek=None):
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
    # 8 OKTOBER (Nino: "doe maar nieuwe welkomstmail, kijk naar de beste
    # manier"): het nieuwe ontwerp (welkom_v2_html) is nu de mail: de knop
    # bovenaan, sitecheck en proefdatum in twee vakken, drie genummerde
    # stappen. Dezelfde feiten als hieronder, minder tekst. Het oude ontwerp
    # blijft staan voor het pakket voor merken en bureaus.
    if (pakket or "").lower() in ("watch", "fix"):
        score = (scan_result or {}).get("score") if (scan_result or {}).get("checks") else None
        wachtwoord = (scan_result or {}).get("weigering") == "wachtwoord"
        naam = "Watch" if (pakket or "").lower() == "watch" else "Fix"
        html = welkom_v2_html(webshop_url, report_url, pakket, score=score, gratis_tot=gratis_tot,
                              plek=plek, wachtwoord=wachtwoord)
        return send_email(to_email, f"Welcome to Krillo {naam}", html)
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
        # 1 oktober, de klantreis nagelopen. Hier stond "about fifteen minutes"
        # en "for a category we do not measure yet, that can take a few days".
        # Nu: staat hij al in de ranglijst, dan zeggen we zijn plek. Zo niet, dan
        # zetten we hem er meteen in (uit de antwoorden van deze maand), of
        # meten we zijn categorie meteen (klantmeetrij). Geen dagen wachten.
        + _p("<strong>Right now.</strong> We are putting thirty buying questions that shoppers "
             "in your category really ask to ChatGPT and Gemini, and writing your first fixes. "
             "That usually takes less than an hour; your dashboard fills itself.")
        # 7 oktober (Nino): stap een voor de klant is de pixel, zodat hij na een
        # maand vanzelf ziet wat AI hem oplevert (stap 304).
        + (_p("<strong>Your sales, connected.</strong> We place the Krillo pixel in your store "
              "for you, so you see every month the visits, orders and revenue AI brings you.")
           if naam == "Fix" else
           _p("<strong>Step 1 for you: connect your sales (2 minutes).</strong> In your dashboard, "
              "under \u201cIs AI sending you visitors and sales?\u201d, copy the Krillo pixel and paste it "
              "into Shopify (Settings, Customer events) or into your site. From then on you see every "
              "month the visits, orders and revenue AI brings you. Rather not do it yourself? Reply "
              "to this email and we place it for you."))
        # 8 oktober: nul keer genoemd is geen plek; dan zeggen we dat eerlijk.
        + (_p(f"<strong>Your rank.</strong> This month AI did not name your store in any buying "
              f"question in your category; {plek.get('genoemde_winkels')} of {plek['van']} stores were "
              f"named. That is your starting point. Your dashboard shows who AI names instead, and "
              f"what to change first.") if plek and plek.get("positie") and plek.get("nul") else
           _p(f"<strong>Your rank.</strong> You are already in the Krillo Index: "
              f"<strong>#{plek['positie']} of {plek['van']}</strong> in your category, from this "
              f"month's measurement. Your dashboard shows the questions where AI names another "
              f"store, and who.") if plek and plek.get("positie") else
           _p("<strong>Your rank.</strong> We are adding your store to this month's ranking of "
              "your category now, from the answers AI already gave. That usually takes a few "
              "minutes. If your category is new for us, we measure it for you first, which "
              "usually takes less than an hour. Either way, we email you when your rank is in."))
        + _p("<strong>Every month.</strong> We measure your whole category again, and that is "
             "where your rank in the index comes from. You get a message with your position, "
             "and a message when you drop three places or more. Your store also gets the "
             "thirteen technical checks every week"
             # Alleen een cijfer als de scan gelukt is (23 september). Mislukt
             # hij bij de start, dan gaat de klant toch door en stond hier
             # anders "0 of 100", terwijl er niets gemeten was.
             + (f"; it scores {score} of 100 on them today." if (scan_result or {}).get("checks")
                else "; the first one follows within a week.")
             + " <strong>Every week</strong> we also ask your five most important buying questions "
               "again, so you see within a week whether a change works.")
        + werk
        # Stap 167: bij de gratis proef precies zeggen wanneer er iets betaald wordt.
        + (_p(f"<strong>Your free trial.</strong> Watch is free until {gratis_tot.strftime('%d-%m-%Y')}. "
              f"After that it is EUR 49 a month by direct debit, and you can cancel any month. Cancel "
              f"before then on the Plan page of your dashboard and you pay nothing. We remind you three "
              f"days before it ends.") if gratis_tot else "")
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
                             onderwerp=None, kop=None, intro=None, feiten=None):
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
    # 8 oktober: feiten (plek, vragen) in een vak boven de tekst, zoals Stripe.
    body = (_feiten(feiten) if feiten else "") + alineas + _score_button(monitoring_url, "Open your dashboard")
    html = _base_html(kop or standaard_kop, intro or f"The latest on {veilig(winkel)}.", body)
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




def handtekening_html():
    """De handtekening onder elke persoonlijke mail (opvolging, antwoord, koude
    mail). 28 september, Nino: "nu sluiten wij af met Nino, hoe maken we het
    professioneler". Naam en functie uit Render (AFZENDER_NAAM, AFZENDER_TITEL),
    zodat een volledige naam geen codewijziging vraagt. Bewust zonder plaatje:
    een logo als afbeelding laat mail vaker in de spam belanden en wordt door
    veel programma's eerst geblokkeerd."""
    e = _html.escape
    naam = (os.environ.get("AFZENDER_NAAM") or "Nino").strip()
    titel = (os.environ.get("AFZENDER_TITEL") or "Founder").strip()
    return f"""
      <p style="font-size:15px; color:#0A0A0B; margin:20px 0 10px;">Kind regards,</p>
      <table cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr><td style="border-left:3px solid {BLAUW}; padding:2px 0 2px 12px;
                       font-family:-apple-system,'Segoe UI',Arial,sans-serif;">
          <div style="font-size:15px; font-weight:700; color:#0A0A0B;">{e(naam)}</div>
          <div style="font-size:13px; color:#4A4A55;">{e(titel)}, Krillo</div>
          <div style="font-size:13px; color:#4A4A55; margin-top:4px;">
            <a href="https://krilloai.com" style="color:{BLAUW}; text-decoration:none;">krilloai.com</a>
            &middot; <a href="mailto:hello@krilloai.com" style="color:{BLAUW}; text-decoration:none;">hello@krilloai.com</a></div>
          <div style="font-size:12px; color:#6E7079; margin-top:2px;">AI visibility for online stores</div>
        </td></tr>
      </table>"""


def send_opvolging(to_email, onderwerp, alinea_s, link_url, afmeld_url=None):
    """De persoonlijke opvolging van de verkoopagent (stap 125).

    Bewust een gewone, korte mail zonder grote blokken: dit is een briefje van
    een mens aan iemand die zijn pagina al bekeek, geen tweede reclame. De
    alinea's komen uit verkoopagent.maak_concept en zijn al nagekeken."""
    if not _gekeurd(onderwerp, alinea_s, "opvolging"):
        return False
    e = _html.escape
    naam = (os.environ.get("AFZENDER_NAAM") or "").strip()
    g = BEDRIJFSGEGEVENS
    tekst = "".join(f'<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
                    f'{a}</p>' for a in alina_s_veilig(alinea_s))
    afmelden = (f'<a href="{afmeld_url}" style="color:#6E7079;">No more email from us</a>'
                if afmeld_url else "Reply and we remove you the same day.")
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px;
                margin:0 auto; padding:24px 16px;">
      {tekst}
      <p style="font-size:15px; margin:18px 0;"><a href="{link_url}"
         style="color:#1B3FE0; font-weight:600;">Open my Krillo page</a></p>
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        {afmelden} &middot; {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    koppen = ({"List-Unsubscribe": f"<{afmeld_url}>",
               "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"} if afmeld_url else None)
    return send_email(to_email, onderwerp, html, koppen=koppen)


def _gekeurd(onderwerp, alineas, wat):
    """De controleagent (stap 38) als laatste hek voor elke agentmail. Een fout
    (lege invulling, beloofd resultaat, verzonnen termijn) houdt de mail tegen;
    de afgekeurde mails staan in het ochtendbericht. Mag nooit zelf de reden
    zijn dat een goede mail niet weggaat: gaat de keuring stuk, dan door."""
    try:
        import tekstkeuring
        uitkomst = tekstkeuring.keur_mail(onderwerp, alineas)
    except Exception as e:
        print(f"Tekstkeuring mislukt, mail gaat door: {e}")
        return True
    if uitkomst["ok"]:
        return True
    print(f"AFGEKEURD ({wat}): {onderwerp!r}: {'; '.join(uitkomst['fouten'])}")
    try:
        import json as _json
        from datetime import datetime as _dt
        import db
        lijst = _json.loads(db.get_instelling("tekstkeuring_afgekeurd") or "[]")[-19:]
        lijst.append({"op": _dt.now().strftime("%d-%m %H:%M"), "wat": wat, "onderwerp": onderwerp,
                      "fouten": uitkomst["fouten"]})
        db.zet_instelling("tekstkeuring_afgekeurd", _json.dumps(lijst))
    except Exception as e:
        print(f"Afgekeurde mail bewaren mislukt: {e}")
    return False


def alina_s_veilig(alineas):
    """De alinea's zijn tekst van ons, maar namen van winkels en vragen komen uit
    AI-antwoorden. Alles escapen, alleen <strong> van ons zelf terugzetten."""
    uit = []
    for a in alineas or []:
        v = _html.escape(a).replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
        uit.append(v)
    return uit


def send_antwoord(to_email, onderwerp, tekst):
    """Een antwoord van de antwoordagent (stap 126), nadat Nino het goedkeurde.

    Een gewone, kale mail: zo ziet een antwoord van een mens eruit. Geen knop,
    geen blokken. De tekst is platte tekst; alles wordt ge-escaped en alleen
    de regels worden alinea's, zodat een link of naam uit zijn mail nooit als
    HTML meegaat."""
    g = BEDRIJFSGEGEVENS
    alineas = [a.strip() for a in (tekst or "").split("\n\n") if a.strip()]
    lijf = "".join(
        '<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
        + _html.escape(a).replace("\n", "<br>") + "</p>" for a in alineas)
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px;
                margin:0 auto; padding:24px 16px;">
      {lijf}
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    return send_email(to_email, onderwerp, html)



def send_badge(to_email, onderwerp, alinea_s, embedcode, slot, link_url, afmeld_url=None):
    """De felicitatie met badge (stap 89). Zelfde kale, persoonlijke vorm als de
    opvolging, met de code om te plakken in een vak dat je makkelijk selecteert."""
    if not _gekeurd(onderwerp, alinea_s, "badge"):
        return False
    g = BEDRIJFSGEGEVENS
    tekst = "".join(f'<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
                    f'{a}</p>' for a in alina_s_veilig(alinea_s))
    code = _html.escape(embedcode or "")
    afmelden = (f'<a href="{afmeld_url}" style="color:#6E7079;">No more email from us</a>'
                if afmeld_url else "Reply and we remove you the same day.")
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px;
                margin:0 auto; padding:24px 16px;">
      {tekst}
      <div style="background:#F7F7F9; border:1px solid #E8E8EC; border-radius:8px; padding:12px 14px;
                  font-family:Menlo,Consolas,monospace; font-size:12px; color:#0A0A0B; word-break:break-all;
                  margin:0 0 16px;">{code}</div>
      <p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">{_html.escape(slot or "")}</p>
      <p style="font-size:15px; margin:18px 0;"><a href="{link_url}"
         style="color:#1B3FE0; font-weight:600;">See your full ranking</a></p>
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        {afmelden} &middot; {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    koppen = ({"List-Unsubscribe": f"<{afmeld_url}>",
               "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"} if afmeld_url else None)
    return send_email(to_email, onderwerp, html, koppen=koppen)


def send_partner_welkom(to_email, naam, link, procent=20, maanden=12):
    """Stap 94: een goedgekeurde partner krijgt zijn eigen link en de afspraken.
    Kort en persoonlijk, zoals de rest van onze mails."""
    g = BEDRIJFSGEGEVENS
    stijl = 'style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;"'
    aanhef = f"Hi {_html.escape(naam.split()[0])}," if naam else "Hi,"
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px; margin:0 auto; padding:24px 16px;">
      <p {stijl}>{aanhef}</p>
      <p {stijl}>Welcome as a Krillo partner. This is your own link:</p>
      <div style="background:#F7F7F9; border:1px solid #E8E8EC; border-radius:8px; padding:12px 14px;
                  font-family:Menlo,Consolas,monospace; font-size:14px; color:#0A0A0B; word-break:break-all;
                  margin:0 0 16px;">{_html.escape(link)}</div>
      <p {stijl}>How it works: a store that opens your link and starts a paid plan within 60 days counts as
         yours. You get {procent} percent of what that store pays us (excluding VAT), for as long as it pays, up to {maanden} months.
         Once a month we send you an overview; you send us an invoice and we pay within 14 days.</p>
      <p {stijl}>Tip: the free check on our homepage is the easiest start for your clients. It shows their rank
         in the Krillo Index and the buying questions where ChatGPT names someone else.</p>
      <p {stijl}>Questions? Just reply to this email.</p>
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    return send_email(to_email, "Your Krillo partner link", html)


def send_gratis_maand(to_email, webshop_url, nieuwe_winkel, volgende_datum):
    """Doorverwijzen: de doorverwijzer hoort dat zijn volgende maand gratis is.
    Kort, met de datum waarop hij weer betaalt, zodat het geen verrassing is."""
    body = (_p(f"The store you referred, {_html.escape(nieuwe_winkel)}, has now been a customer for 30 days. "
               f"As promised, your next month is free.")
            + _feiten([("Your store", _html.escape(webshop_url)), ("Your next payment", _html.escape(str(volgende_datum)))])
            + _p("We simply skipped one payment, there is nothing for you to do. Thank you for spreading the word.", zacht=True)
            + handtekening_html())
    html = _base_html("Your next month is free", "Thank you for the referral.", body)
    return send_email(to_email, "Your next month with Krillo is free", html)


def send_bureau_mail(to_email, onderwerp, alineas, link_url, afmeld_url, partners_url="https://krilloai.com/partners"):
    """Stap 115: de mail aan een bureau. Zelfde kale, persoonlijke vorm als de
    opvolging, met een link naar zijn pagina en afmelden met een klik."""
    if not _gekeurd(onderwerp, alineas, "bureau"):
        return False
    g = BEDRIJFSGEGEVENS
    tekst = "".join(f'<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
                    f'{a}</p>' for a in alina_s_veilig(alineas))
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px; margin:0 auto; padding:24px 16px;">
      {tekst}
      <p style="font-size:15px; margin:18px 0;"><a href="{link_url}" style="color:#1B3FE0; font-weight:600;">See your clients in the index</a>
         &middot; <a href="{partners_url}" style="color:#1B3FE0;">The partner program</a></p>
      <p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">Interested? Just reply.</p>
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        <a href="{afmeld_url}" style="color:#6E7079;">No more email from us</a> &middot;
        {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    koppen = {"List-Unsubscribe": f"<{afmeld_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return send_email(to_email, onderwerp, html, koppen=koppen)



def send_lijstje_mail(to_email, onderwerp, alineas, link_url, afmeld_url):
    """De lijstjesagent (29 september): een schrijver van een artikel met GEO-tools.
    Kaal en persoonlijk, met een afmeldlink die met een klik werkt."""
    if not _gekeurd(onderwerp, alineas, "lijstje"):
        return False
    g = BEDRIJFSGEGEVENS
    tekst = "".join(f'<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
                    f'{a}</p>' for a in alina_s_veilig(alineas))
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px; margin:0 auto; padding:24px 16px;">
      {tekst}
      <p style="font-size:15px; margin:18px 0;"><a href="{link_url}" style="color:#1B3FE0; font-weight:600;">See the Krillo Index</a></p>
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        <a href="{afmeld_url}" style="color:#6E7079;">No more email from us</a> &middot;
        {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    koppen = {"List-Unsubscribe": f"<{afmeld_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return send_email(to_email, onderwerp, html, koppen=koppen)


def send_klantbericht(to_email, onderwerp, alineas, link_url, knop="Open my Krillo page"):
    """Een persoonlijk bericht aan een KLANT (stap 99, 130, 152): behoud,
    overstappen, terugwinnen. Zelfde kale vorm als de opvolging, zonder
    afmeldregel (het is een klant), wel met de keuring ervoor."""
    if not _gekeurd(onderwerp, alineas, "klant"):
        return False
    g = BEDRIJFSGEGEVENS
    tekst = "".join(f'<p style="font-size:15px; color:#0A0A0B; line-height:1.65; margin:0 0 14px;">'
                    f'{a}</p>' for a in alina_s_veilig(alineas))
    html = f"""
    <div style="font-family:-apple-system,'Segoe UI',Arial,sans-serif; max-width:560px; margin:0 auto; padding:24px 16px;">
      {tekst}
      <p style="font-size:15px; margin:18px 0;"><a href="{link_url}" style="color:#1B3FE0; font-weight:600;">{_html.escape(knop)}</a></p>
      {handtekening_html()}
      <p style="font-size:12px; color:#6E7079; line-height:1.6; margin-top:28px;">
        {g['naam']}, {g['adres']}, {g['plaats']}, KVK {g['kvk']}</p>
    </div>"""
    return send_email(to_email, onderwerp, html)


def send_persbericht(to_email, onderwerp, tekst):
    """Het maandelijkse persbericht (persagent.py). Platte tekst in een kale
    mail: redacties kopieren eruit, en opmaak zit dan in de weg."""
    html = ('<div style="font-family:-apple-system,\'Segoe UI\',Arial,sans-serif; max-width:640px; '
            'margin:0 auto; padding:24px 16px; font-size:15px; color:#0A0A0B; line-height:1.6; '
            'white-space:pre-wrap;">' + _html.escape(tekst) + "</div>")
    return send_email(to_email, onderwerp, html)
